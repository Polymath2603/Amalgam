/**
 * ws.js — WebSocket connection and message handling
 */
import { BASE_URL, WS_BASE, IS_TAURI } from './config.js';
import { showToast, applyTheme } from './utils.js';
import {
    getSettings, setSettingsCache,
    getWs, setWs,
    getCurrentAssistantMessage, setCurrentAssistantMessage,
    getLastUserMessage, setLastUserMessage,
    getVoiceInputEnabled, getVoiceOutputEnabled,
    getCurrentSessionId, setCurrentSessionId,
    streamBuffer, getStreamBufferTimer, setStreamBufferTimer,
    getAvatarRenderer, getAvatarPreviewRenderer,
    getIsPlayingTTS, getTtsQueue, getTtsFlushRequested,
} from './state.js';
import { isBrowserStt, updateVoiceState, stopBrowserSpeechRec, startBrowserSpeechRec } from './voice.js';
import { processTTSQueue, flushTTSQueue } from './tts.js';
import { stripMarkers, formatMessage, updateToolCall } from './markdown.js';
import { updateHealthBar } from './health.js';
import { t } from '../i18n.js';

// Callbacks set by orchestrator
let _addMessage = null;
let _setStatus = null;
let _loadSession = null;
let _fetchCommands = null;
let _loadCharacters = null;
let _applySettings = null;

export function setWsCallbacks({ addMessage, setStatus, loadSession, fetchCommands, loadCharacters, applySettings }) {
    _addMessage = addMessage;
    _setStatus = setStatus;
    _loadSession = loadSession;
    _fetchCommands = fetchCommands;
    _loadCharacters = loadCharacters;
    _applySettings = applySettings;
}

// Reconnect state
let _reconnectAttempts = 0;
const _reconnectDelays = [500, 1000, 2000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000];
let _reconnectTimer = null;
let _reconnectCountdownTimer = null;
const _pendingMessages = [];

// Heartbeat state
let _pingInterval = null;
let _pongPending = false;
let _pongTimeout = null;

// Companion mode
const urlParams = new URLSearchParams(window.location.search);
const IS_COMPANION = urlParams.get('mode') === 'companion';
if (IS_COMPANION) document.body.classList.add('companion-mode');

function _startHeartbeat(wsRef) {
    _stopHeartbeat();
    _pongPending = false;
    _pingInterval = setInterval(() => {
        if (wsRef && wsRef.readyState === WebSocket.OPEN) {
            wsRef.send(JSON.stringify({ type: 'ping' }));
            _pongPending = true;
            clearTimeout(_pongTimeout);
            _pongTimeout = setTimeout(() => {
                if (_pongPending && wsRef && wsRef.readyState === WebSocket.OPEN) {
                    console.warn('Heartbeat: pong not received, closing stale connection');
                    wsRef.close(3000, 'Heartbeat timeout');
                    _pongPending = false;
                }
            }, 10000);
        }
    }, 30000);
}

function _stopHeartbeat() {
    if (_pingInterval) { clearInterval(_pingInterval); _pingInterval = null; }
    if (_pongTimeout) { clearTimeout(_pongTimeout); _pongTimeout = null; }
    _pongPending = false;
}

function _showReconnecting(attempt, delay) {
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    if (statusDot) statusDot.className = 'status-dot connecting';
    statusText?.setAttribute('aria-label', `Reconnecting attempt ${attempt}`);
    statusText?.setAttribute('data-i18n', 'status.reconnecting');
    statusText.textContent = t('status.reconnecting_countdown', { attempt, seconds: Math.round(delay / 1000) });
    const bar = document.getElementById('offline-bar');
    if (bar && attempt > 2) {
        bar.classList.remove('hidden');
        bar.classList.add('visible');
    }
    if (delay && delay > 0) {
        let remaining = Math.round(delay / 1000);
        if (_reconnectCountdownTimer) clearInterval(_reconnectCountdownTimer);
        _reconnectCountdownTimer = setInterval(() => {
            remaining--;
            if (remaining <= 0) {
                clearInterval(_reconnectCountdownTimer);
                _reconnectCountdownTimer = null;
                statusText?.setAttribute('data-i18n', 'status.reconnecting');
                statusText.textContent = t('status.reconnecting');
            } else {
                statusText?.setAttribute('data-i18n', 'status.reconnecting_countdown');
                statusText.textContent = t('status.reconnecting_countdown', { attempt, seconds: remaining });
            }
        }, 1000);
    }
}

function _clearReconnecting() {
    if (_reconnectCountdownTimer) { clearInterval(_reconnectCountdownTimer); _reconnectCountdownTimer = null; }
}

export function getPendingMessages() { return _pendingMessages; }

export function connectWS() {
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
    _stopHeartbeat();
    const wsInst = new WebSocket(`${WS_BASE}/ws/chat`);
    setWs(wsInst);

    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    let _settingsLoaded = false; // local to connectWS scope

    wsInst.onopen = () => {
        _reconnectAttempts = 0;
        _clearReconnecting();
        if (statusDot) statusDot.className = 'status-dot online';
        if (statusText) statusText.textContent = t('status.connected');

        _startHeartbeat(wsInst);

        if (!_settingsLoaded) {
            import('./api-client.js').then(({ api }) => {
                api(BASE_URL + '/api/settings').then(s => { if (s) { _applySettings?.(s); _settingsLoaded = true; }});
            });
            _loadCharacters?.();
            _fetchCommands?.();
            _loadSession?.('current');
        }

        if (wsInst.readyState === WebSocket.OPEN) {
            wsInst.send(JSON.stringify({
                type: 'client_hello',
                capabilities: {
                    push_notifications: typeof Capacitor !== 'undefined' && !!Capacitor.Plugins?.PushNotifications,
                    native_microphone: typeof Capacitor !== 'undefined' && !!Capacitor.Plugins?.Microphone,
                    platform: typeof Capacitor !== 'undefined' ? 'capacitor' : 'web'
                }
            }));
            if (getVoiceInputEnabled() && isBrowserStt()) {
                // Restart browser STT after reconnect — it doesn't survive WS disconnects
                startBrowserSpeechRec();
                wsInst.send(JSON.stringify({ type: 'command', command: 'voice_input_on' }));
            } else if (!getVoiceInputEnabled() && isBrowserStt()) {
                wsInst.send(JSON.stringify({ type: 'command', command: 'voice_input_off' }));
            } else {
                wsInst.send(JSON.stringify({ type: 'command', command: getVoiceInputEnabled() ? 'voice_input_on' : 'voice_input_off' }));
            }
            wsInst.send(JSON.stringify({ type: 'command', command: getVoiceOutputEnabled() ? 'voice_output_on' : 'voice_output_off' }));
        }

        while (_pendingMessages.length > 0) {
            const msg = _pendingMessages.shift();
            if (wsInst.readyState === WebSocket.OPEN) wsInst.send(msg);
        }
    };

    wsInst.onclose = (event) => {
        _stopHeartbeat();

        // Reset voice state on disconnect — flush TTS, stop browser STT
        flushTTSQueue();
        if (getVoiceInputEnabled() && isBrowserStt()) {
            stopBrowserSpeechRec();
        }
        updateVoiceState('idle');

        if (event.code === 1000 || event.code === 1001) {
            _clearReconnecting();
            if (statusDot) statusDot.className = 'status-dot connecting';
            if (statusText) statusText.textContent = t('status.reconnecting');
            _reconnectAttempts = 0;
            _reconnectTimer = setTimeout(connectWS, 200);
            return;
        }
        if (_reconnectAttempts >= _reconnectDelays.length) {
            _showReconnecting(_reconnectDelays.length, 5000);
            _reconnectTimer = setTimeout(connectWS, 5000);
            if (_reconnectAttempts >= _reconnectDelays.length + 30) {
                if (statusDot) statusDot.className = 'status-dot offline';
                if (statusText) statusText.textContent = t('status.disconnected');
                return;
            }
            _reconnectAttempts++;
            return;
        }
        const delay = _reconnectDelays[_reconnectAttempts];
        _showReconnecting(_reconnectAttempts + 1, delay);
        _reconnectAttempts++;
        _reconnectTimer = setTimeout(connectWS, delay);
    };

    wsInst.onerror = () => { console.warn('WebSocket error'); };

    wsInst.onmessage = e => {
        try {
            const data = JSON.parse(e.data);
            if (data.type === 'pong') {
                _pongPending = false;
                if (_pongTimeout) { clearTimeout(_pongTimeout); _pongTimeout = null; }
                return;
            }
            if (data.type === 'error') {
                const severity = data.recoverable ? 'recoverable' : 'critical';
                showToast(data.message || 'Unknown error', severity, {
                    service: data.service,
                    suggestion: data.suggestion,
                });
                return;
            }
            handleWSMessage(data);
        } catch (err) {
            console.warn('WebSocket message parse error:', err);
        }
    };
}

// ws.js already imports all state accessors above

export function handleWSMessage(data) {
    const wsInst = getWs();
    const chatMessages = document.getElementById('chat-messages');
    const avatarRenderer = getAvatarRenderer();
    const avatarPreviewRenderer = getAvatarPreviewRenderer();
    if (data.type === 'user_message_from_voice') {
        _addMessage?.('user', data.text);
        if (wsInst && wsInst.readyState === WebSocket.OPEN) {
            wsInst.send(JSON.stringify({ type: 'user_message', text: data.text }));
        }
    } else if (data.type === 'visibility') {
        const visible = data.visible;
        if (IS_TAURI && window.__TAURI__) {
            const { getCurrentWindow } = window.__TAURI__.window;
            const win = getCurrentWindow();
            if (visible) win.show(); else win.hide();
        } else {
            const avatarView = document.getElementById('vrm-view');
            if (avatarView) avatarView.style.display = visible ? 'block' : 'none';
        }
    } else if (data.type === 'chat_start') {
        flushTTSQueue();
        setCurrentAssistantMessage(_addMessage?.('assistant', ''));
        _setStatus?.('thinking');
    } else if (data.type === 'chat_append') {
        if (data.role === 'assistant') {
            let cam = getCurrentAssistantMessage();
            if (!cam) {
                cam = _addMessage?.('assistant', '');
                setCurrentAssistantMessage(cam);
            }
            if (data.error) cam?.classList.add('msg-error');
            const body = cam?.querySelector('.msg-body');
            let cleanText = stripMarkers(data.text);
            // Stream buffer: batch DOM updates via requestAnimationFrame
            const existing = streamBuffer.get(body) || '';
            streamBuffer.set(body, existing + cleanText);
            if (!getStreamBufferTimer()) {
                setStreamBufferTimer(requestAnimationFrame(_flushStreamBuffer));
            }


            if (data.finished && cam?.classList.contains('msg-error')) {
                _flushStreamBuffer();
                setCurrentAssistantMessage(null);
                setLastUserMessage(null);
                _setStatus?.('ready');
                showToast('Message failed. You can click edit to retry.', 'danger');
                return;
            }
            if (data.finished) {
                _flushStreamBuffer();
                setCurrentAssistantMessage(null);
                setLastUserMessage(null);
                if (!getIsPlayingTTS()) {
                    _setStatus?.('ready');
                    if (avatarRenderer?._idleManager) avatarRenderer._idleManager.deactivate();
                }
            }
        } else if (data.role === 'system') {
            if (data.session_id && data.session_id !== getCurrentSessionId()) {
                setCurrentSessionId(data.session_id);
                location.hash = 'chat/' + data.session_id;
                _loadSession?.(data.session_id);
                return;
            }
            _addMessage?.('system', data.text);
        }
        if (chatMessages) chatMessages.scrollTop = chatMessages.scrollHeight;
    } else if (data.type === 'voice_state') {
        updateVoiceState(data.state);
    } else if (data.type === 'tts_audio') {
        const q = getTtsQueue();
        q.push({ audio: data.audio, duration: data.duration, idx: data.sentence_idx || 0, visemeSchedule: data.viseme_schedule || null });
        processTTSQueue();
    } else if (data.type === 'tts_error') {
        console.warn('TTS error:', data.message);
        showToast(data.message || 'TTS failed', 'danger');
        // Continue processing any remaining valid TTS items in the queue
        processTTSQueue();
    } else if (data.type === 'tts_interrupt') {
        flushTTSQueue();
    } else if (data.type === 'emotion') {
        const emotion = (data.emotion || 'neutral').toLowerCase();
        if (avatarRenderer) avatarRenderer.setEmotion(emotion);
        if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion(emotion);
    } else if (data.type === 'expression') {
        const expr = (data.expression || 'neutral').toLowerCase();
        if (avatarRenderer) avatarRenderer.setExpression(expr);
        if (avatarPreviewRenderer) avatarPreviewRenderer.setExpression(expr);
    } else if (data.type === 'idle_prompt') {
        if (data.text) {
            if (avatarRenderer) avatarRenderer.setEmotion('relaxed');
            if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion('relaxed');
            setTimeout(() => {
                if (avatarRenderer) avatarRenderer.setEmotion('neutral');
                if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion('neutral');
            }, 6000);
        }
    } else if (data.type === 'animation') {
        if (data.url && avatarRenderer) avatarRenderer.playAnimation(data.url);
    } else if (data.type === 'roleplay') {
        if (data.animation_url && avatarRenderer) avatarRenderer.playAnimation(data.animation_url);
    } else if (data.type === 'typing') {
        _setStatus?.('typing');
    } else if (data.type === 'stop_typing') {
        if (document.querySelector('#chat-avatar-status')?.textContent === 'Typing...') _setStatus?.('ready');
    } else if (data.type === 'tool_call') {
        _addMessage?.('tool', data.text || '');
    } else if (data.type === 'permission_request') {
        const overlay = document.getElementById('shell-permission-overlay');
        const cmdDisplay = document.getElementById('shell-pending-cmd');
        if (overlay && cmdDisplay) { cmdDisplay.textContent = data.command || ''; overlay.style.display = 'flex'; }
    } else if (data.type === 'thinking') {
        const thinkingEnabled = document.getElementById('thinking-toggle')?.checked ?? true;
        if (thinkingEnabled && data.text) {
            const cam = getCurrentAssistantMessage();
            const body = cam?.querySelector('.msg-body');
            if (body) {
                const thinkEl = document.createElement('div');
                thinkEl.className = 'thinking-bubble';
                thinkEl.textContent = data.text;
                body.appendChild(thinkEl);
            }
        }
    } else if (data.type === 'swarm_update') {
        if (typeof window.handleSwarmUpdate === 'function') window.handleSwarmUpdate(data.data);
    } else if (data.type === 'avatar_life_event') {
        if (data.event === 'bored' && avatarRenderer) avatarRenderer.setEmotion('bored');
    } else if (data.type === 'interrupt') {
        if (data.action === 'stop_audio_and_animation') {
            flushTTSQueue();
            if (avatarRenderer) avatarRenderer.setEmotion('surprised');
        }
    } else if (data.type === 'service_status') {
        if (data.services) updateHealthBar(data.services);
    } else if (data.type === 'tool_call_update') {
        if (data.tool_call_id) updateToolCall(data.tool_call_id, data.status, data.result);
    } else if (data.type === 'theme_change') {
        if (data.theme) applyTheme(data.theme);
    } else if (data.type === 'settings_change') {
        if (data.settings) setSettingsCache(data.settings);
    } else if (data.type === 'companion') {
        // Companion proactive message from scheduler
        const companionEnabled = getSettings()?.companion?.enabled ?? false;
        if (companionEnabled && data.content) {
            const cam = _addMessage?.('companion', data.content);
            if (cam && chatMessages) chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }
}

function _flushStreamBuffer() {
    setStreamBufferTimer(null);
    try {
        if (streamBuffer.size === 0) return;
        for (const [el, newText] of streamBuffer) {
            const accumulated = (el.dataset.rawText || '') + newText;
            el.dataset.rawText = accumulated;
            el.innerHTML = formatMessage(accumulated);
            el.querySelectorAll('pre code').forEach(codeBlock => {
                if (!codeBlock.parentElement.querySelector('.copy-code-btn')) {
                    const btn = document.createElement('button');
                    btn.className = 'copy-code-btn';
                    btn.setAttribute('aria-label', 'Copy code');
                    btn.onclick = function() {
                        const t = this;
                        const c = t.previousElementSibling;
                        navigator.clipboard.writeText(c.textContent || c.innerText).then(() => {
                            t.classList.add('copied');
                            t.textContent = 'Copied';
                            setTimeout(() => { t.classList.remove('copied'); t.textContent = ''; }, 2000);
                        });
                    };
                    codeBlock.parentElement.appendChild(btn);
                }
            });
        }
        for (const [el] of streamBuffer) {
            if (!el.isConnected) streamBuffer.delete(el);
        }
        streamBuffer.clear();
    } catch (err) {
        console.error('Stream buffer flush error:', err);
        streamBuffer.clear();
    }
}

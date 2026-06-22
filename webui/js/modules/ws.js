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
    getIsPlayingTTS, setIsPlayingTTS,
    getTtsQueue, setTtsQueue,
    getTtsQueuePlaying, setTtsQueuePlaying,
    setServerCapabilities, setServerPlatform,
    setWakeWordEnabled,
    resetVoiceState,
} from './state.js';
import { isBrowserStt, updateVoiceState, stopBrowserSpeechRec, startBrowserSpeechRec, resetBrowserStt } from './voice.js';
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

        // Hide offline bar on successful connection (fixes race where
        // the bar is visible before initial connect or after reconnect).
        const offlineBar = document.getElementById('offline-bar');
        if (offlineBar) { offlineBar.classList.add('hidden'); offlineBar.classList.remove('visible'); }

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

        // Reset voice state on disconnect: flush TTS queue, stop audio, close AudioContext
        flushTTSQueue();

        // Stop browser STT if it was running
        if (getVoiceInputEnabled() && isBrowserStt()) {
            resetBrowserStt();
        }

        // Update UI voice state to idle
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
    } else if (data.type === 'server_hello') {
        // Store server platform/capabilities for feature gating
        setServerCapabilities(data.capabilities);
        setServerPlatform(data.platform);
    } else if (data.type === 'chat_start') {
        // Race condition fix: flush any playing TTS when new message starts
        flushTTSQueue();
        const assistantMsg = _addMessage?.('assistant', '');
        if (assistantMsg) {
            const body = assistantMsg.querySelector('.msg-body');
            if (body) {
                body.innerHTML = '<span class="thinking-dots"><span></span><span></span><span></span></span>';
            }
        }
        setCurrentAssistantMessage(assistantMsg);
        _setStatus?.('thinking');
        if (avatarRenderer) avatarRenderer.playGreeting?.();
        if (avatarPreviewRenderer) avatarPreviewRenderer.playGreeting?.();
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
                setStreamBufferTimer(requestAnimationFrame(() => {
                    streamBuffer.forEach((text, el) => {
                        if (el) el.innerHTML = formatMessage(text);
                    });
                    streamBuffer.clear();
                    setStreamBufferTimer(null);
                    // Auto-scroll only if user is near the bottom (within 150px)
                    if (chatMessages) {
                        const nearBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < 150;
                        if (nearBottom) chatMessages.scrollTop = chatMessages.scrollHeight;
                    }
                }));
            }
            // If this append is marked finished, finalize the assistant message
            if (data.finished) {
                setCurrentAssistantMessage(null);
                _setStatus?.('ready');
                // Flush any remaining stream buffer
                if (getStreamBufferTimer()) {
                    cancelAnimationFrame(getStreamBufferTimer());
                    setStreamBufferTimer(null);
                }
                streamBuffer.forEach((text, el) => {
                    if (el) el.innerHTML = formatMessage(text);
                });
                streamBuffer.clear();
                // Auto-scroll after final flush (always scroll on completion)
                if (chatMessages) chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        }
    } else if (data.type === 'tts_audio') {
        // Add audio to TTS queue
        try {
            const q = getTtsQueue();
            q.push({
                idx: data.sentence_idx ?? q.length,
                audio: data.audio,
                duration: data.duration,
                visemeSchedule: data.viseme_schedule ?? null,
            });
            setTtsQueue(q);
            processTTSQueue();
        } catch (e) {
            console.error('TTS queue error:', e);
        }
    } else if (data.type === 'tts_interrupt') {
        // Backend requests TTS stop (e.g., user barged in)
        flushTTSQueue();
    } else if (data.type === 'tts_error') {
        // Backend TTS synthesis failed — reset TTS state so UI doesn't hang
        console.warn('TTS error from backend:', data.message);
        flushTTSQueue();
        _setStatus?.('ready');
        if (data.message) {
            showToast(`TTS: ${data.message}`, 'warning');
        }
    } else if (data.type === 'voice_state') {
        updateVoiceState(data.state);
    } else if (data.type === 'emotion') {
        if (avatarRenderer) avatarRenderer.setEmotion?.(data.emotion);
        if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion?.(data.emotion);
    } else if (data.type === 'expression') {
        if (avatarRenderer) avatarRenderer.setExpression?.(data.expression);
        if (avatarPreviewRenderer) avatarPreviewRenderer.setExpression?.(data.expression);
    } else if (data.type === 'viseme') {
        // Set mouth openness (0.0 = closed, 1.0 = fully open)
        if (avatarRenderer) avatarRenderer.setMouthOpen(data.value);
        if (avatarPreviewRenderer) avatarPreviewRenderer.setMouthOpen(data.value);
    } else if (data.type === 'thinking') {
        _setStatus?.('thinking');
        if (avatarRenderer) avatarRenderer.playNod?.();
        if (avatarPreviewRenderer) avatarPreviewRenderer.playNod?.();
    } else if (data.type === 'roleplay') {
        // Roleplay text display
        const cam = getCurrentAssistantMessage();
        if (cam) {
            const body = cam.querySelector('.msg-body');
            if (body) {
                const rpDiv = document.createElement('div');
                rpDiv.className = 'roleplay';
                rpDiv.textContent = data.text;
                body.appendChild(rpDiv);
            }
        }
    } else if (data.type === 'tool_call') {
        if (data.tool_id) updateToolCall(data.tool_id, data.status || 'running', data.result);
    } else if (data.type === 'permission_request') {
        showToast(`Permission requested: ${data.command}`, 'info');
    } else if (data.type === 'theme_change') {
        applyTheme(data.theme);
    } else if (data.type === 'session_id') {
        setCurrentSessionId(data.session_id);
    } else if (data.type === 'health_update') {
        updateHealthBar(data.services);
    } else if (data.type === 'wake_word_state') {
        setWakeWordEnabled(data.enabled);
        if (data.error) {
            showToast(data.error, 'danger');
        }
    } else if (data.type === 'animation') {
        // Animation playback
        if (avatarRenderer && data.url) avatarRenderer.playAnimation?.(data.url);
        if (avatarPreviewRenderer && data.url) avatarPreviewRenderer.playAnimation?.(data.url);
    } else if (data.type === 'avatar_life_event') {
        // Server-pushed avatar life state (bored, sleeping, idle)
        if (data.event === 'bored') {
            if (avatarRenderer) avatarRenderer.setEmotion?.('bored');
            if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion?.('bored');
        } else if (data.event === 'sleeping') {
            if (avatarRenderer) avatarRenderer.setEmotion?.('sleep');
            if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion?.('sleep');
        }
        // Dispatch DOM event so other components can react
        document.dispatchEvent(new CustomEvent('avatarLifeState', { detail: { event: data.event } }));
    } else if (data.type === 'companion') {
        // Companion proactive message — display as a special assistant message
        const cam = _addMessage?.('assistant', data.content || '');
        if (cam) {
            cam.classList.add('msg-companion');
            if (data.context) cam.dataset.companionContext = data.context;
        }
        _setStatus?.('ready');
    } else if (data.type === 'interrupt') {
        if (data.action === 'stop_audio_and_animation') {
            flushTTSQueue();
        }
    }
}

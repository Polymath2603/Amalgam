
const IS_TAURI = window.location.protocol === 'tauri:' || window.location.protocol === 'asset:';
const BASE_URL = IS_TAURI ? 'http:
const WS_BASE = IS_TAURI ? 'ws:

import { initCustomSelects, syncAllCustomSelects } from './custom-select.js';
import { t, setLanguage, initI18n, getCurrentLang } from './i18n.js';


let avatarRenderer = null;
let avatarPreviewRenderer = null;
let speechBubble = null;

window.addEventListener('error', e => console.error('GLOBAL_ERROR:', e.message, e.filename, e.lineno));
document.addEventListener('DOMContentLoaded', async () => {
    
    let savedLang = null;
    try {
        const r = await fetch(`${BASE_URL}/api/settings/get/ui.language`);
        if (r.ok) { const d = await r.json(); savedLang = d.value; }
    } catch {}
    await initI18n(savedLang);

    
    const langSelect = document.getElementById('language-select');
    if (langSelect) {
        langSelect.value = getCurrentLang();
        langSelect.addEventListener('change', async () => {
            await setLanguage(langSelect.value);
            fetch(`${BASE_URL}/api/settings/set`, {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({'ui.language': langSelect.value})
            });
        });
    }

    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const statusDot = document.getElementById('status-dot');
    console.log('app:init - elements:', { chatMessages: !!chatMessages, chatInput: !!chatInput, sendBtn: !!sendBtn, statusDot: !!statusDot });
    if (!sendBtn) console.warn('app:init - send-btn not found in DOM');

    
    

    
    const avatarContainer = document.getElementById('avatar-canvas');
    const avatarPreview = document.getElementById('avatar-preview');
    let _avatarModule = null;
    let _vrmPath = BASE_URL + '/characters/default/model.vrm';
    let _mainAvatarCreated = false;

    import('./avatar.js').then(async ({ AvatarRenderer }) => {
        _avatarModule = { AvatarRenderer };
        const settings = await fetch(BASE_URL + '/api/settings').then(r => r.json());
        _vrmPath = settings?.avatar?.model_path
            ? BASE_URL + `/${settings.avatar.model_path}`
            : BASE_URL + '/characters/default/model.vrm';

        
        if (avatarPreview) {
            avatarPreviewRenderer = new AvatarRenderer(avatarPreview, _vrmPath, { preview: true });
        }

        
        const observer = new IntersectionObserver((entries) => {
            if (entries[0].isIntersecting) {
                createMainAvatar();
                observer.disconnect();
            }
        }, { threshold: 0.1 });
        if (avatarContainer) observer.observe(avatarContainer);

    }).catch(err => {
        console.error('Avatar load failed:', err);
    });

    function createMainAvatar() {
        if (_mainAvatarCreated || !_avatarModule || !avatarContainer) return;
        _mainAvatarCreated = true;
        try {
            avatarRenderer = new _avatarModule.AvatarRenderer(avatarContainer, _vrmPath);
            
            import('./speech-bubble.js').then(({ SpeechBubble }) => {
                speechBubble = new SpeechBubble(avatarContainer, avatarRenderer);
            }).catch(err => console.error('SpeechBubble load failed:', err));
            
            initIdleManager();
        } catch(err) {
            console.error('Main avatar creation failed:', err);
            avatarContainer.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#e74c3c;font-size:0.8rem;gap:0.5rem;padding:1rem;text-align:center"><span class="material-icons-round" style="font-size:2rem">error</span><span>Avatar error: ${err.message || err}</span></div>`;
        }
    }

    
    function initIdleManager() {
        if (!avatarRenderer || avatarRenderer._idleManager || !_settingsCache) return;
        const idleCfg = _settingsCache.idle || {};
        avatarRenderer.initIdleManager({
            enabled: idleCfg.enabled !== false,
            timeBeforeIdleSec: idleCfg.time_before_idle_sec || 30,
            timeToSleepSec: idleCfg.time_to_sleep_sec || 120,
            minIntervalSec: idleCfg.min_interval_sec || 8,
            maxIntervalSec: idleCfg.max_interval_sec || 15,
            baseUrl: BASE_URL,
            onRequestIdlePrompt: () => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'idle_prompt_request' }));
                }
            },
            onSleep: () => {
                if (speechBubble) speechBubble.show('zzz...', 0);
            },
            onWake: () => {
                if (speechBubble) speechBubble.hide();
            },
        });
        
        avatarRenderer._idleManager.deactivate();
    }
    const statusText = document.getElementById('status-text');

    let ws = null;
    let currentAssistantMessage = null;
    let lastUserMessage = null;
    let voiceInputEnabled = false;
    let voiceOutputEnabled = false;
    let mcpServersCache = []; 
    let _settingsCache = null; 

    
    let audioContext = null;
    let currentAudioSource = null;
    let isPlayingTTS = false;
    let ttsQueue = [];
    let ttsQueuePlaying = false;
    let ttsFlushRequested = false;
    let _speakingMsgId = null;

    
    let _streamBuffer = new Map();
    let _streamBufferTimer = null;
    function _flushStreamBuffer() {
        _streamBufferTimer = null;
        if (_streamBuffer.size === 0) return;
        for (const [el, text] of _streamBuffer) {
            el.textContent += text;
        }
        _streamBuffer.clear();
    }
    function _appendStreamText(el, text) {
        const existing = _streamBuffer.get(el) || '';
        _streamBuffer.set(el, existing + text);
        if (!_streamBufferTimer) {
            _streamBufferTimer = requestAnimationFrame(_flushStreamBuffer);
        }
    }

    function ensureAudioContext() {
        if (!audioContext) {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (audioContext.state === 'suspended') {
            audioContext.resume();
        }
        return audioContext;
    }

    function processTTSQueue() {
        if (ttsQueuePlaying || ttsQueue.length === 0) return;
        ttsQueuePlaying = true;
        
        ttsQueue.sort((a, b) => a.idx - b.idx);
        const item = ttsQueue.shift();
        playTTSAudio(item.audio, item.duration, item.visemeSchedule, () => {
            if (ttsFlushRequested) {
                ttsFlushRequested = false;
                ttsQueue = [];
                ttsQueuePlaying = false;
                isPlayingTTS = false;
                setStatus('ready');
                
                if (avatarRenderer?._idleManager) avatarRenderer._idleManager.deactivate();
                return;
            }
            ttsQueuePlaying = false;
            
            if (ttsQueue.length > 0) {
                processTTSQueue();
            } else {
                setStatus('ready');
            }
        });
    }

    function flushTTSQueue() {
        ttsFlushRequested = true;
        if (currentAudioSource) {
            try { currentAudioSource.stop(); } catch (_) {}
            currentAudioSource = null;
        }
    }

    
    function switchTab(tabId) {
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        const navItem = document.querySelector(`.nav-item[data-tab="${tabId}"]`);
        const panel = document.getElementById(`tab-${tabId}`);
        if (navItem && panel) {
            navItem.classList.add('active');
            panel.classList.add('active');
            panel.focus({ preventScroll: true });
            localStorage.setItem('activeTab', tabId);
            if (tabId === 'settings') loadMCP();
            
            if (tabId === 'avatar') {
                createMainAvatar();
            }
        }
    }

    
    const _hash = window.location.hash.replace('#', '').split('/');
    switchTab(localStorage.getItem('activeTab') || _hash[0] || 'chat');

    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            switchTab(item.dataset.tab);
            window.location.hash = item.dataset.tab;
        });
    });

    
    let _initComplete = false;
    let _settingsLoaded = false;
    window.addEventListener('hashchange', () => {
        const h = window.location.hash.replace('#', '').split('/');
        
        
        if (!_initComplete) return;
        const currentPanel = document.querySelector('.tab-panel.active');
        const currentTab = currentPanel ? currentPanel.id.replace('tab-', '') : null;
        if (h[0] && h[0] !== currentTab) {
            switchTab(h[0] || 'chat');
        }
    });

    
    const providerSelect = document.getElementById('provider-select');
    function showProviderSection(name) {
        document.querySelectorAll('.provider-section').forEach(s => {
            const isActive = s.dataset.provider === name;
            s.classList.toggle('active', isActive);
            s.style.display = isActive ? '' : 'none';
        });
    }
    providerSelect.addEventListener('change', () => showProviderSection(providerSelect.value));
    showProviderSection(providerSelect.value);

    
    const ttsEngine = document.getElementById('tts-engine');
    const sttEngine = document.getElementById('stt-engine');
    function showTtsSection(name) {
        document.querySelectorAll('.tts-section').forEach(s => {
            const isActive = s.dataset.tts === name;
            s.classList.toggle('active', isActive);
            s.style.display = isActive ? '' : 'none';
        });
    }
    function showSttSection(name) {
        document.querySelectorAll('.stt-section').forEach(s => {
            const isActive = s.dataset.stt === name;
            s.classList.toggle('active', isActive);
            s.style.display = isActive ? '' : 'none';
        });
    }
    ttsEngine.addEventListener('change', () => showTtsSection(ttsEngine.value));
    sttEngine.addEventListener('change', () => showSttSection(sttEngine.value));
    showTtsSection(ttsEngine.value);
    showSttSection(sttEngine.value);

    
    function connectWS() {
        ws = new WebSocket(`${WS_BASE}/ws/chat`);

        ws.onopen = () => {
            statusDot.className = 'status-dot online';
            statusText.textContent = 'Connected';
            
            if (!_settingsLoaded) {
                api(BASE_URL + '/api/settings').then(s => { if (s) { applySettings(s); markSettingsClean(); _settingsLoaded = true; }});
                loadCharacters();
                fetchCommands();
                loadSession('current');
            }
            loadHistory();
            [2000, 4000, 8000].forEach(delay => setTimeout(() => loadHistory(), delay));
            
            if (ws.readyState === WebSocket.OPEN) {
                if (voiceInputEnabled && isBrowserStt()) {
                    ws.send(JSON.stringify({ type: 'command', command: 'voice_input_on' }));
                } else if (!voiceInputEnabled && isBrowserStt()) {
                    ws.send(JSON.stringify({ type: 'command', command: 'voice_input_off' }));
                } else {
                    ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
                }
                ws.send(JSON.stringify({ type: 'command', command: voiceOutputEnabled ? 'voice_output_on' : 'voice_output_off' }));
            }
        };
        ws.onclose = () => {
            statusDot.className = 'status-dot';
            statusText.textContent = 'Disconnected';
            setTimeout(connectWS, 3000);
        };
        ws.onerror = () => {
            console.warn('WebSocket error');
        };
        ws.onmessage = e => {
            try {
                handleWSMessage(JSON.parse(e.data));
            } catch (err) {
                console.warn('WebSocket message parse error:', err);
            }
        };
    }

    

    function handleWSMessage(data) {
        if (data.type === 'user_message_from_voice') {
            
            addMessage('user', data.text);
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'user_message', text: data.text }));
            }
            return;
        } else if (data.type === 'chat_start') {
            flushTTSQueue();
            currentAssistantMessage = addMessage('assistant', '');
            setStatus('thinking');
        } else if (data.type === 'chat_append') {
            if (data.role === 'assistant') {
                if (!currentAssistantMessage) {
                    currentAssistantMessage = addMessage('assistant', '');
                }
                if (data.error) {
                    currentAssistantMessage.classList.add('msg-error');
                }
                const body = currentAssistantMessage.querySelector('.msg-body');
                let cleanText = stripMarkers(data.text);
                _appendStreamText(body, cleanText);
                
                _speechBubbleAccumulator += cleanText;
                
                const pending = _streamBuffer.get(body);
                if (pending) {
                    body.textContent += pending;
                    _streamBuffer.delete(body);
                }
                
                if (data.finished && currentAssistantMessage?.classList.contains('msg-error')) {
                    _flushStreamBuffer();
                    currentAssistantMessage = null;
                    lastUserMessage = null;
                    setStatus('ready');
                    showToast('Message failed. You can click edit to retry.', 'danger');
                    return;
                }
                if (data.finished) {
                    _flushStreamBuffer();
                    
                    if (speechBubble && _speechBubbleAccumulator.trim()) {
                        speechBubble.show(_speechBubbleAccumulator.trim(), 6000);
                    }
                    _speechBubbleAccumulator = '';
                    currentAssistantMessage = null;
                    lastUserMessage = null;
                    if (!isPlayingTTS) {
                        setStatus('ready');
                        
                        if (avatarRenderer?._idleManager) avatarRenderer._idleManager.deactivate();
                    }
                }
            } else if (data.role === 'system') {
                if (data.session_id && data.session_id !== _currentSessionId) {
                    _currentSessionId = data.session_id;
                    location.hash = 'chat/' + data.session_id;
                    loadSession(data.session_id);
                    return;
                }
                addMessage('system', data.text);
            }
            chatMessages.scrollTop = chatMessages.scrollHeight;
        } else if (data.type === 'voice_state') {
            updateVoiceState(data.state);
        } else if (data.type === 'tts_audio') {
            
            ttsQueue.push({ audio: data.audio, duration: data.duration, idx: data.sentence_idx || 0, visemeSchedule: data.viseme_schedule || null });
            processTTSQueue();
        } else if (data.type === 'tts_error') {
            showToast(data.message || 'TTS failed', 'danger');
            setStatus('ready');
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
                if (speechBubble) speechBubble.show(data.text, 6000);
                if (avatarRenderer) avatarRenderer.setEmotion('relaxed');
                if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion('relaxed');
                setTimeout(() => {
                    if (avatarRenderer) avatarRenderer.setEmotion('neutral');
                    if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion('neutral');
                }, 6000);
            }
        } else if (data.type === 'animation') {
            
            if (data.url && avatarRenderer) {
                avatarRenderer.playAnimation(data.url);
            }
        } else if (data.type === 'roleplay') {
            
            if (data.animation_url && avatarRenderer) {
                avatarRenderer.playAnimation(data.animation_url);
            }
        } else if (data.type === 'typing') {
            setStatus('typing');
        } else if (data.type === 'stop_typing') {
            if (document.querySelector('#chat-avatar-status')?.textContent === 'Typing...') setStatus('ready');
        } else if (data.type === 'tool_call') {
            addMessage('tool', data.text || '');
        } else if (data.type === 'permission_request') {
            const overlay = document.getElementById('shell-permission-overlay');
            const cmdDisplay = document.getElementById('shell-pending-cmd');
            if (overlay && cmdDisplay) {
                cmdDisplay.textContent = data.command || '';
                overlay.style.display = 'flex';
            }
        } else if (data.type === 'thinking') {
            const thinkingEnabled = document.getElementById('thinking-toggle')?.checked ?? true;
            if (thinkingEnabled && data.text) {
                const body = currentAssistantMessage?.querySelector('.msg-body');
                if (body) {
                    const thinkEl = document.createElement('div');
                    thinkEl.className = 'thinking-bubble';
                    thinkEl.textContent = data.text;
                    body.appendChild(thinkEl);
                }
            }
        }
    }

    
    
    let _speechBubbleAccumulator = '';

    let _sessionHasMessages = false;
    let _currentSessionId = null;
    function updateSessionButtons() {
        document.getElementById('new-chat-btn').style.display = _sessionHasMessages ? '' : 'none';
        document.getElementById('new-session-btn').style.display = _sessionHasMessages ? '' : 'none';
    }

    
    function stripMarkers(text) {
        
        return (text || '')
            .replace(/\/\*\*[\s\S]*?(?:\*\*\/?|$)/g, '')
            .replace(/\/\*[\s\S]*?(?:\*\/|$)/g, '')
            .replace(/\/\[\[.*?\]\]/g, '')
            .replace(/\/\(\(.*?\)\)/g, '');
    }

    function getMessageHtml(role, text) {
        return `<div class="msg-body">${escHtml(text)}</div>` +
            `<div class="msg-actions">` +
                `<button class="msg-action" data-action="copy" title="Copy">` +
                    `<span class="material-icons-round">content_copy</span>` +
                `</button>` +
                `${role === 'user' ? `
                    <button class="msg-action" data-action="edit" title="Edit">
                        <span class="material-icons-round">edit</span>
                    </button>
                ` : ''}` +
                `${role === 'assistant' ? `
                    <button class="msg-action" data-action="regenerate" title="Regenerate">
                        <span class="material-icons-round">refresh</span>
                    </button>
                    <button class="msg-action" data-action="speak" title="Speak">
                        <span class="material-icons-round">volume_up</span>
                    </button>
                ` : ''}` +
            `</div>`;
    }

    function updateSpeakButtons() {
        document.querySelectorAll('.msg-assistant .msg-action[data-action="speak"], .msg-assistant .msg-action[data-action="stop-speak"]').forEach(btn => {
            const msg = btn.closest('.msg');
            const isSpeaking = msg.dataset.msgId === _speakingMsgId;
            btn.dataset.action = isSpeaking ? 'stop-speak' : 'speak';
            btn.title = isSpeaking ? 'Stop' : 'Speak';
            btn.innerHTML = isSpeaking ? '<span class="material-icons-round">stop</span>' : '<span class="material-icons-round">volume_up</span>';
        });
    }

    function addMessage(role, text) {
        
        const welcome = chatMessages.querySelector('.welcome-message');
        if (welcome) welcome.remove();

        const div = document.createElement('div');
        div.className = `msg msg-${role}`;
        div.dataset.msgId = 'msg-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
        div.innerHTML = getMessageHtml(role, text);
        chatMessages.appendChild(div);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        if (!_sessionHasMessages) {
            _sessionHasMessages = true;
            updateSessionButtons();
            
            setTimeout(loadHistory, 1000);
        }
        return div;
    }

    chatMessages.addEventListener('click', async (e) => {
        const btn = e.target.closest('.msg-action');
        if (!btn) return;
        const action = btn.dataset.action;
        const msg = btn.closest('.msg');
        const body = msg.querySelector('.msg-body')?.textContent || '';

        if (action === 'copy') {
            await navigator.clipboard.writeText(body);
            showToast('Copied to clipboard', 'success');
        } else if (action === 'edit') {
            chatInput.value = body;
            chatInput.dataset.editTarget = msg.dataset.msgId || '';
            chatInput.focus();
        } else if (action === 'regenerate') {
            const userMsg = msg.previousElementSibling;
            if (userMsg?.classList.contains('msg-user')) {
                const text = userMsg.querySelector('.msg-body')?.textContent;
                msg.remove();
                userMsg.remove();
                if (text && ws?.readyState === WebSocket.OPEN) {
                    addMessage('user', text);
                    ws.send(JSON.stringify({ type: 'user_message', text }));
                }
            }
        } else if (action === 'speak' || action === 'stop-speak') {
            if (_speakingMsgId === msg.dataset.msgId && action === 'stop-speak') {
                flushTTSQueue();
                _speakingMsgId = null;
                updateSpeakButtons();
            } else if (ws?.readyState === WebSocket.OPEN) {
                if (isPlayingTTS) flushTTSQueue();
                _speakingMsgId = msg.dataset.msgId;
                updateSpeakButtons();
                ws.send(JSON.stringify({ type: 'command', command: 'speak', text: body }));
            }
        }
    });

    function clearErrors() {
        chatMessages.querySelectorAll('.msg-assistant.msg-error').forEach(el => {
            const prev = el.previousElementSibling;
            if (prev?.classList.contains('msg-user')) prev.remove();
            el.remove();
        });
    }

    let _sending = false;
    function sendMessage() {
        if (_sending) { console.log('sendMessage: already sending, ignored'); return; }
        _sending = true;
        console.log('sendMessage called');
        const text = chatInput.value.trim();
        console.log('Text:', text);
        if (!text) { _sending = false; return; }
        if (!ws) { _sending = false; console.warn('send: ws null'); showToast('Not connected', 'danger'); return; }
        if (ws.readyState === WebSocket.CONNECTING) { _sending = false; console.warn('send: ws connecting'); showToast('Connecting...', 'danger'); return; }
        if (ws.readyState !== WebSocket.OPEN) {
            _sending = false;
            console.warn('send: ws state', ws.readyState);
            showToast('Not connected (reconnecting...)', 'danger');
            return;
        }

        
        if (text.startsWith('/')) {
            const parts = text.split(/\s+/);
            const command = parts[0].substring(1).toLowerCase();
            const args = parts.slice(1).join(' ');
            ws.send(JSON.stringify({ type: 'slash_command', command, args }));
            chatInput.value = '';
            chatInput.style.height = 'auto';
            _sending = false;
            return;
        }

        clearErrors();
        flushTTSQueue();

        
        const editId = chatInput.dataset.editTarget;
        if (editId) {
            const oldMsg = chatMessages.querySelector(`[data-msg-id="${editId}"]`);
            if (oldMsg) {
                const next = oldMsg.nextElementSibling;
                if (next?.classList.contains('msg-assistant')) next.remove();
                oldMsg.remove();
            }
            delete chatInput.dataset.editTarget;
        }

        clearTimeout(_typingTimer);
        setStatus('ready');
        try { 
            console.log('Sending stop_typing command');
            ws.send(JSON.stringify({ type: 'command', command: 'stop_typing' })); 
        } catch (e) { 
            console.warn('send stop_typing:', e); 
        }
        console.log('Adding user message:', text);
        lastUserMessage = addMessage('user', text);
        const msg = { type: 'user_message', text };
        if (_pendingImageData) {
            msg.images = [_pendingImageData];
            _pendingImageData = null;
            if (imgPreview) imgPreview.style.display = 'none';
            if (imgPreviewSrc) imgPreviewSrc.src = '';
            if (imgInput) imgInput.value = '';
        }
        try {
            console.log('Sending user_message:', JSON.stringify(msg));
            ws.send(JSON.stringify(msg));
        } catch (e) {
            console.warn('send user_message:', e); showToast('Send failed', 'danger');
        }
        
        if (avatarRenderer?._idleManager) avatarRenderer._idleManager.wake();
        chatInput.value = '';
        chatInput.style.height = 'auto';
        _sending = false;
    }

    if (sendBtn) {
        sendBtn.addEventListener('click', sendMessage);
    }

    
    let _pendingImageData = null;
    const imgBtn = document.getElementById('img-btn');
    const imgInput = document.getElementById('img-input');
    const imgPreview = document.getElementById('img-preview');
    const imgPreviewSrc = document.getElementById('img-preview-src');
    const imgPreviewRemove = document.getElementById('img-preview-remove');
    if (imgBtn && imgInput) {
        imgBtn.addEventListener('click', () => imgInput.click());
        imgInput.addEventListener('change', (e) => {
            const files = e.target.files;
            console.log('Image input change:', files?.length, 'files');
            const file = files?.[0];
            if (!file) { console.log('No file selected'); return; }
            console.log('Reading file:', file.name, file.size, file.type);
            const reader = new FileReader();
            reader.onload = (ev) => {
                console.log('FileReader loaded, result length:', ev.target?.result?.length);
                _pendingImageData = ev.target?.result;
                if (imgPreviewSrc && imgPreview) {
                    imgPreviewSrc.src = _pendingImageData;
                    imgPreview.style.display = 'flex';
                    console.log('Preview shown');
                }
            };
            reader.onerror = (err) => console.error('FileReader error:', err);
            reader.readAsDataURL(file);
        });
    }
    if (imgPreviewRemove) {
        imgPreviewRemove.addEventListener('click', () => {
            _pendingImageData = null;
            if (imgInput) imgInput.value = '';
            if (imgPreview) imgPreview.style.display = 'none';
            if (imgPreviewSrc) imgPreviewSrc.src = '';
        });
    }

    document.addEventListener('keydown', e => {
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            const tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'BUTTON') return;
            const activeTab = document.querySelector('.tab-panel.active');
            if (!activeTab) return;
            const target = activeTab.id === 'tab-chat' ? chatInput : activeTab.id === 'tab-characters' ? document.getElementById('char-search-input') : null;
            if (target) {
                target.focus();
                requestAnimationFrame(() => target.setSelectionRange(target.value.length, target.value.length));
            }
        }
    });

    
    if (IS_TAURI) {
        document.addEventListener('keydown', e => {
            if (e.ctrlKey && e.key === 'r') {
                e.preventDefault();
                if (e.shiftKey) {
                    
                    window.location.href = window.location.pathname + '?_=' + Date.now();
                } else {
                    window.location.reload();
                }
            }
        });
    }

    let CMD_LIST = [];
    const cmdSuggestions = document.getElementById('cmd-suggestions');
    let _cmdSelectedIndex = -1;

    function updateCmdSuggestions() {
        const val = chatInput.value;
        if (!val.startsWith('/')) { cmdSuggestions.classList.remove('show'); return; }
        const partial = val.substring(1).toLowerCase();
        const matches = CMD_LIST.filter(c => c.name.startsWith(partial));
        if (!matches.length || partial.includes(' ')) { cmdSuggestions.classList.remove('show'); return; }
        cmdSuggestions.innerHTML = matches.map((c, i) =>
            `<div class="cmd-item${i === _cmdSelectedIndex ? ' selected' : ''}" data-index="${i}">
                <span class="cmd-name">/${c.name}</span>
                <span class="cmd-desc">${c.desc}</span>
            </div>`
        ).join('');
        cmdSuggestions.classList.add('show');
        _cmdSelectedIndex = Math.min(_cmdSelectedIndex, matches.length - 1);
    }

    chatInput.addEventListener('keydown', e => {
        if (cmdSuggestions.classList.contains('show')) {
            const items = cmdSuggestions.querySelectorAll('.cmd-item');
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                _cmdSelectedIndex = Math.min(_cmdSelectedIndex + 1, items.length - 1);
                items.forEach((el, i) => el.classList.toggle('selected', i === _cmdSelectedIndex));
                return;
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                _cmdSelectedIndex = Math.max(_cmdSelectedIndex - 1, 0);
                items.forEach((el, i) => el.classList.toggle('selected', i === _cmdSelectedIndex));
                return;
            }
            if (e.key === 'Enter' || e.key === 'Tab') {
                if (_cmdSelectedIndex >= 0 && _cmdSelectedIndex < items.length) {
                    e.preventDefault();
                    const name = items[_cmdSelectedIndex].querySelector('.cmd-name')?.textContent || '';
                    chatInput.value = name + ' ';
                    chatInput.style.height = 'auto';
                    chatInput.style.height = chatInput.scrollHeight + 'px';
                    cmdSuggestions.classList.remove('show');
                    chatInput.focus();
                    return;
                }
            }
            if (e.key === 'Escape') {
                cmdSuggestions.classList.remove('show');
                return;
            }
        }
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    chatInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = this.scrollHeight + 'px';
        _cmdSelectedIndex = 0;
        updateCmdSuggestions();
    });
    chatInput.addEventListener('blur', () => {
        setTimeout(() => cmdSuggestions.classList.remove('show'), 150);
    });
    chatInput.addEventListener('focus', updateCmdSuggestions);
    let _typingTimer;
    chatInput.addEventListener('keydown', () => {
        clearTimeout(_typingTimer);
        setStatus('typing');
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'command', command: 'typing' }));
        _typingTimer = setTimeout(() => {
            setStatus('ready');
            if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'command', command: 'stop_typing' }));
        }, 2000);
    });

    function escHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    
    function setStatus(state) {
        const el = document.getElementById('chat-avatar-status');
        const avatar = document.getElementById('chat-avatar');
        if (!el || !avatar) return;
        avatar.className = 'chat-avatar';
        switch (state) {
            case 'thinking': avatar.classList.add('thinking'); el.textContent = 'Thinking...'; break;
            case 'speaking': avatar.classList.add('speaking'); el.textContent = 'Speaking...'; break;
            case 'listening': avatar.classList.add('listening'); el.textContent = 'Listening...'; break;
            case 'typing': avatar.classList.add('typing'); el.textContent = 'Typing...'; break;
            case 'error': avatar.classList.add('error'); el.textContent = 'Error'; break;
            default: el.textContent = 'Ready';
        }
    }

    function setCharacterAvatar(charName) {
        document.getElementById('chat-avatar-name').textContent = charName;
    }

    
    let browserSpeechRec = null;
    let browserSpeechRestartTimer = null;

    function isBrowserStt() {
        return document.getElementById('stt-engine')?.value === 'browser';
    }

    function startBrowserSpeechRec() {
        if (browserSpeechRec) return;
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            showToast('Speech Recognition not supported in this browser. Try Chrome.', 'danger');
            return;
        }
        browserSpeechRec = new SpeechRecognition();
        browserSpeechRec.continuous = true;
        browserSpeechRec.interimResults = true;
        browserSpeechRec.lang = 'en-US';

        browserSpeechRec.onresult = (event) => {
            let finalText = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                if (event.results[i].isFinal) {
                    finalText += event.results[i][0].transcript;
                }
            }
            if (finalText.trim() && ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'user_message', text: finalText.trim() }));
            }
        };

        browserSpeechRec.onerror = (event) => {
            console.warn('Browser SpeechRecognition error:', event.error);
            if (event.error === 'not-allowed') {
                showToast('Microphone access denied. Check browser permissions.', 'danger');
                stopBrowserSpeechRec();
            } else if (event.error === 'aborted') {
                
            } else if (event.error === 'no-speech') {
                
            } else {
                showToast(`Speech recognition error: ${event.error}`, 'danger');
            }
        };

        browserSpeechRec.onend = () => {
            
            if (voiceInputEnabled && isBrowserStt()) {
                browserSpeechRestartTimer = setTimeout(() => {
                    if (voiceInputEnabled && isBrowserStt()) {
                        try { browserSpeechRec?.start(); } catch (_) {}
                    }
                }, 300);
            }
        };

        try {
            browserSpeechRec.start();
        } catch (e) {
            console.warn('Browser SpeechRecognition start failed:', e);
        }
    }

    function stopBrowserSpeechRec() {
        if (browserSpeechRestartTimer) {
            clearTimeout(browserSpeechRestartTimer);
            browserSpeechRestartTimer = null;
        }
        if (browserSpeechRec) {
            try { browserSpeechRec.stop(); } catch (_) {}
            browserSpeechRec = null;
        }
    }

    
    const voiceInputToggle = document.getElementById('voice-input-toggle');
    const voiceOutputToggle = document.getElementById('voice-output-toggle');
    const voiceInputToggleSettings = document.getElementById('voice-input-toggle-settings');
    const voiceOutputToggleSettings = document.getElementById('voice-output-toggle-settings');

    function toggleVoiceInput() {
        voiceInputEnabled = !voiceInputEnabled;
        voiceInputToggle.querySelector('.material-icons-round').textContent = voiceInputEnabled ? 'mic' : 'mic_off';
        voiceInputToggle.classList.toggle('active', voiceInputEnabled);
        if (voiceInputToggleSettings) {
            voiceInputToggleSettings.checked = voiceInputEnabled;
        }
        if (voiceInputEnabled && isBrowserStt()) {
            startBrowserSpeechRec();
            
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'command', command: 'voice_input_on' }));
            }
        } else {
            if (isBrowserStt()) {
                stopBrowserSpeechRec();
                
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'command', command: 'voice_input_off' }));
                }
            } else {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
                }
            }
        }
        fetch(BASE_URL + '/api/settings/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: 'ui.voice_input', value: voiceInputEnabled })
        });
        showToast(voiceInputEnabled ? 'Voice input on' : 'Voice input off');
    }

    voiceInputToggle.addEventListener('click', toggleVoiceInput);

    voiceOutputToggle.addEventListener('click', () => {
        voiceOutputEnabled = !voiceOutputEnabled;
        voiceOutputToggle.querySelector('.material-icons-round').textContent = voiceOutputEnabled ? 'volume_up' : 'volume_off';
        voiceOutputToggle.classList.toggle('active', voiceOutputEnabled);
        if (voiceOutputToggleSettings) {
            voiceOutputToggleSettings.checked = voiceOutputEnabled;
        }
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'command', command: voiceOutputEnabled ? 'voice_output_on' : 'voice_output_off' }));
        }
        showToast(voiceOutputEnabled ? 'Voice output on' : 'Voice output off');
    });

    if (voiceInputToggleSettings) {
        voiceInputToggleSettings.addEventListener('change', () => {
            voiceInputEnabled = voiceInputToggleSettings.checked;
            voiceInputToggle.querySelector('.material-icons-round').textContent = voiceInputEnabled ? 'mic' : 'mic_off';
            voiceInputToggle.classList.toggle('active', voiceInputEnabled);
            if (voiceInputEnabled && isBrowserStt()) {
                startBrowserSpeechRec();
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'command', command: 'voice_input_on' }));
                }
            } else {
                if (isBrowserStt()) {
                    stopBrowserSpeechRec();
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ type: 'command', command: 'voice_input_off' }));
                    }
                } else {
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
                    }
                }
            }
            showToast(voiceInputEnabled ? 'Voice input on' : 'Voice input off');
        });
    }

    if (voiceOutputToggleSettings) {
        voiceOutputToggleSettings.addEventListener('change', () => {
            voiceOutputEnabled = voiceOutputToggleSettings.checked;
            voiceOutputToggle.querySelector('.material-icons-round').textContent = voiceOutputEnabled ? 'volume_up' : 'volume_off';
            voiceOutputToggle.classList.toggle('active', voiceOutputEnabled);
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'command', command: voiceOutputEnabled ? 'voice_output_on' : 'voice_output_off' }));
            }
            fetch(BASE_URL + '/api/settings/set', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'ui.voice_output', value: voiceOutputEnabled })
            });
            showToast(voiceOutputEnabled ? 'Voice output on' : 'Voice output off');
        });
    }

    function updateVoiceState(state) {
        const bars = document.getElementById('voice-bars');
        bars.className = 'voice-bars';
        if (state === 'recording' || state === 'speaking') {
            bars.classList.add('active');
        }
        if (state === 'recording') setStatus('listening');
        else if (state === 'speaking') setStatus('speaking');
        else setStatus('ready');
    }

    async function playTTSAudio(base64Wav, duration, visemeSchedule, onComplete) {
        try {
            const ctx = ensureAudioContext();

            
            const binaryStr = atob(base64Wav);
            const bytes = new Uint8Array(binaryStr.length);
            for (let i = 0; i < binaryStr.length; i++) {
                bytes[i] = binaryStr.charCodeAt(i);
            }

            const audioBuffer = await ctx.decodeAudioData(bytes.buffer);

            const source = ctx.createBufferSource();
            source.buffer = audioBuffer;

            
            const analyser = ctx.createAnalyser();
            analyser.fftSize = 2048;
            source.connect(analyser);
            source.connect(ctx.destination);
            currentAudioSource = source;
            isPlayingTTS = true;
            updateSpeakButtons();

            
            if (avatarRenderer?._idleManager) avatarRenderer._idleManager.activate();

            setStatus('speaking');

            
            if (avatarRenderer) avatarRenderer.startLipSync(ctx, analyser, visemeSchedule);
            if (avatarPreviewRenderer) avatarPreviewRenderer.startLipSync(ctx, analyser, visemeSchedule);

            source.onended = () => {
                isPlayingTTS = false;
                currentAudioSource = null;
                _speakingMsgId = null;
                updateSpeakButtons();
                if (avatarRenderer) avatarRenderer.stopLipSync();
                if (avatarPreviewRenderer) avatarPreviewRenderer.stopLipSync();
                
                if (avatarRenderer?._idleManager) avatarRenderer._idleManager.deactivate();
                if (onComplete) onComplete();
            };

            source.start(0);
        } catch (err) {
            console.error('TTS playback error:', err);
            isPlayingTTS = false;
            currentAudioSource = null;
            if (avatarRenderer) avatarRenderer.setMouthOpen(0);
            if (onComplete) onComplete();
        }
    }

    
    async function api(url, opts = {}) {
        try {
            const r = await fetch(url, opts);
            return await r.json();
        } catch (e) {
            console.error(`API error (${url}):`, e);
            return null;
        }
    }

    function showToast(msg, type = 'info') {
        const c = document.getElementById('toast-container');
        const t = document.createElement('div');
        t.className = `toast toast-${type}`;
        t.textContent = msg;
        c.appendChild(t);
        setTimeout(() => t.remove(), 3000);
    }

    
    async function fetchCommands() {
        try {
            const data = await api(BASE_URL + '/api/commands');
            CMD_LIST = data?.commands || [];
        } catch { CMD_LIST = []; }
    }

    async function loadSession(sessionId) {
        const chatMessages = document.getElementById('chat-messages');
        chatMessages.innerHTML = '<div class="msg msg-system" style="text-align:center;color:var(--muted);padding:2rem"><span class="material-icons-round" style="font-size:1.5rem;display:block;margin-bottom:0.5rem">hourglass_top</span>Loading conversation...</div>';
        _sessionHasMessages = false;
        updateSessionButtons();
        try {
            const session = await api(BASE_URL + `/api/memory/session/${sessionId}`);
            chatMessages.innerHTML = '';
            function _setHash(sid) {
                const tab = document.querySelector('.tab-panel.active');
                if (!tab || tab.id === 'tab-chat') {
                    location.hash = 'chat/' + sid;
                }
            }
            if (session?.exists === false) {
                const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
                if (res?.session_id) {
                    _currentSessionId = res.session_id;
                    _setHash(res.session_id);
                }
                return;
            }
            if (session?.messages?.length) {
                _sessionHasMessages = true;
                session.messages.forEach((m, i) => {
                    let role = m.role;
                    const content = stripMarkers(m.content);
                    if (role === 'system' && (content.startsWith('Tool result') || content.startsWith('Tool parse error'))) {
                        role = 'tool';
                    }
                    const div = document.createElement('div');
                    div.className = `msg msg-${role}`;
                    div.dataset.msgId = `msg-loaded-${i}`;
                    if (role === 'assistant' && isErrorText(content)) {
                        div.classList.add('msg-error');
                    }
                    div.innerHTML = getMessageHtml(role, content);
                    chatMessages.appendChild(div);
                });
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
            _currentSessionId = session?.session_id || sessionId;
            if (_currentSessionId) _setHash(_currentSessionId);
            updateSessionButtons();
        } catch (e) {
            chatMessages.innerHTML = '';
            const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
            _currentSessionId = res?.session_id || sessionId;
            if (res?.session_id) _setHash(res.session_id);
            updateSessionButtons();
        }
    }

    window.addEventListener('hashchange', () => {
        const parts = location.hash.replace('#', '').split('/');
        if (parts[0] === 'chat' && parts[1] && parts[1] !== _currentSessionId) {
            loadSession(parts[1]);
        }
    });

    async function init() {
        const settings = await api(BASE_URL + '/api/settings');
        if (settings) { await applySettings(settings); markSettingsClean(); _settingsLoaded = true; }
        await loadCharacters();
                await fetchCommands();

        
        const parts = location.hash.replace('#', '').split('/');
        const sessionId = parts[0] === 'chat' && parts[1] ? parts[1] : null;
        await loadSession(sessionId || 'current');
        
        loadHistory();
        
        [2000, 4000, 8000].forEach(delay => setTimeout(() => loadHistory(), delay));
        
        _initComplete = true;
    }

    function applyTheme(theme) {
        if (theme === 'dark') {
            document.documentElement.removeAttribute('data-theme');
        } else {
            document.documentElement.setAttribute('data-theme', theme);
        }
    }

    function applyAccentColor(hex) {
        document.documentElement.style.setProperty('--accent', hex);
        
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        document.documentElement.style.setProperty('--accent-dim', `rgba(${r}, ${g}, ${b}, 0.15)`);
        
        document.querySelectorAll('#color-swatches .swatch').forEach(s => {
            s.classList.toggle('active', s.dataset.color === hex);
        });
        document.getElementById('accent-color-picker').value = hex;
    }

    
    document.querySelectorAll('#color-swatches .swatch').forEach(swatch => {
        swatch.addEventListener('click', () => {
            applyAccentColor(swatch.dataset.color);
        });
    });
    document.getElementById('accent-color-picker').addEventListener('input', e => {
        applyAccentColor(e.target.value);
    });

    async function applySettings(d) {
        _settingsCache = d;

        
        initIdleManager();

        
        const active = d.provider?.active || 'gemini';
        providerSelect.value = active;
        showProviderSection(active);
        document.getElementById('gemini-api-key').value = d.provider?.gemini?.api_key || '';
        document.getElementById('gemini-base-url').value = d.provider?.gemini?.base_url || '';
        document.getElementById('ollama-url').value = d.provider?.ollama?.base_url || '';
        setOpt('gemini-model', d.provider?.gemini?.model);
        setOpt('ollama-model', d.provider?.ollama?.model);
        
        document.getElementById('openrouter-api-key').value = d.provider?.openrouter?.api_key || '';
        setVal('openrouter-base-url', d.provider?.openrouter?.base_url);
        setOpt('openrouter-model', d.provider?.openrouter?.model);
        document.getElementById('zai-api-key').value = d.provider?.zai?.api_key || '';
        setVal('zai-base-url', d.provider?.zai?.base_url);
        setOpt('zai-model', d.provider?.zai?.model);
        document.getElementById('siliconflow-api-key').value = d.provider?.siliconflow?.api_key || '';
        setVal('siliconflow-base-url', d.provider?.siliconflow?.base_url);
        setOpt('siliconflow-model', d.provider?.siliconflow?.model);
        document.getElementById('groq-api-key').value = d.provider?.groq?.api_key || '';
        setVal('groq-base-url', d.provider?.groq?.base_url);
        setOpt('groq-model', d.provider?.groq?.model);
        document.getElementById('chatgpt-api-key').value = d.provider?.chatgpt?.api_key || '';
        setVal('chatgpt-base-url', d.provider?.chatgpt?.base_url);
        setOpt('chatgpt-model', d.provider?.chatgpt?.model);
        document.getElementById('claude-api-key').value = d.provider?.claude?.api_key || '';
        setVal('claude-base-url', d.provider?.claude?.base_url);
        setOpt('claude-model', d.provider?.claude?.model);

        
        document.getElementById('deepseek-api-key').value = d.provider?.deepseek?.api_key || '';
        setVal('deepseek-base-url', d.provider?.deepseek?.base_url);
        setOpt('deepseek-model', d.provider?.deepseek?.model);
        document.getElementById('mistral-api-key').value = d.provider?.mistral?.api_key || '';
        setVal('mistral-base-url', d.provider?.mistral?.base_url);
        setOpt('mistral-model', d.provider?.mistral?.model);
        document.getElementById('together-api-key').value = d.provider?.together?.api_key || '';
        setVal('together-base-url', d.provider?.together?.base_url);
        setOpt('together-model', d.provider?.together?.model);
        document.getElementById('azure-openai-api-key').value = d.provider?.['azure-openai']?.api_key || '';
        setVal('azure-openai-base-url', d.provider?.['azure-openai']?.base_url);
        setOpt('azure-openai-model', d.provider?.['azure-openai']?.model);
        document.getElementById('alibaba-api-key').value = d.provider?.alibaba?.api_key || '';
        setVal('alibaba-base-url', d.provider?.alibaba?.base_url);
        setOpt('alibaba-model', d.provider?.alibaba?.model);
        document.getElementById('huggingface-api-key').value = d.provider?.huggingface?.api_key || '';
        setVal('huggingface-base-url', d.provider?.huggingface?.base_url);
        setOpt('huggingface-model', d.provider?.huggingface?.model);

        
        document.getElementById('aws-access-key').value = d.provider?.aws?.access_key || '';
        document.getElementById('aws-secret-key').value = d.provider?.aws?.secret_key || '';
        document.getElementById('aws-region').value = d.provider?.aws?.region || '';
        setOpt('aws-model', d.provider?.aws?.model);

        
        document.getElementById('gcp-service-account').value = d.provider?.gcp?.service_account_json || '';
        document.getElementById('gcp-project-id').value = d.provider?.gcp?.project_id || '';
        document.getElementById('gcp-region').value = d.provider?.gcp?.region || '';
        setOpt('gcp-model', d.provider?.gcp?.model);

        
        const temp = d.llm?.temperature ?? 0.7;
        const tempSlider = document.getElementById('llm-temperature');
        if (tempSlider) { tempSlider.value = temp; document.getElementById('llm-temperature-val').textContent = temp; }
        const vadEl = document.getElementById('vad-mode');
        if (vadEl) vadEl.value = d.voice?.vad_mode ?? 2;

        
        document.getElementById('custom-system-prompt').value = d.character?.system_prompt || '';

        
        document.getElementById('lipsync-toggle').checked = d.voice?.lipsync_enabled ?? true;
        const engineEl = document.getElementById('tts-engine');
        if (engineEl) { engineEl.value = d.voice?.engine || 'edge-tts'; showTtsSection(engineEl.value); }
        const sttEngineEl = document.getElementById('stt-engine');
        if (sttEngineEl) { const v = d.voice?.stt_engine || 'browser'; sttEngineEl.value = v; showSttSection(v); }

        
        setVal('elevenlabs-api-key', d.voice?.elevenlabs?.api_key);
        setVal('elevenlabs-model', d.voice?.elevenlabs?.model);
        setVal('elevenlabs-voice-id', d.voice?.elevenlabs?.voice_id);
        setVal('openai-tts-api-key', d.voice?.openai_tts?.api_key);
        setVal('openai-tts-model', d.voice?.openai_tts?.model);
        setOpt('openai-tts-voice', d.voice?.openai_tts?.voice);
        setVal('alltalk-url', d.voice?.alltalk?.url);
        setVal('alltalk-voice', d.voice?.alltalk?.voice);
        setVal('alltalk-language', d.voice?.alltalk?.language);
        setVal('alltalk-version', d.voice?.alltalk?.version);
        setVal('alltalk-rvc-voice', d.voice?.alltalk?.rvc_voice);
        setVal('alltalk-rvc-pitch', d.voice?.alltalk?.rvc_pitch);
        setVal('piper-url', d.voice?.piper?.url);
        setVal('coqui-url', d.voice?.coqui_local?.url);
        setVal('coqui-speaker-id', d.voice?.coqui_local?.speaker_id);
        setVal('kokoro-url', d.voice?.kokoro?.url);
        setVal('kokoro-voice', d.voice?.kokoro?.voice);

        
        setVal('openai-whisper-api-key', d.voice?.openai_whisper?.api_key);
        setVal('openai-whisper-model', d.voice?.openai_whisper?.model);
        setVal('groq-whisper-api-key', d.voice?.groq_whisper?.api_key);
        setVal('groq-whisper-model', d.voice?.groq_whisper?.model);
        setVal('groq-whisper-base-url', d.voice?.groq_whisper?.base_url);
        setVal('whispercpp-url', d.voice?.whispercpp?.url);
        setVal('faster-whisper-model', d.voice?.faster_whisper?.model);

        
        voiceInputEnabled = d.ui?.voice_input ?? true;
        voiceOutputEnabled = d.ui?.voice_output ?? true;
        voiceInputToggle.querySelector('.material-icons-round').textContent = voiceInputEnabled ? 'mic' : 'mic_off';
        voiceInputToggle.classList.toggle('active', voiceInputEnabled);
        voiceOutputToggle.querySelector('.material-icons-round').textContent = voiceOutputEnabled ? 'volume_up' : 'volume_off';
        voiceOutputToggle.classList.toggle('active', voiceOutputEnabled);
        if (voiceInputToggleSettings) voiceInputToggleSettings.checked = voiceInputEnabled;
        if (voiceOutputToggleSettings) voiceOutputToggleSettings.checked = voiceOutputEnabled;
        
        if (ws && ws.readyState === WebSocket.OPEN) {
            if (voiceInputEnabled && isBrowserStt()) {
                ws.send(JSON.stringify({ type: 'command', command: 'voice_input_on' }));
            } else if (!voiceInputEnabled && isBrowserStt()) {
                ws.send(JSON.stringify({ type: 'command', command: 'voice_input_off' }));
            } else {
                ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
            }
            ws.send(JSON.stringify({ type: 'command', command: voiceOutputEnabled ? 'voice_output_on' : 'voice_output_off' }));
        }
        
        if (voiceInputEnabled && isBrowserStt()) {
            startBrowserSpeechRec();
        } else if (isBrowserStt()) {
            stopBrowserSpeechRec();
        }

        
        const thinkingEnabled = d.ui?.thinking_enabled ?? true;
        document.getElementById('thinking-toggle').checked = thinkingEnabled;
        document.getElementById('thinking-toggle').onchange = async function() {
            await fetch(BASE_URL + '/api/settings/set', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ key: 'ui.thinking_enabled', value: this.checked })
            });
        };

        
        const theme = d.ui?.theme || 'dark';
        document.getElementById('theme-select').value = theme;
        applyTheme(theme);
        const fsEl = document.getElementById('font-size-range');
        if (fsEl) {
            const fs = d.ui?.font_size || 14;
            fsEl.value = fs;
            document.getElementById('font-size-val').textContent = `${fs}px`;
            document.documentElement.style.setProperty('--font-size', fs + 'px');
        }

        document.getElementById('vault-path').value = d.vault?.path || 'data/vault';

        syncAllCustomSelects();

        
        const charId = d.character?.active || 'amalgam';
        
        const chars = await api(BASE_URL + '/api/characters');
        const charName = chars?.[charId]?.name || (charId.charAt(0).toUpperCase() + charId.slice(1));
        setCharacterAvatar(charName);
    }

    function setVal(id, val) {
        const el = document.getElementById(id);
        if (el && val) el.value = val;
    }

    function setOpt(id, val) {
        const sel = document.getElementById(id);
        if (!sel || !val) return;
        if (!Array.from(sel.options).some(o => o.value === val)) {
            const o = document.createElement('option');
            o.value = val; o.textContent = val;
            sel.appendChild(o);
        }
        sel.value = val;
    }

    
    const charSearchInput = document.getElementById('char-search-input');
    charSearchInput.addEventListener('input', () => {
        const q = charSearchInput.value.toLowerCase();
        document.querySelectorAll('#characters-grid .char-card').forEach(card => {
            const text = card.dataset.search || '';
            card.style.display = text.includes(q) ? '' : 'none';
        });
    });

    async function loadCharacters() {
        const chars = await api(BASE_URL + '/api/characters');
        if (!chars) return;
        const s = await api(BASE_URL + '/api/settings');
        const active = s?.character?.active || 'amalgam';
        const grid = document.getElementById('characters-grid');
        grid.innerHTML = '';

        for (const [id, c] of Object.entries(chars)) {
            const card = document.createElement('div');
            card.className = `char-card ${id === active ? 'active' : ''}`;
            let iconUrl = c.icon_url || './icons/logo.png';
            if (iconUrl.startsWith('/')) iconUrl = BASE_URL + iconUrl;
            const searchText = [id, c.name, c.description, c.personality, c.voice].filter(Boolean).join(' ').toLowerCase();
            card.dataset.search = searchText;
            card.innerHTML = `
                <img src="${iconUrl}" alt="" class="char-avatar" onerror="this.src='./icons/logo.png'">
                <div class="char-info">
                    <h3>${escHtml(c.name || id)}</h3>
                    <p>${escHtml(c.description || '')}</p>
                    <div class="char-tags">
                        ${c.personality ? `<span class="tag">${c.personality}</span>` : ''}
                        ${c.voice ? `<span class="tag tag-voice">${c.voice.split('-').pop().replace('Neural', '')}</span>` : ''}
                    </div>
                </div>
            `;
            const charName = c.name || id;
            card.addEventListener('click', async () => {
                const body = { character: { active: id } };
                if (c.voice) body.voice = { active: c.voice };
                await api(BASE_URL + '/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                grid.querySelectorAll('.char-card').forEach(el => el.classList.remove('active'));
                card.classList.add('active');
                setCharacterAvatar(charName);
        await fetchCommands();
                
                let vrmPath = c.model_url || '/characters/default/model.vrm';
                if (vrmPath.startsWith('/')) vrmPath = BASE_URL + vrmPath;
                if (avatarRenderer) avatarRenderer.loadVRM(vrmPath);
                if (avatarPreviewRenderer) avatarPreviewRenderer.loadVRM(vrmPath);
                _vrmPath = vrmPath;
                
                await api(BASE_URL + '/api/settings/set', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: 'avatar.model_path', value: vrmPath.replace(/^\
                });
                showToast(`Switched to ${c.name || id}`);
            });
            grid.appendChild(card);
        }
    }



    
    async function loadMCP() {
        const servers = await api(BASE_URL + '/api/mcp/servers');
        const tools = await api(BASE_URL + '/api/mcp/tools');
        const list = document.getElementById('mcp-toggle-list');
        const grid = document.getElementById('tools-grid');

        if (servers?.servers) {
            mcpServersCache = servers.servers; 
            list.innerHTML = '';
            servers.servers.forEach(s => {
                const item = document.createElement('div');
                item.className = `mcp-item${s.enabled === false ? ' disabled' : ''}`;
                const icon = s.enabled !== false ? 'check_circle' : 'cancel';
                const iconClass = s.enabled !== false ? 'online' : 'offline';
                const connClass = s.connected ? 'connected' : 'disconnected';
                item.innerHTML = `
                    <div class="mcp-item-info">
                        <span class="material-icons-round mcp-status-icon ${iconClass}">${icon}</span>
                        <div>
                            <strong><span class="conn-dot ${connClass}"></span> ${s.name}</strong>
                            <span class="muted">${(() => { const c = s.command + ' ' + (s.args || []).join(' '); return c.length > 40 ? c.slice(0, 40) + '...' : c; })()}</span>
                        </div>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" class="mcp-enabled" data-name="${s.name}" ${s.enabled !== false ? 'checked' : ''}>
                        <span class="toggle-slider"></span>
                    </label>
                `;
                const checkbox = item.querySelector('.mcp-enabled');
                checkbox.addEventListener('change', () => {
                    const isEnabled = checkbox.checked;
                    const statusIcon = item.querySelector('.mcp-status-icon');
                    statusIcon.textContent = isEnabled ? 'check_circle' : 'cancel';
                    statusIcon.className = `material-icons-round mcp-status-icon ${isEnabled ? 'online' : 'offline'}`;
                    item.classList.toggle('disabled', !isEnabled);
                    const server = mcpServersCache.find(srv => srv.name === s.name);
                    if (server) server.enabled = isEnabled;
                    markSettingsDirty();
                });
                list.appendChild(item);
            });
        }

        if (tools?.tools) {
            
            const enabledServers = new Set(
                (servers?.servers || []).filter(s => s.enabled !== false).map(s => s.name)
            );
            
            const enabledTools = tools.tools.filter(t => {
                
                return true; 
            });

            grid.innerHTML = enabledTools.length === 0
                ? '<p class="muted">No tools connected</p>'
                : '';
            enabledTools.forEach(t => {
                const card = document.createElement('div');
                card.className = 'tool-card';
                const desc = (t.description || '').length > 40 ? (t.description || '').slice(0, 40) + '...' : (t.description || '');
                card.innerHTML = `<strong>${t.name}</strong><p>${desc}</p>`;
                grid.appendChild(card);
            });
        }
    }

    
    let _settingsSnapshot = {};
    let _mcpSnapshot = '';
    function _settingsFields() {
        return Array.from(document.querySelectorAll('#tab-settings input, #tab-settings select, #tab-settings textarea')).filter(el => el.id);
    }
    function captureSettingsSnapshot() {
        _settingsSnapshot = {};
        _settingsFields().forEach(el => {
            _settingsSnapshot[el.id] = el.type === 'checkbox' ? el.checked : el.value;
        });
    }
    function _mcpState() {
        return (mcpServersCache || []).map(s => `${s.name}:${s.enabled !== false}`).join('|');
    }
    function isSettingsDirty() {
        const fieldsDirty = _settingsFields().some(el => {
            const cur = el.type === 'checkbox' ? el.checked : el.value;
            return cur !== _settingsSnapshot[el.id];
        });
        const mcpDirty = _mcpSnapshot !== _mcpState();
        return fieldsDirty || mcpDirty;
    }
    function markSettingsDirty() { document.getElementById('save-all-settings').disabled = !isSettingsDirty(); }
    function markSettingsClean() {
        captureSettingsSnapshot();
        _mcpSnapshot = _mcpState();
        document.getElementById('save-all-settings').disabled = true;
    }
    document.querySelectorAll('#tab-settings input, #tab-settings select, #tab-settings textarea').forEach(el => {
        el.addEventListener('change', markSettingsDirty);
        el.addEventListener('input', markSettingsDirty);
    });

    
    function validateSettings() {
        const errors = [];
        const activeProvider = providerSelect.value;
        const cloudKeys = { gemini: 'gemini-api-key', openrouter: 'openrouter-api-key', zai: 'zai-api-key', siliconflow: 'siliconflow-api-key', groq: 'groq-api-key', chatgpt: 'chatgpt-api-key', claude: 'claude-api-key', deepseek: 'deepseek-api-key', mistral: 'mistral-api-key', together: 'together-api-key', 'azure-openai': 'azure-openai-api-key', alibaba: 'alibaba-api-key', huggingface: 'huggingface-api-key' };
        if (cloudKeys[activeProvider]) {
            const val = document.getElementById(cloudKeys[activeProvider]).value.trim();
            if (!val) errors.push(`${activeProvider} requires an API key`);
        }
        if (activeProvider === 'ollama') {
            if (!document.getElementById('ollama-url').value.trim()) errors.push('Ollama requires a Base URL');
        }
        if (activeProvider === 'llamacpp') {
            if (!document.getElementById('llamacpp-url').value.trim()) errors.push('LlamaCpp requires a Base URL');
        }
        if (activeProvider === 'koboldai') {
            if (!document.getElementById('koboldai-url').value.trim()) errors.push('KoboldAI requires a Base URL');
        }
        if (activeProvider === 'aws') {
            if (!document.getElementById('aws-access-key').value.trim()) errors.push('AWS requires an Access Key');
            if (!document.getElementById('aws-secret-key').value.trim()) errors.push('AWS requires a Secret Key');
        }
        if (activeProvider === 'gcp') {
            if (!document.getElementById('gcp-project-id').value.trim()) errors.push('GCP requires a Project ID');
        }

        const ttsEngine = document.getElementById('tts-engine').value;
        if (ttsEngine === 'elevenlabs' && !document.getElementById('elevenlabs-api-key').value.trim()) errors.push('ElevenLabs requires an API Key');
        if (ttsEngine === 'openai-tts' && !document.getElementById('openai-tts-api-key').value.trim()) errors.push('OpenAI TTS requires an API Key');
        if ((ttsEngine === 'alltalk') && !document.getElementById('alltalk-url').value.trim()) errors.push('AllTalk requires a URL');
        if (ttsEngine === 'piper' && !document.getElementById('piper-url').value.trim()) errors.push('Piper requires a URL');
        if (ttsEngine === 'coqui-local' && !document.getElementById('coqui-url').value.trim()) errors.push('Coqui requires a URL');
        if (ttsEngine === 'kokoro' && !document.getElementById('kokoro-url').value.trim()) errors.push('Kokoro requires a URL');

        const sttEngine = document.getElementById('stt-engine')?.value;
        if (sttEngine === 'openai-whisper' && !document.getElementById('openai-whisper-api-key').value.trim()) errors.push('OpenAI Whisper requires an API Key');
        if (sttEngine === 'groq-whisper' && !document.getElementById('groq-whisper-api-key').value.trim()) errors.push('Groq Whisper requires an API Key');
        if (sttEngine === 'whispercpp' && !document.getElementById('whispercpp-url').value.trim()) errors.push('Whisper.cpp requires a URL');

        return errors;
    }

    
    const SETTINGS_FIELDS = {
        'tts-engine': 'voice.engine',
        'stt-engine': 'voice.stt_engine',
        'lipsync-toggle': 'voice.lipsync_enabled',
        'vad-mode': 'voice.vad_mode',
        'elevenlabs-api-key': 'voice.elevenlabs.api_key',
        'elevenlabs-model': 'voice.elevenlabs.model',
        'elevenlabs-voice-id': 'voice.elevenlabs.voice_id',
        'openai-tts-api-key': 'voice.openai_tts.api_key',
        'openai-tts-model': 'voice.openai_tts.model',
        'openai-tts-voice': 'voice.openai_tts.voice',
        'alltalk-url': 'voice.alltalk.url',
        'alltalk-voice': 'voice.alltalk.voice',
        'alltalk-language': 'voice.alltalk.language',
        'alltalk-version': 'voice.alltalk.version',
        'alltalk-rvc-voice': 'voice.alltalk.rvc_voice',
        'alltalk-rvc-pitch': 'voice.alltalk.rvc_pitch',
        'piper-url': 'voice.piper.url',
        'coqui-url': 'voice.coqui_local.url',
        'coqui-speaker-id': 'voice.coqui_local.speaker_id',
        'kokoro-url': 'voice.kokoro.url',
        'kokoro-voice': 'voice.kokoro.voice',
        'openai-whisper-api-key': 'voice.openai_whisper.api_key',
        'openai-whisper-model': 'voice.openai_whisper.model',
        'groq-whisper-api-key': 'voice.groq_whisper.api_key',
        'groq-whisper-model': 'voice.groq_whisper.model',
        'groq-whisper-base-url': 'voice.groq_whisper.base_url',
        'whispercpp-url': 'voice.whispercpp.url',
        'faster-whisper-model': 'voice.faster_whisper.model',
        'llm-temperature': 'llm.temperature',
        'theme-select': 'ui.theme',
        'font-size-range': 'ui.font_size',
        'vault-path': 'vault.path',
        'custom-system-prompt': 'character.system_prompt',
        'gemini-api-key': 'provider.gemini.api_key',
        'gemini-model': 'provider.gemini.model',
        'gemini-base-url': 'provider.gemini.base_url',
        'ollama-url': 'provider.ollama.base_url',
        'ollama-model': 'provider.ollama.model',
        'openrouter-api-key': 'provider.openrouter.api_key',
        'openrouter-model': 'provider.openrouter.model',
        'openrouter-base-url': 'provider.openrouter.base_url',
        'zai-api-key': 'provider.zai.api_key',
        'zai-model': 'provider.zai.model',
        'zai-base-url': 'provider.zai.base_url',
        'siliconflow-api-key': 'provider.siliconflow.api_key',
        'siliconflow-model': 'provider.siliconflow.model',
        'siliconflow-base-url': 'provider.siliconflow.base_url',
        'groq-api-key': 'provider.groq.api_key',
        'groq-model': 'provider.groq.model',
        'groq-base-url': 'provider.groq.base_url',
        'chatgpt-api-key': 'provider.chatgpt.api_key',
        'chatgpt-model': 'provider.chatgpt.model',
        'chatgpt-base-url': 'provider.chatgpt.base_url',
        'claude-api-key': 'provider.claude.api_key',
        'claude-model': 'provider.claude.model',
        'claude-base-url': 'provider.claude.base_url',
        'llamacpp-url': 'provider.llamacpp.base_url',
        'koboldai-url': 'provider.koboldai.base_url',
        'deepseek-api-key': 'provider.deepseek.api_key',
        'deepseek-model': 'provider.deepseek.model',
        'deepseek-base-url': 'provider.deepseek.base_url',
        'mistral-api-key': 'provider.mistral.api_key',
        'mistral-model': 'provider.mistral.model',
        'mistral-base-url': 'provider.mistral.base_url',
        'together-api-key': 'provider.together.api_key',
        'together-model': 'provider.together.model',
        'together-base-url': 'provider.together.base_url',
        'azure-openai-api-key': 'provider.azure-openai.api_key',
        'azure-openai-model': 'provider.azure-openai.model',
        'azure-openai-base-url': 'provider.azure-openai.base_url',
        'alibaba-api-key': 'provider.alibaba.api_key',
        'alibaba-model': 'provider.alibaba.model',
        'alibaba-base-url': 'provider.alibaba.base_url',
        'huggingface-api-key': 'provider.huggingface.api_key',
        'huggingface-model': 'provider.huggingface.model',
        'huggingface-base-url': 'provider.huggingface.base_url',
        'aws-access-key': 'provider.aws.access_key',
        'aws-secret-key': 'provider.aws.secret_key',
        'aws-region': 'provider.aws.region',
        'aws-model': 'provider.aws.model',
        'gcp-service-account': 'provider.gcp.service_account_json',
        'gcp-project-id': 'provider.gcp.project_id',
        'gcp-region': 'provider.gcp.region',
        'gcp-model': 'provider.gcp.model',
    };

    
    document.getElementById('save-all-settings').addEventListener('click', async () => {
        const errors = validateSettings();
        if (errors.length) {
            errors.forEach(e => showToast(e, 'danger'));
            return;
        }

        
        document.querySelectorAll('.mcp-item').forEach(item => {
            const name = item.querySelector('.mcp-enabled').dataset.name;
            const enabled = item.querySelector('.mcp-enabled').checked;
            const s = mcpServersCache.find(s => s.name === name);
            if (s) s.enabled = enabled;
        });

        const settings = {};
        for (const [fieldId, dotpath] of Object.entries(SETTINGS_FIELDS)) {
            const el = document.getElementById(fieldId);
            if (!el) continue;
            const val = el.type === 'checkbox' ? el.checked : el.value;
            if (val !== '' && val !== undefined && val !== null) {
                settings[dotpath] = val;
            }
        }
        settings['provider.active'] = providerSelect.value;
        settings['ui.voice_input'] = voiceInputEnabled;
        settings['ui.voice_output'] = voiceOutputEnabled;
        settings['mcp.servers'] = mcpServersCache;

        const result = await api(BASE_URL + '/api/settings/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ settings })
        });
        if (result) {
            markSettingsClean();
            showToast('All settings saved', 'success');
        } else {
            showToast('Failed to save settings', 'danger');
        }
    });

    
    document.getElementById('theme-select').addEventListener('change', function () {
        applyTheme(this.value);
    });

    
    const tempSlider = document.getElementById('llm-temperature');
    if (tempSlider) {
        tempSlider.addEventListener('input', function () {
            document.getElementById('llm-temperature-val').textContent = this.value;
        });
    }

    
    async function loadRelationship() {
        const charId = (await api(BASE_URL + '/api/settings'))?.character?.active || 'amalgam';
        const data = await api(BASE_URL + `/api/relationship/${charId}`);
        const container = document.getElementById('relationship-display');
        const label = document.getElementById('rel-stage-label');
        if (!container) return;
        if (!data || data.error) {
            container.innerHTML = '<p class="muted">No relationship data yet.</p>';
            if (label) label.textContent = '';
            return;
        }
        if (label) label.textContent = data.stage || '';
        container.innerHTML = `
            <div class="rel-stat"><span class="rel-stat-label">Stage</span><span>${data.stage || 'stranger'}</span></div>
            <div class="rel-stat"><span class="rel-stat-label">Interactions</span><span>${data.interaction_count || 0}</span></div>
            <div class="rel-stat"><span class="rel-stat-label">Sentiment</span><span>${data.avg_sentiment ?? 0.5}</span></div>
            <div class="rel-stat"><span class="rel-stat-label">Depth</span><span>${data.avg_depth ?? 0}</span></div>
            <div class="rel-stat"><span class="rel-stat-label">User words</span><span>${data.total_words_user || 0}</span></div>
            <div class="rel-stat"><span class="rel-stat-label">Assistant words</span><span>${data.total_words_assistant || 0}</span></div>
        `;
    }

    async function loadSessions() {
        const data = await api(BASE_URL + '/api/memory/sessions');
        const container = document.getElementById('sessions-list');
        const count = document.getElementById('sessions-count');
        if (!container) return;
        const sessions = data?.sessions || [];
        if (count) count.textContent = `(${sessions.length})`;
        if (sessions.length === 0) {
            container.innerHTML = '<p class="muted">No sessions yet.</p>';
            return;
        }
        container.innerHTML = sessions.map(s => `
            <div class="data-session-item">
                <span>${escHtml(s.preview || s.id)}</span>
                <span class="muted">${s.message_count || '?'} msgs</span>
                <span class="data-session-delete" data-id="${s.id}">delete</span>
            </div>
        `).join('');
        container.querySelectorAll('.data-session-delete').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (!confirm('Delete this session?')) return;
                await api(BASE_URL + `/api/memory/session/${btn.dataset.id}`, { method: 'DELETE' });
                loadSessions();
                loadHistory();
                showToast('Session deleted');
            });
        });
    }

    async function loadVaultFiles() {
        const data = await api(BASE_URL + '/api/vault/files');
        const container = document.getElementById('vault-files-list');
        const count = document.getElementById('vault-count');
        if (!container) return;
        const files = data?.files || [];
        if (count) count.textContent = `(${files.length})`;
        if (files.length === 0) {
            container.innerHTML = '<p class="muted">No vault files.</p>';
            return;
        }
        container.innerHTML = files.map(f => `
            <div class="data-session-item" style="cursor:pointer" data-file="${escHtml(f.name)}">
                <span>${escHtml(f.name)}</span>
                <span class="muted">${f.size} bytes</span>
            </div>
        `).join('');
        container.querySelectorAll('[data-file]').forEach(el => {
            el.addEventListener('click', () => loadVaultFileEdit(el.dataset.file));
        });
    }

    let _vaultCurrentFile = '';

    async function loadVaultFileEdit(filename) {
        _vaultCurrentFile = filename;
        const editor = document.getElementById('vault-editor');
        const saveBtn = document.getElementById('vault-save-btn');
        const delBtn = document.getElementById('vault-delete-btn');
        if (!editor) return;
        const data = await api(BASE_URL + `/api/vault/files/${encodeURIComponent(filename)}`);
        editor.value = data?.content || '';
        if (saveBtn) saveBtn.disabled = false;
        if (delBtn) delBtn.disabled = false;
        document.getElementById('vault-filename-input').value = filename;
    }

    
    const vaultNewBtn = document.getElementById('vault-new-btn');
    if (vaultNewBtn) {
        vaultNewBtn.addEventListener('click', () => {
            _vaultCurrentFile = '';
            document.getElementById('vault-editor').value = '';
            document.getElementById('vault-filename-input').value = '';
            document.getElementById('vault-save-btn').disabled = false;
            document.getElementById('vault-delete-btn').disabled = true;
        });
    }

    
    const vaultSaveBtn = document.getElementById('vault-save-btn');
    if (vaultSaveBtn) {
        vaultSaveBtn.addEventListener('click', async () => {
            const nameInput = document.getElementById('vault-filename-input');
            const editor = document.getElementById('vault-editor');
            if (!nameInput || !nameInput.value.trim()) return showToast('Enter a filename', 'danger');
            const filename = nameInput.value.trim();
            if (!filename.endsWith('.md')) return showToast('Filename must end in .md', 'danger');
            const ok = await api(BASE_URL + `/api/vault/files/${encodeURIComponent(filename)}`, {
                method: 'POST',
                body: JSON.stringify({ content: editor?.value || '' })
            });
            _vaultCurrentFile = filename;
            loadVaultFiles();
            showToast('File saved');
        });
    }

    
    const vaultDeleteBtn = document.getElementById('vault-delete-btn');
    if (vaultDeleteBtn) {
        vaultDeleteBtn.addEventListener('click', async () => {
            if (!_vaultCurrentFile || !confirm(`Delete ${_vaultCurrentFile}?`)) return;
            await api(BASE_URL + `/api/vault/files/${encodeURIComponent(_vaultCurrentFile)}`, { method: 'DELETE' });
            _vaultCurrentFile = '';
            document.getElementById('vault-editor').value = '';
            document.getElementById('vault-filename-input').value = '';
            vaultDeleteBtn.disabled = true;
            vaultSaveBtn.disabled = true;
            loadVaultFiles();
            showToast('File deleted');
        });
    }

    async function loadRules() {
        const editor = document.getElementById('rules-editor');
        if (!editor) return;
        try {
            const r = await fetch(BASE_URL + '/api/rules');
            const data = await r.json();
            editor.value = data?.content || '';
        } catch {
            editor.value = 'Failed to load rules.';
        }
    }

    const saveRulesBtn = document.getElementById('save-rules-btn');
    if (saveRulesBtn) {
        saveRulesBtn.addEventListener('click', async () => {
            const editor = document.getElementById('rules-editor');
            if (!editor) return;
            await fetch(BASE_URL + '/api/rules', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: editor.value })
            });
            showToast('Rules saved');
        });
    }

    
    const settingsTab = document.getElementById('tab-settings');
    if (settingsTab) {
        const observer = new MutationObserver(() => {
            if (settingsTab.classList.contains('active')) {
                loadRelationship();
                loadSessions();
                loadVaultFiles();
                loadRules();
                loadHistory(); 
            }
        });
        observer.observe(settingsTab, { attributes: true, attributeFilter: ['class'] });
        
        if (settingsTab.classList.contains('active')) {
            loadRelationship();
            loadSessions();
            loadVaultFiles();
            loadRules();
            loadHistory(); 
        }
    }

    
    const historyPanel = document.getElementById('history-panel');
    const historyList = document.getElementById('history-list');

    document.getElementById('new-chat-btn').addEventListener('click', async () => {
        const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
        if (res?.session_id) location.hash = 'chat/' + res.session_id;
        showToast('New conversation started');
    });

    document.getElementById('history-toggle').addEventListener('click', async () => {
        console.log('History toggle clicked');
        historyPanel.classList.toggle('open');
        console.log('History panel open class:', historyPanel.classList.contains('open'));
        if (historyPanel.classList.contains('open')) {
            console.log('Loading history...');
            await loadHistory();
        }
    });
    document.getElementById('close-history').addEventListener('click', () => {
        historyPanel.classList.remove('open');
    });

    document.getElementById('new-session-btn').addEventListener('click', async () => {
        const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
        if (res?.session_id) location.hash = 'chat/' + res.session_id;
        historyPanel.classList.remove('open');
        showToast('New conversation started');
    });

    document.getElementById('clear-all-history').addEventListener('click', async () => {
        if (!confirm('Clear all conversation history?')) return;
        await api(BASE_URL + '/api/memory/clear', { method: 'POST' });
        const res = await api(BASE_URL + '/api/memory/session/current');
        if (res?.session_id) location.hash = 'chat/' + res.session_id;
        historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No conversations yet</div>';
        updateHistoryToggle();
        showToast('History cleared');
    });

    function updateHistoryToggle() {
        const hasSessions = !!historyList.querySelector('[data-session-id]');
        document.getElementById('history-toggle').style.display = hasSessions ? '' : 'none';
    }

    async function loadHistory() {
        const container = document.getElementById('history-list');
        if (!container) return;
        try {
            const data = await api(BASE_URL + '/api/memory/sessions');
            console.log('loadHistory: API response:', data);
            historyList.innerHTML = '';
            if (!data || !data.sessions || data.sessions.length === 0) {
                historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No conversations yet</div>';
                updateHistoryToggle();
                return;
            }
            console.log('loadHistory: got', data.sessions.length, 'sessions');
            data.sessions.forEach(session => {
                const item = document.createElement('div');
                item.className = 'history-item';
                item.dataset.sessionId = session.id;
                const time = session.last_active ? new Date(session.last_active).toLocaleString([], { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }) : '';
                item.innerHTML = `
                    <div class="history-content">
                        <div class="history-preview">${escHtml(session.preview)}</div>
                        <div class="history-time">${time} · ${session.message_count} messages</div>
                    </div>
                    <button class="history-delete" title="Delete conversation"><span class="material-icons-round" style="font-size:1rem">close</span></button>
                `;
                item.querySelector('.history-content').addEventListener('click', async () => {
                    location.hash = 'chat/' + session.id;
                    historyPanel.classList.remove('open');
                });
                item.querySelector('.history-delete').addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (!confirm('Delete this conversation?')) return;
                    await api(BASE_URL + `/api/memory/session/${session.id}`, { method: 'DELETE' });
                    item.remove();
                    if (location.hash.replace('#', '').split('/')[1] === session.id) {
                        const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
                        if (res?.session_id) location.hash = 'chat/' + res.session_id;
                    }
                    updateHistoryToggle();
                });
                
                historyList.appendChild(item);
            });
            updateHistoryToggle();
        } catch (e) {
            historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted)">Failed to load history</div>';
            updateHistoryToggle();
        }
    }

    
    const historySearchInput = document.getElementById('history-search-input');
    let _historySearchTimer = null;
    let _historySearchAbort = null;

    if (historySearchInput) {
        historySearchInput.addEventListener('input', () => {
            clearTimeout(_historySearchTimer);
            const q = historySearchInput.value.trim();
            if (!q) {
                loadHistory();
                return;
            }
            _historySearchTimer = setTimeout(() => performHistorySearch(q), 300);
        });
    }

    async function performHistorySearch(query) {
        if (_historySearchAbort) _historySearchAbort.abort();
        _historySearchAbort = new AbortController();
        try {
            const res = await fetch(
                `${BASE_URL}/api/memory/search?q=${encodeURIComponent(query)}&scope=all`,
                { signal: _historySearchAbort.signal }
            );
            const data = await res.json();
            renderHistorySearchResults(data.results || []);
        } catch (e) {
            if (e.name !== 'AbortError') console.warn('History search failed:', e);
        }
    }

    function renderHistorySearchResults(results) {
        historyList.innerHTML = '';
        if (results.length === 0) {
            historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No results found</div>';
            return;
        }
        results.forEach(r => {
            const item = document.createElement('div');
            item.className = 'history-search-result';
            const snippet = r.content ? r.content.substring(0, 120) : '';
            item.innerHTML = `
                <div class="result-session">${escHtml(r.session_id || 'unknown')}</div>
                <div class="result-snippet">${escHtml(snippet)}</div>
            `;
            item.addEventListener('click', () => {
                location.hash = 'chat/' + r.session_id;
                historyPanel.classList.remove('open');
            });
            historyList.appendChild(item);
        });
    }

    
    const vaultSearchInput = document.getElementById('vault-search-input');
    const vaultSemanticToggle = document.getElementById('vault-semantic-toggle');
    const vaultSearchResults = document.getElementById('vault-search-results');
    let _vaultSearchTimer = null;

    if (vaultSearchInput) {
        vaultSearchInput.addEventListener('input', () => {
            clearTimeout(_vaultSearchTimer);
            const q = vaultSearchInput.value.trim();
            if (!q) {
                vaultSearchResults.innerHTML = '';
                return;
            }
            _vaultSearchTimer = setTimeout(() => performVaultSearch(q), 300);
        });
    }

    async function performVaultSearch(query) {
        const mode = vaultSemanticToggle?.checked ? 'semantic' : 'keyword';
        try {
            const res = await api(
                `${BASE_URL}/api/vault/search?q=${encodeURIComponent(query)}&mode=${mode}&max_results=8`
            );
            renderVaultSearchResults(res?.results || [], mode);
        } catch (e) {
            console.warn('Vault search failed:', e);
        }
    }

    function renderVaultSearchResults(results, mode) {
        if (!vaultSearchResults) return;
        if (results.length === 0) {
            vaultSearchResults.innerHTML = '<p class="muted" style="font-size:0.8rem">No results found</p>';
            return;
        }
        vaultSearchResults.innerHTML = results.map(r => {
            const snippet = (r.snippet || r.content || '').substring(0, 150);
            const dist = r.distance != null ? ` (${(1 - r.distance).toFixed(2)})` : '';
            return `<div class="vault-search-result" data-filename="${escHtml(r.filename || '')}">
                <div class="result-filename">${escHtml(r.filename || '')}${dist}</div>
                <div class="result-snippet">${escHtml(snippet)}</div>
            </div>`;
        }).join('');

        vaultSearchResults.querySelectorAll('.vault-search-result').forEach(el => {
            el.addEventListener('click', () => {
                const fn = el.dataset.filename;
                if (fn) loadVaultFileEdit(fn);
            });
        });
    }

    
    document.getElementById('fetch-gemini-models').addEventListener('click', async () => {
        const btn = document.getElementById('fetch-gemini-models');
        if (!document.getElementById('gemini-api-key').value.trim()) {
            showToast('Enter API key first', 'danger');
            return;
        }
        btn.disabled = true; btn.textContent = '...';
        const r = await api(BASE_URL + '/api/models/gemini');
        if (r?.models?.length) {
            const sel = document.getElementById('gemini-model');
            sel.innerHTML = '<option value="">Select model...</option>';
            r.models.forEach(m => { const o = document.createElement('option'); o.value = m; o.textContent = m; sel.appendChild(o); });
            showToast(`Found ${r.models.length} models`);
        } else {
            showToast('No models found. Check API key.', 'danger');
        }
        btn.disabled = false; btn.textContent = 'Fetch';
    });

    document.getElementById('fetch-ollama-models').addEventListener('click', async () => {
        const btn = document.getElementById('fetch-ollama-models');
        btn.disabled = true; btn.textContent = '...';
        const r = await api(BASE_URL + '/api/models/ollama');
        if (r?.models?.length) {
            const sel = document.getElementById('ollama-model');
            sel.innerHTML = '<option value="">Select model...</option>';
            r.models.forEach(m => { const o = document.createElement('option'); o.value = m; o.textContent = m; sel.appendChild(o); });
            showToast(`Found ${r.models.length} models`);
        } else {
            showToast('No models found. Is Ollama running?', 'danger');
        }
        btn.disabled = false; btn.textContent = 'Fetch';
    });

    
    ['openrouter', 'zai', 'siliconflow', 'groq', 'chatgpt', 'claude', 'deepseek', 'mistral', 'together', 'azure-openai', 'alibaba', 'huggingface'].forEach(provider => {
        const btn = document.getElementById(`fetch-${provider}-models`);
        if (!btn) return;
        btn.addEventListener('click', async () => {
            const keyInput = document.getElementById(`${provider}-api-key`);
            if (!keyInput?.value.trim()) {
                showToast('Enter API key first', 'danger');
                return;
            }
            btn.disabled = true; btn.textContent = '...';
            const r = await api(BASE_URL + `/api/models/${provider}`);
            if (r?.models?.length) {
                const sel = document.getElementById(`${provider}-model`);
                const current = sel.value;
                sel.innerHTML = '<option value="">Select model...</option>';
                r.models.forEach(m => { const o = document.createElement('option'); o.value = m; o.textContent = m; sel.appendChild(o); });
                if (current && r.models.includes(current)) sel.value = current;
                showToast(`Found ${r.models.length} models`);
            } else {
                showToast('No models found. Check API key.', 'danger');
            }
            btn.disabled = false; btn.textContent = 'Fetch';
        });
    });

    
    document.getElementById('fetch-aws-models')?.addEventListener('click', async () => {
        const btn = document.getElementById('fetch-aws-models');
        if (!document.getElementById('aws-access-key').value.trim()) {
            showToast('Enter AWS Access Key first', 'danger');
            return;
        }
        btn.disabled = true; btn.textContent = '...';
        const r = await api(BASE_URL + '/api/models/aws');
        if (r?.models?.length) {
            const sel = document.getElementById('aws-model');
            const current = sel.value;
            sel.innerHTML = '<option value="">Select model...</option>';
            r.models.forEach(m => { const o = document.createElement('option'); o.value = m; o.textContent = m; sel.appendChild(o); });
            if (current && r.models.includes(current)) sel.value = current;
            showToast(`Found ${r.models.length} models`);
        } else {
            showToast('No models found. Check credentials.', 'danger');
        }
        btn.disabled = false; btn.textContent = 'Fetch';
    });

    
    document.getElementById('fetch-gcp-models')?.addEventListener('click', async () => {
        const btn = document.getElementById('fetch-gcp-models');
        if (!document.getElementById('gcp-project-id').value.trim()) {
            showToast('Enter GCP Project ID first', 'danger');
            return;
        }
        btn.disabled = true; btn.textContent = '...';
        const r = await api(BASE_URL + '/api/models/gcp');
        if (r?.models?.length) {
            const sel = document.getElementById('gcp-model');
            const current = sel.value;
            sel.innerHTML = '<option value="">Select model...</option>';
            r.models.forEach(m => { const o = document.createElement('option'); o.value = m; o.textContent = m; sel.appendChild(o); });
            if (current && r.models.includes(current)) sel.value = current;
            showToast(`Found ${r.models.length} models`);
        } else {
            showToast('No models found. Check credentials.', 'danger');
        }
        btn.disabled = false; btn.textContent = 'Fetch';
    });

    
    document.getElementById('toggle-gemini-key').addEventListener('click', function () {
        const inp = document.getElementById('gemini-api-key');
        const icon = this.querySelector('.material-icons-round');
        inp.type = inp.type === 'password' ? 'text' : 'password';
        icon.textContent = inp.type === 'password' ? 'visibility_off' : 'visibility';
    });
    ['openrouter', 'zai', 'siliconflow', 'groq', 'chatgpt', 'claude', 'deepseek', 'mistral', 'together', 'azure-openai', 'alibaba', 'huggingface'].forEach(p => {
        const btn = document.getElementById(`toggle-${p}-key`);
        if (btn) btn.addEventListener('click', function () {
            const inp = document.getElementById(`${p}-api-key`);
            const icon = this.querySelector('.material-icons-round');
            inp.type = inp.type === 'password' ? 'text' : 'password';
            icon.textContent = inp.type === 'password' ? 'visibility_off' : 'visibility';
        });
    });


    document.getElementById('font-size-range').addEventListener('input', e => {
        document.getElementById('font-size-val').textContent = `${e.target.value}px`;
        document.documentElement.style.setProperty('--font-size', e.target.value + 'px');
    });

    
    function hideShellPermission() {
        const overlay = document.getElementById('shell-permission-overlay');
        if (overlay) overlay.style.display = 'none';
    }

    async function approveShellCommand(mode) {
        const cmdDisplay = document.getElementById('shell-pending-cmd');
        const cmd = cmdDisplay?.textContent || '';
        if (!cmd) return;
        hideShellPermission();
        if (mode === 'decline') {
            showToast('Command declined');
            return;
        }
        await api(BASE_URL + '/api/shell/approve', {
            method: 'POST',
            body: JSON.stringify({ cmd, mode })
        });
        showToast(`Command ${mode === 'once' ? 'allowed once' : mode === 'prefix' ? 'prefix allowed' : 'exact command allowed'}. Re-send your message to retry.`);
    }

    document.getElementById('shell-allow-once')?.addEventListener('click', () => approveShellCommand('once'));
    document.getElementById('shell-allow-prefix')?.addEventListener('click', () => approveShellCommand('prefix'));
    document.getElementById('shell-allow-exact')?.addEventListener('click', () => approveShellCommand('exact'));
    document.getElementById('shell-decline')?.addEventListener('click', () => approveShellCommand('decline'));

    
    initCustomSelects();
    connectWS();
    init().catch(e => {
        console.error('Init failed:', e);
        showToast('Failed to connect to server', 'danger');
        _initComplete = true;
    });
});

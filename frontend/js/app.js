
let avatarRenderer = null;
let avatarPreviewRenderer = null;

document.addEventListener('DOMContentLoaded', () => {
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const statusDot = document.getElementById('status-dot');

    
    let _animationMap = {};

    
    const avatarContainer = document.getElementById('avatar-canvas');
    const avatarPreview = document.getElementById('avatar-preview');
    let _avatarModule = null;
    let _vrmPath = '/user_data/avatars/avatar.vrm';
    let _mainAvatarCreated = false;

    import('/static/js/avatar.js').then(async ({ AvatarRenderer }) => {
        _avatarModule = { AvatarRenderer };
        const settings = await fetch('/api/settings').then(r => r.json());
        _vrmPath = settings?.avatar?.model_path
            ? `/${settings.avatar.model_path}`
            : '/characters/default/model.vrm';

        
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
        } catch(err) {
            console.error('Main avatar creation failed:', err);
            avatarContainer.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#e74c3c;font-size:0.8rem;gap:0.5rem;padding:1rem;text-align:center"><span class="material-icons-round" style="font-size:2rem">error</span><span>Avatar error: ${err.message || err}</span></div>`;
        }
    }
    const statusText = document.getElementById('status-text');

    let ws = null;
    let currentAssistantMessage = null;
    let lastUserMessage = null;
    let voiceInputEnabled = false;
    let voiceOutputEnabled = false;
    let mcpServersCache = []; 

    
    let audioContext = null;
    let currentAudioSource = null;
    let isPlayingTTS = false;
    let ttsQueue = [];
    let ttsQueuePlaying = false;
    let ttsFlushRequested = false;

    
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
        playTTSAudio(item.audio, item.duration, () => {
            if (ttsFlushRequested) {
                ttsFlushRequested = false;
                ttsQueue = [];
                ttsQueuePlaying = false;
                isPlayingTTS = false;
                setStatus('ready');
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
            if (tabId === 'settings') loadMCP();
            
            if (tabId === 'avatar') {
                createMainAvatar();
            }
        }
    }

    
    const _hash = window.location.hash.replace('#', '').split('/');
    switchTab(_hash[0] || 'chat');

    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            switchTab(item.dataset.tab);
            window.location.hash = item.dataset.tab;
        });
    });

    
    window.addEventListener('hashchange', () => {
        const h = window.location.hash.replace('#', '').split('/');
        switchTab(h[0] || 'chat');
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
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${proto}

        ws.onopen = () => {
            statusDot.className = 'status-dot online';
            statusText.textContent = 'Connected';
            
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
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

    function parseErrorMessage(text) {
        const t = text.trim();
        
        try {
            let obj = JSON.parse(t);
            if (Array.isArray(obj)) obj = obj[0];
            if (obj?.error) {
                const e = obj.error;
                const msg = e.message || JSON.stringify(e);
                if (e.code == 429 || e.status === 'RESOURCE_EXHAUSTED') return 'Quota exceeded. ' + msg;
                return msg;
            }
        } catch {}
        
        const m = t.match(/^\[.*?Error[^:]*:\s*([\s\S]*)/i);
        if (m) {
            const inner = m[1].trim();
            try {
                let obj = JSON.parse(inner.replace(/\]$/, ''));
                if (Array.isArray(obj)) obj = obj[0];
                if (obj?.error) {
                    const e = obj.error;
                    const msg = e.message || '';
                    if (e.code == 429 || e.status === 'RESOURCE_EXHAUSTED') return 'Quota exceeded. ' + msg;
                    return msg;
                }
            } catch {}
            
            const msgMatch = inner.match(/"message"\s*:\s*"([^"]*)/);
            if (msgMatch && msgMatch[1].trim()) {
                return msgMatch[1].replace(/[\]\}]+$/, '').trim();
            }
            
            if (/\b429\b/.test(t) || /RESOURCE_EXHAUSTED/i.test(t)) {
                return 'Quota exceeded. You have exceeded your current quota. Please check your plan and billing details.';
            }
            return 'API error. Please try again later.';
        }
        
        const msgMatch = t.match(/"message"\s*:\s*"([^"]*)/);
        if (msgMatch && msgMatch[1].trim()) {
            
            return msgMatch[1].replace(/[\]\}]+$/, '').trim();
        }
        return null;
    }

    function isErrorText(text) {
        return /^(Quota exceeded|API Error|Error connecting|Error:|\[.*?Error)/i.test(text.trim());
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
                
                let cleanText = (data.text || '')
                    .replace(/\/\[\[(happy|sad|angry|surprised|thinking|relaxed|confused|shy|jealous|bored|suspicious|victory|sleep|love|excited)\]\]/gi, '')
                    .replace(/\/\(\((happy|angry|sad|relaxed|surprised|blink)\)\)/gi, '')
                    .replace(/\/\*\*[\s\S]+?\*\*\/?/g, '');
                
                cleanText = cleanText.replace(/\/\[\[.*?\]\]/g, '');
                cleanText = cleanText.replace(/\/\(\(.*?\)\)/g, '');
                
                cleanText = cleanText.replace(/\/\[\[[^\]\s]*/g, '');
                cleanText = cleanText.replace(/\/\(\([^\)\s]*/g, '');
                
                cleanText = cleanText.replace(/(\/\[\[|\/\(\(|\/\*\*)[^\]\)]*$/g, '');
                _appendStreamText(body, cleanText);
                
                const pending = _streamBuffer.get(body);
                if (pending) {
                    body.textContent += pending;
                    _streamBuffer.delete(body);
                }
                
                if (!currentAssistantMessage.classList.contains('msg-error') && body.textContent.trim()) {
                    const parsed = parseErrorMessage(body.textContent);
                    if (parsed) {
                        body.textContent = parsed;
                        currentAssistantMessage.classList.add('msg-error');
                    } else if (isErrorText(body.textContent)) {
                        currentAssistantMessage.classList.add('msg-error');
                    }
                }
                if (data.finished && currentAssistantMessage?.classList.contains('msg-error')) {
                    _flushStreamBuffer();
                    
                    if (lastUserMessage) {
                        const promptText = lastUserMessage.querySelector('.msg-body')?.textContent || '';
                        chatInput.value = promptText;
                        lastUserMessage.remove();
                    }
                    currentAssistantMessage.remove();
                    currentAssistantMessage = null;
                    lastUserMessage = null;
                    setStatus('ready');
                    return;
                }
                if (data.finished) {
                    _flushStreamBuffer();
                    currentAssistantMessage = null;
                    lastUserMessage = null;
                    if (!isPlayingTTS) {
                        setStatus('ready');
                    }
                }
            } else if (data.role === 'system') {
                addMessage('system', data.text);
            }
            chatMessages.scrollTop = chatMessages.scrollHeight;
        } else if (data.type === 'voice_state') {
            updateVoiceState(data.state);
        } else if (data.type === 'tts_audio') {
            
            ttsQueue.push({ audio: data.audio, duration: data.duration, idx: data.sentence_idx || 0 });
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
        } else if (data.type === 'roleplay') {
            
            const text = data.text || '';
            const words = text.toLowerCase().split(/\s+/);
            let matchedUrl = null;
            for (const word of words) {
                if (_animationMap[word]) { matchedUrl = _animationMap[word]; break; }
            }
            if (!matchedUrl) {
                
                for (const [name, url] of Object.entries(_animationMap)) {
                    if (text.toLowerCase().includes(name)) { matchedUrl = url; break; }
                }
            }
            if (matchedUrl && avatarRenderer) {
                avatarRenderer.playAnimation(matchedUrl);
            }
        } else if (data.type === 'typing') {
            setStatus('typing');
        } else if (data.type === 'stop_typing') {
            if (document.querySelector('#chat-avatar-status')?.textContent === 'Typing...') setStatus('ready');
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

    
    let _sessionHasMessages = false;
    function updateSessionButtons() {
        document.getElementById('new-chat-btn').style.display = _sessionHasMessages ? '' : 'none';
        document.getElementById('new-session-btn').style.display = _sessionHasMessages ? '' : 'none';
    }

    
    function addMessage(role, text) {
        
        const welcome = chatMessages.querySelector('.welcome-message');
        if (welcome) welcome.remove();

        const div = document.createElement('div');
        div.className = `msg msg-${role}`;
        div.dataset.msgId = 'msg-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
        div.innerHTML = `
            <div class="msg-body">${escHtml(text)}</div>
            <div class="msg-actions">
                <button class="msg-action" data-action="copy" title="Copy">
                    <span class="material-icons-round">content_copy</span>
                </button>
                ${role === 'user' ? `
                    <button class="msg-action" data-action="edit" title="Edit">
                        <span class="material-icons-round">edit</span>
                    </button>
                ` : ''}
                ${role === 'assistant' ? `
                    <button class="msg-action" data-action="regenerate" title="Regenerate">
                        <span class="material-icons-round">refresh</span>
                    </button>
                    <button class="msg-action" data-action="speak" title="Speak">
                        <span class="material-icons-round">volume_up</span>
                    </button>
                ` : ''}
            </div>
        `;
        chatMessages.appendChild(div);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        if (!_sessionHasMessages) { _sessionHasMessages = true; updateSessionButtons(); }
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
        } else if (action === 'speak') {
            if (ws?.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'command', command: 'speak', text: body }));
            }
        }
    });

    function clearErrors() {
        chatMessages.querySelectorAll('.msg-assistant.msg-error').forEach(el => el.remove());
    }

    function sendMessage() {
        const text = chatInput.value.trim();
        if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
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
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'command', command: 'stop_typing' }));
        lastUserMessage = addMessage('user', text);
        ws.send(JSON.stringify({ type: 'user_message', text }));
        chatInput.value = '';
        chatInput.style.height = 'auto';
    }

    sendBtn.addEventListener('click', sendMessage);
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
    chatInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    chatInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = this.scrollHeight + 'px';
    });
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

    
    const voiceInputToggle = document.getElementById('voice-input-toggle');
    const voiceOutputToggle = document.getElementById('voice-output-toggle');
    const voiceInputToggleSettings = document.getElementById('voice-input-toggle-settings');
    const voiceOutputToggleSettings = document.getElementById('voice-output-toggle-settings');

    voiceInputToggle.addEventListener('click', () => {
        voiceInputEnabled = !voiceInputEnabled;
        voiceInputToggle.querySelector('.material-icons-round').textContent = voiceInputEnabled ? 'mic' : 'mic_off';
        voiceInputToggle.classList.toggle('active', voiceInputEnabled);
        if (voiceInputToggleSettings) {
            voiceInputToggleSettings.checked = voiceInputEnabled;
        }
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
        }
        fetch('/api/settings/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: 'ui.voice_input', value: voiceInputEnabled })
        });
        showToast(voiceInputEnabled ? 'Voice input on' : 'Voice input off');
    });

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
        fetch('/api/settings/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: 'ui.voice_output', value: voiceOutputEnabled })
        });
        showToast(voiceOutputEnabled ? 'Voice output on' : 'Voice output off');
    });

    if (voiceInputToggleSettings) {
        voiceInputToggleSettings.addEventListener('change', () => {
            voiceInputEnabled = voiceInputToggleSettings.checked;
            voiceInputToggle.querySelector('.material-icons-round').textContent = voiceInputEnabled ? 'mic' : 'mic_off';
            voiceInputToggle.classList.toggle('active', voiceInputEnabled);
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
            }
            fetch('/api/settings/set', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'ui.voice_input', value: voiceInputEnabled })
            });
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
            fetch('/api/settings/set', {
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

    async function playTTSAudio(base64Wav, duration, onComplete) {
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

            setStatus('speaking');

            
            if (avatarRenderer) avatarRenderer.startLipSync(ctx, analyser);
            if (avatarPreviewRenderer) avatarPreviewRenderer.startLipSync(ctx, analyser);

            source.onended = () => {
                isPlayingTTS = false;
                currentAudioSource = null;
                if (avatarRenderer) avatarRenderer.stopLipSync();
                if (avatarPreviewRenderer) avatarPreviewRenderer.stopLipSync();
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

    
    async function fetchAnimationMap() {
        const charId = ((await api('/api/settings'))?.character?.active) || 'amalgam';
        const data = await api(`/api/animations?char_id=${charId}`);
        _animationMap = {};
        const all = [...(data?.default || []), ...(data?.character || [])];
        for (const a of all) {
            _animationMap[a.name.toLowerCase()] = a.url;
        }
    }

    async function init() {
        const settings = await api('/api/settings');
        if (settings) { applySettings(settings); markSettingsClean(); }
        await loadCharacters();
        await fetchAnimationMap();
        
        const chatMessages = document.getElementById('chat-messages');
        chatMessages.innerHTML = '<div class="msg msg-system" style="text-align:center;color:var(--muted);padding:2rem"><span class="material-icons-round" style="font-size:1.5rem;display:block;margin-bottom:0.5rem">hourglass_top</span>Loading conversation...</div>';
        updateSessionButtons();
        try {
            const session = await api('/api/memory/session/current');
            chatMessages.innerHTML = '';
            if (session?.messages?.length) {
                _sessionHasMessages = true;
                session.messages.forEach(m => {
                    const div = document.createElement('div');
                    div.className = `msg msg-${m.role}`;
                    div.innerHTML = `<div class="msg-body">${escHtml(m.content)}</div>`;
                    chatMessages.appendChild(div);
                });
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
            updateSessionButtons();
        } catch (e) {
            console.warn('Failed to load chat session:', e);
            updateSessionButtons();
        }
        
        loadHistory();
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
        
        const active = d.provider?.active || 'gemini';
        providerSelect.value = active;
        showProviderSection(active);
        document.getElementById('gemini-api-key').value = d.provider?.gemini?.api_key || '';
        document.getElementById('gemini-base-url').value = d.provider?.gemini?.base_url || '';
        document.getElementById('ollama-url').value = d.provider?.ollama?.base_url || '';
        setOpt('gemini-model', d.provider?.gemini?.model);
        setOpt('ollama-model', d.provider?.ollama?.model);
        
        document.getElementById('openrouter-api-key').value = d.provider?.openrouter?.api_key || '';
        setOpt('openrouter-model', d.provider?.openrouter?.model);
        document.getElementById('zai-api-key').value = d.provider?.zai?.api_key || '';
        setOpt('zai-model', d.provider?.zai?.model);
        document.getElementById('siliconflow-api-key').value = d.provider?.siliconflow?.api_key || '';
        setOpt('siliconflow-model', d.provider?.siliconflow?.model);
        document.getElementById('groq-api-key').value = d.provider?.groq?.api_key || '';
        setOpt('groq-model', d.provider?.groq?.model);
        document.getElementById('chatgpt-api-key').value = d.provider?.chatgpt?.api_key || '';
        setOpt('chatgpt-model', d.provider?.chatgpt?.model);

        
        document.getElementById('custom-system-prompt').value = d.character?.system_prompt || '';

        
        document.getElementById('lipsync-toggle').checked = d.voice?.lipsync_enabled ?? true;
        const engineEl = document.getElementById('tts-engine');
        if (engineEl) { engineEl.value = d.voice?.engine || 'edge-tts'; showTtsSection(engineEl.value); }
        const sttEngineEl = document.getElementById('stt-engine');
        if (sttEngineEl) { const v = d.provider?.stt?.engine || 'faster-whisper'; sttEngineEl.value = v; showSttSection(v); }

        
        voiceInputEnabled = d.ui?.voice_input ?? true;
        voiceOutputEnabled = d.ui?.voice_output ?? true;
        voiceInputToggle.querySelector('.material-icons-round').textContent = voiceInputEnabled ? 'mic' : 'mic_off';
        voiceInputToggle.classList.toggle('active', voiceInputEnabled);
        voiceOutputToggle.querySelector('.material-icons-round').textContent = voiceOutputEnabled ? 'volume_up' : 'volume_off';
        voiceOutputToggle.classList.toggle('active', voiceOutputEnabled);
        if (voiceInputToggleSettings) voiceInputToggleSettings.checked = voiceInputEnabled;
        if (voiceOutputToggleSettings) voiceOutputToggleSettings.checked = voiceOutputEnabled;
        
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
            ws.send(JSON.stringify({ type: 'command', command: voiceOutputEnabled ? 'voice_output_on' : 'voice_output_off' }));
        }

        
        const thinkingEnabled = d.ui?.thinking_enabled ?? true;
        document.getElementById('thinking-toggle').checked = thinkingEnabled;
        document.getElementById('thinking-toggle').onchange = async function() {
            await fetch('/api/settings/set', {
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

        document.getElementById('vault-path').value = d.vault?.path || 'user_data/vault';

        
        const charId = d.character?.active || 'amalgam';
        
        const chars = await api('/api/characters');
        const charName = chars?.[charId]?.name || (charId.charAt(0).toUpperCase() + charId.slice(1));
        setCharacterAvatar(charName);
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
        const chars = await api('/api/characters');
        if (!chars) return;
        const s = await api('/api/settings');
        const active = s?.character?.active || 'amalgam';
        const grid = document.getElementById('characters-grid');
        grid.innerHTML = '';

        for (const [id, c] of Object.entries(chars)) {
            const card = document.createElement('div');
            card.className = `char-card ${id === active ? 'active' : ''}`;
            const iconUrl = c.icon_url || '/static/icons/logo.png';
            const searchText = [id, c.name, c.description, c.personality, c.voice].filter(Boolean).join(' ').toLowerCase();
            card.dataset.search = searchText;
            card.innerHTML = `
                <img src="${iconUrl}" alt="" class="char-avatar" onerror="this.src='/static/icons/logo.png'">
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
                await api('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                grid.querySelectorAll('.char-card').forEach(el => el.classList.remove('active'));
                card.classList.add('active');
                setCharacterAvatar(charName);
                await fetchAnimationMap();
                
                const vrmPath = c.model_url || '/characters/default/model.vrm';
                if (avatarRenderer) avatarRenderer.loadVRM(vrmPath);
                if (avatarPreviewRenderer) avatarPreviewRenderer.loadVRM(vrmPath);
                _vrmPath = vrmPath;
                
                await api('/api/settings/set', {
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
        const servers = await api('/api/mcp/servers');
        const tools = await api('/api/mcp/tools');
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
                item.innerHTML = `
                    <div class="mcp-item-info">
                        <span class="material-icons-round mcp-status-icon ${iconClass}">${icon}</span>
                        <div>
                            <strong>${s.name}</strong>
                            <span class="muted">${s.command} ${(s.args || []).join(' ')}</span>
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
                const desc = (t.description || '').length > 100 ? (t.description || '').slice(0, 100) + '...' : (t.description || '');
                card.innerHTML = `<strong>${t.name}</strong><p>${desc}</p>`;
                grid.appendChild(card);
            });
        }
    }

    
    let _settingsSnapshot = {};
    function _settingsFields() {
        return Array.from(document.querySelectorAll('#tab-settings input, #tab-settings select, #tab-settings textarea')).filter(el => el.id);
    }
    function captureSettingsSnapshot() {
        _settingsSnapshot = {};
        _settingsFields().forEach(el => {
            _settingsSnapshot[el.id] = el.type === 'checkbox' ? el.checked : el.value;
        });
    }
    function isSettingsDirty() {
        return _settingsFields().some(el => {
            const cur = el.type === 'checkbox' ? el.checked : el.value;
            return cur !== _settingsSnapshot[el.id];
        });
    }
    function markSettingsDirty() { document.getElementById('save-all-settings').disabled = !isSettingsDirty(); }
    function markSettingsClean() { captureSettingsSnapshot(); document.getElementById('save-all-settings').disabled = true; }
    document.querySelectorAll('#tab-settings input, #tab-settings select, #tab-settings textarea').forEach(el => {
        el.addEventListener('change', markSettingsDirty);
        el.addEventListener('input', markSettingsDirty);
    });

    
    function validateSettings() {
        const errors = [];
        const activeProvider = providerSelect.value;
        const cloudKeys = { gemini: 'gemini-api-key', openrouter: 'openrouter-api-key', zai: 'zai-api-key', siliconflow: 'siliconflow-api-key', groq: 'groq-api-key', chatgpt: 'chatgpt-api-key', claude: 'claude-api-key' };
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

        const activeProvider = providerSelect.value;
        const result = await api('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                voice: {
                    engine: document.getElementById('tts-engine').value,
                    lipsync_enabled: document.getElementById('lipsync-toggle').checked,
                    elevenlabs: {
                        api_key: document.getElementById('elevenlabs-api-key').value,
                        model: document.getElementById('elevenlabs-model').value,
                        voice_id: document.getElementById('elevenlabs-voice-id').value
                    },
                    openai_tts: {
                        api_key: document.getElementById('openai-tts-api-key').value,
                        model: document.getElementById('openai-tts-model').value,
                        voice: document.getElementById('openai-tts-voice').value
                    },
                    alltalk: {
                        url: document.getElementById('alltalk-url').value,
                        voice: document.getElementById('alltalk-voice').value,
                        language: document.getElementById('alltalk-language').value
                    },
                    piper: { url: document.getElementById('piper-url').value },
                    coqui_local: {
                        url: document.getElementById('coqui-url').value,
                        speaker_id: document.getElementById('coqui-speaker-id').value
                    },
                    kokoro: {
                        url: document.getElementById('kokoro-url').value,
                        voice: document.getElementById('kokoro-voice').value
                    }
                },
                ui: {
                    theme: document.getElementById('theme-select').value,
                    font_size: parseInt(document.getElementById('font-size-range').value),
                    voice_input: voiceInputEnabled,
                    voice_output: voiceOutputEnabled
                },
                vault: { path: document.getElementById('vault-path').value },
                character: { system_prompt: document.getElementById('custom-system-prompt').value },
                provider: {
                    active: activeProvider,
                    gemini: {
                        api_key: document.getElementById('gemini-api-key').value,
                        model: document.getElementById('gemini-model').value,
                        base_url: document.getElementById('gemini-base-url').value
                    },
                    ollama: {
                        base_url: document.getElementById('ollama-url').value,
                        model: document.getElementById('ollama-model').value
                    },
                    openrouter: {
                        api_key: document.getElementById('openrouter-api-key').value,
                        model: document.getElementById('openrouter-model').value,
                        base_url: 'https:
                    },
                    zai: {
                        api_key: document.getElementById('zai-api-key').value,
                        model: document.getElementById('zai-model').value,
                        base_url: 'https:
                    },
                    siliconflow: {
                        api_key: document.getElementById('siliconflow-api-key').value,
                        model: document.getElementById('siliconflow-model').value,
                        base_url: 'https:
                    },
                    groq: {
                        api_key: document.getElementById('groq-api-key').value,
                        model: document.getElementById('groq-model').value,
                        base_url: 'https:
                    },
                    chatgpt: {
                        api_key: document.getElementById('chatgpt-api-key').value,
                        model: document.getElementById('chatgpt-model').value,
                        base_url: 'https:
                    },
                    claude: {
                        api_key: document.getElementById('claude-api-key').value,
                        model: document.getElementById('claude-model').value,
                        base_url: 'https:
                    },
                    llamacpp: {
                        base_url: document.getElementById('llamacpp-url').value
                    },
                    koboldai: {
                        base_url: document.getElementById('koboldai-url').value
                    },
                    stt: {
                        engine: document.getElementById('stt-engine')?.value || 'faster-whisper',
                        openai_whisper: { api_key: "REDACTED").value },
                        groq_whisper: { api_key: "REDACTED").value },
                        whispercpp: { url: document.getElementById('whispercpp-url').value }
                    }
                },
                mcp: { servers: mcpServersCache }
            })
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

    
    const historyPanel = document.getElementById('history-panel');
    const historyList = document.getElementById('history-list');

    document.getElementById('new-chat-btn').addEventListener('click', async () => {
        await api('/api/memory/new-session', { method: 'POST' });
        document.getElementById('chat-messages').innerHTML = '';
        _sessionHasMessages = false;
        updateSessionButtons();
        showToast('New conversation started');
    });

    document.getElementById('history-toggle').addEventListener('click', async () => {
        historyPanel.classList.toggle('open');
        if (historyPanel.classList.contains('open')) {
            await loadHistory();
        }
    });
    document.getElementById('close-history').addEventListener('click', () => {
        historyPanel.classList.remove('open');
    });

    document.getElementById('new-session-btn').addEventListener('click', async () => {
        await api('/api/memory/new-session', { method: 'POST' });
        document.getElementById('chat-messages').innerHTML = '';
        _sessionHasMessages = false;
        updateSessionButtons();
        historyPanel.classList.remove('open');
        showToast('New conversation started');
    });

    document.getElementById('clear-all-history').addEventListener('click', async () => {
        if (!confirm('Clear all conversation history?')) return;
        await api('/api/memory/clear', { method: 'POST' });
        document.getElementById('chat-messages').innerHTML = '';
        historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No conversations yet</div>';
        updateHistoryToggle();
        showToast('History cleared');
    });

    function updateHistoryToggle() {
        document.getElementById('history-toggle').style.display = historyList.querySelector('[data-session-id]') ? '' : 'none';
    }

    async function loadHistory() {
        try {
            const data = await api('/api/memory/sessions');
            historyList.innerHTML = '';
            if (!data || !data.sessions || data.sessions.length === 0) {
                historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No conversations yet</div>';
                updateHistoryToggle();
                return;
            }
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
                    const msgs = await api(`/api/memory/session/${session.id}`);
                    if (msgs?.messages) {
                        const chatMessages = document.getElementById('chat-messages');
                        chatMessages.innerHTML = '';
                        msgs.messages.forEach(m => {
                            const div = document.createElement('div');
                            div.className = `msg msg-${m.role}`;
                            div.innerHTML = `<div class="msg-body">${escHtml(m.content)}</div>`;
                            chatMessages.appendChild(div);
                        });
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                        _sessionHasMessages = true;
                        updateSessionButtons();
                    }
                    historyPanel.classList.remove('open');
                });
                item.querySelector('.history-delete').addEventListener('click', async (e) => {
                    e.stopPropagation();
                    await api(`/api/memory/session/${session.id}`, { method: 'DELETE' });
                    item.remove();
                    updateHistoryToggle();
                });
            });
            updateHistoryToggle();
        } catch (e) {
            historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted)">Failed to load history</div>';
            updateHistoryToggle();
        }
    }

    
    document.getElementById('fetch-gemini-models').addEventListener('click', async () => {
        const btn = document.getElementById('fetch-gemini-models');
        if (!document.getElementById('gemini-api-key').value.trim()) {
            showToast('Enter API key first', 'danger');
            return;
        }
        btn.disabled = true; btn.textContent = '...';
        const r = await api('/api/models/gemini');
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
        const r = await api('/api/models/ollama');
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

    
    ['openrouter', 'zai', 'siliconflow', 'groq', 'chatgpt'].forEach(provider => {
        const btn = document.getElementById(`fetch-${provider}-models`);
        if (!btn) return;
        btn.addEventListener('click', async () => {
            const keyInput = document.getElementById(`${provider}-api-key`);
            if (!keyInput?.value.trim()) {
                showToast('Enter API key first', 'danger');
                return;
            }
            btn.disabled = true; btn.textContent = '...';
            const r = await api(`/api/models/${provider}`);
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

    
    document.getElementById('toggle-gemini-key').addEventListener('click', function () {
        const inp = document.getElementById('gemini-api-key');
        const icon = this.querySelector('.material-icons-round');
        inp.type = inp.type === 'password' ? 'text' : 'password';
        icon.textContent = inp.type === 'password' ? 'visibility_off' : 'visibility';
    });
    ['openrouter', 'zai', 'siliconflow', 'groq', 'chatgpt'].forEach(p => {
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

    
    connectWS();
    init().catch(e => {
        console.error('Init failed:', e);
        showToast('Failed to connect to server', 'danger');
    });
});

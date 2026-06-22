/**
 * app.js — Main orchestrator (entry point)
 *
 * Wires all modules together and handles DOMContentLoaded bootstrap.
 * Replaces the original 3975-line monolith.
 */
import { IS_TAURI, BASE_URL } from './modules/config.js';
import { showToast, applyTheme, detectGPUCapability, escHtml } from './modules/utils.js';
import { api } from './modules/api-client.js';
import { SETTINGS_SCHEMA } from './modules/settings-schema.js';
import {
    setDomRefs,
    getSettings, setSettingsCache,
    getWs,
    getCurrentAssistantMessage, setCurrentAssistantMessage,
    setLastUserMessage,
    getCurrentSessionId, setCurrentSessionId,
    getSessionHasMessages, setSessionHasMessages,
    getAvatarRenderer, setAvatarRenderer,
    getAvatarPreviewRenderer, setAvatarPreviewRenderer,
    getSpeakingMsgId, setSpeakingMsgId,
    getIsPlayingTTS,
} from './modules/state.js';
import { stripMarkers, _isErrorText, formatMessage, getMessageHtml, renderMarkdown } from './modules/markdown.js';
import { refreshProviderList, refreshCharacterList, refreshCharacterInfo, renderSettings, renderCategory, filterSettings, saveCategory, toggleFieldVisibility, testConnection, fetchModels, _attachSettingsDelegates, setActiveSettingsTab } from './modules/settings.js';
import { processTTSQueue, flushTTSQueue, setTtsCallbacks } from './modules/tts.js';
import { _applyVoiceInput, _applyVoiceOutput, isBrowserStt, initVoiceToggles, updateVoiceState, setVoiceStatusCallback } from './modules/voice.js';
import { connectWS, getPendingMessages } from './modules/ws.js';
import { loadMCP } from './modules/mcp.js';
import { initCompanion, updateCompanionSettings } from './modules/companion.js';
import { initMemoryGraph, destroyMemoryGraph } from './modules/memory-graph.js';
import { initMcpCommand, openMcpPanel, isMcpPanelOpen, handleMcpKeydown } from './modules/mcp-command.js';
import { updateHealthBar, refreshHealth } from './modules/health.js';
import { loadHistory, initHistoryEvents, setHistoryDeps, updateHistoryToggle } from './modules/history.js';
import { showSetupWizard, _initSetupWizard } from './modules/setup-wizard.js';
import { t, setLanguage, initI18n, getCurrentLang } from './i18n.js';
import { initCustomSelects, syncAllCustomSelects } from './custom-select.js';
import { loadMetrics, initMetricsAutoRefresh } from './metrics.js';

// ─── Global error handler ───
window.addEventListener('error', e => console.error('GLOBAL_ERROR:', e.message, e.filename, e.lineno));

// ─── Ctrl+Q/D for Tauri ───
document.addEventListener('keydown', e => {
    if ((e.ctrlKey && (e.key === 'q' || e.key === 'd'))) {
        e.preventDefault();
        if (window.__TAURI__) { window.__TAURI__.core.invoke('exit_app'); }
    }
});

// ─── GPU detection ───
const gpuInfo = detectGPUCapability();
window._gpuTier = gpuInfo.tier;
console.log(`GPU tier: ${gpuInfo.tier} (${gpuInfo.reason})`);

// ─── Reduced motion ───
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
if (prefersReducedMotion.matches) document.body.classList.add('reduced-motion');
prefersReducedMotion.addEventListener('change', (e) => document.body.classList.toggle('reduced-motion', e.matches));

// ─── CSS animation for spin ───
const _styleSheet = document.createElement('style');
_styleSheet.textContent = `
    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    .test-conn-btn .material-icons-round { font-size: 18px; }
`;
document.head.appendChild(_styleSheet);

    // ─── DOMContentLoaded ───
document.addEventListener('DOMContentLoaded', async () => {
    // Init i18n
    let savedLang = null;
    try {
        const r = await fetch(`${BASE_URL}/api/settings/get/ui.language`);
        if (r.ok) { const d = await r.json(); savedLang = d.value; }
    } catch {}
    await initI18n(savedLang);

    // Check setup wizard
    try {
        const setupResp = await fetch(`${BASE_URL}/api/setup/status`);
        if (setupResp.ok) {
            const setupStatus = await setupResp.json();
            if (setupStatus.needs_setup) showSetupWizard();
        }
    } catch (e) { console.warn('Setup status check failed:', e); }

    initMcpCommand();
    initMetricsAutoRefresh();

    // ─── Grab DOM refs ───
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    if (!chatMessages || !chatInput || !statusDot) console.warn('app:init - missing required DOM elements');
    setDomRefs({ chatMessages, chatInput, statusDot, statusText });

    // ─── Wire up callbacks that break circular deps ───
    setTtsCallbacks({ setStatus, updateSpeakButtons });
    setVoiceStatusCallback(setStatus);

    // ─── Avatar initialization ───
    const avatarContainer = document.getElementById('avatar-canvas');
    const avatarPreview = document.getElementById('avatar-preview');
    let _avatarModule = null;
    let _vrmPath = BASE_URL + '/characters/default/model.vrm';

    import('./avatar.js').then(async (mod) => {
        const AvatarRenderer = mod.AvatarRenderer;
        const SpriteAvatar = mod.SpriteAvatar;
        const useSprite = window._gpuTier === 'low';
        _avatarModule = { AvatarRenderer, SpriteAvatar, useSprite };
        const settings = await fetch(BASE_URL + '/api/settings').then(r => r.json());
        _vrmPath = settings?.avatar?.model_path
            ? BASE_URL + `/${settings.avatar.model_path}`
            : BASE_URL + '/characters/default/model.vrm';

        if (avatarPreview) {
            setAvatarPreviewRenderer(new AvatarRenderer(avatarPreview, _vrmPath, { preview: true }));
        }

        const observer = new IntersectionObserver((entries) => {
            if (entries[0].isIntersecting) {
                createMainAvatar();
                observer.disconnect();
            }
        }, { threshold: 0.1 });
        if (avatarContainer) observer.observe(avatarContainer);
    }).catch(err => console.error('Avatar load failed:', err));

    function createMainAvatar() {
        if (getAvatarRenderer() || !_avatarModule || !avatarContainer) return;
        try {
            let renderer;
            if (_avatarModule.useSprite) {
                renderer = new _avatarModule.SpriteAvatar(avatarContainer);
            } else {
                renderer = new _avatarModule.AvatarRenderer(avatarContainer, _vrmPath);
            }
            setAvatarRenderer(renderer);

            initIdleManager();
        } catch(err) {
            console.error('Main avatar creation failed:', err);
            const errDiv = document.createElement('div');
            errDiv.style.cssText = 'display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#e74c3c;font-size:0.8rem;gap:0.5rem;padding:1rem;text-align:center';
            const icon = document.createElement('span');
            icon.className = 'material-icons-round';
            icon.style.fontSize = '2rem';
            icon.textContent = 'error';
            const msg = document.createElement('span');
            msg.textContent = `Avatar error: ${err.message || err}`;
            errDiv.append(icon, msg);
            avatarContainer.replaceChildren(errDiv);
        }
    }

    function initIdleManager() {
        const av = getAvatarRenderer();
        if (!av || av._idleManager || !getSettings()) return;
        const idleCfg = getSettings().idle || {};
        av.initIdleManager({
            enabled: idleCfg.enabled !== false,
            timeBeforeIdleSec: idleCfg.time_before_idle_sec || 30,
            timeToSleepSec: idleCfg.time_to_sleep_sec || 120,
            minIntervalSec: idleCfg.min_interval_sec || 8,
            maxIntervalSec: idleCfg.max_interval_sec || 15,
            baseUrl: BASE_URL,
            onRequestIdlePrompt: () => {
                const ws = getWs();
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'idle_prompt_request' }));
                }
            },
            onSleep: () => {},
            onWake: () => {},
        });
        av._idleManager.deactivate();
    }

    // ─── Tab switching ───
    let _initComplete = false;
    let _settingsLoaded = false;

    const _hash = window.location.hash.replace('#', '').split('/');
    if (_hash[0] === 'settings' && _hash[1] && (SETTINGS_SCHEMA[_hash[1]] || _hash[1] === 'Vault' || _hash[1] === 'Rules')) {
        setActiveSettingsTab(_hash[1]);
    }
    switchTab(_hash[0] || 'chat');

    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => switchTab(item.dataset.tab));
    });

    window.addEventListener('hashchange', () => {
        const h = window.location.hash.replace('#', '').split('/');
        if (!_initComplete) return;
        const currentPanel = document.querySelector('.tab-panel.active');
        const currentTab = currentPanel ? currentPanel.id.replace('tab-', '') : null;
        if (h[0] && h[0] !== currentTab) switchTab(h[0] || 'chat');
    });

    function switchTab(tabId) {
        const h = window.location.hash.replace('#', '').split('/');
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        const panel = document.getElementById(`tab-${tabId}`);
        if (panel) {
            document.querySelectorAll(`.nav-item[data-tab="${tabId}"]`).forEach(n => n.classList.add('active'));
            panel.classList.add('active');
            panel.focus({ preventScroll: true });
            window.location.hash = tabId;
            if (tabId === 'settings') {
                const sub = h[1];
                if (sub && (SETTINGS_SCHEMA[sub] || sub === 'Vault' || sub === 'Rules')) setActiveSettingsTab(sub);
                loadMCP();
            }
            if (tabId === 'avatar') createMainAvatar();
            if (tabId === 'metrics') loadMetrics();
            if (tabId === 'swarm' && !window.swarmGraph) {
                if (typeof window.initSwarmTab === 'function') window.initSwarmTab();
            }
            if (tabId === 'memory') {
                initMemoryGraph();
            } else {
                // Clean up memory graph animation when leaving the tab
                destroyMemoryGraph();
            }
        }
    }

    // ─── Voice input init ───
    initVoiceToggles();
    window._toggleVoiceInputState = (enabled) => _applyVoiceInput(enabled);

    // ─── Chat message actions ───
    chatMessages?.addEventListener('click', async (e) => {
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
                const ws = getWs();
                if (text && ws?.readyState === WebSocket.OPEN) {
                    addMessage('user', text);
                    ws.send(JSON.stringify({ type: 'user_message', text }));
                }
            }
        } else if (action === 'speak' || action === 'stop-speak') {
            const ws = getWs();
            if (getSpeakingMsgId() === msg.dataset.msgId && action === 'stop-speak') {
                flushTTSQueue();
                setSpeakingMsgId(null);
                updateSpeakButtons();
            } else if (ws?.readyState === WebSocket.OPEN) {
                if (getIsPlayingTTS()) flushTTSQueue();
                setSpeakingMsgId(msg.dataset.msgId);
                updateSpeakButtons();
                ws.send(JSON.stringify({ type: 'command', command: 'speak', text: body }));
            }
        }
    });

    // ─── Image attachment ───
    let _pendingImageData = null;
    const imgBtn = document.getElementById('img-btn');
    const imgInput = document.getElementById('img-input');
    const imgPreview = document.getElementById('img-preview');
    const imgPreviewSrc = document.getElementById('img-preview-src');
    const imgPreviewRemove = document.getElementById('img-preview-remove');
    if (imgBtn && imgInput) {
        imgBtn.addEventListener('click', () => imgInput.click());
        imgInput.addEventListener('change', (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (ev) => {
                _pendingImageData = ev.target?.result;
                if (imgPreviewSrc && imgPreview) {
                    imgPreviewSrc.src = _pendingImageData;
                    imgPreview.style.display = 'flex';
                }
            };
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

    // ─── Auto-focus on typing ───
    document.addEventListener('keydown', e => {
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            if (isMcpPanelOpen()) return;  // don't steal focus while MCP panel is open
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

    // ─── Tauri Ctrl+R ───
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

    // ─── Command suggestions ───
    let CMD_LIST = [];
    const cmdSuggestions = document.getElementById('cmd-suggestions');
    let _cmdSelectedIndex = -1;

    function updateCmdSuggestions() {
        const val = chatInput.value;
        if (!val.startsWith('/')) { cmdSuggestions?.classList.remove('show'); return; }
        const partial = val.substring(1).toLowerCase();
        const matches = CMD_LIST.filter(c => c.name.startsWith(partial));
        if (!matches.length || partial.includes(' ')) { cmdSuggestions?.classList.remove('show'); return; }
        if (cmdSuggestions) {
            cmdSuggestions.innerHTML = matches.map((c, i) =>
                `<div class="cmd-item${i === _cmdSelectedIndex ? ' selected' : ''}" data-index="${i}">
                    <span class="cmd-name">/${escHtml(c.name)}</span>
                    <span class="cmd-desc">${escHtml(c.desc)}</span>
                </div>`
            ).join('');
            cmdSuggestions.classList.add('show');
        }
        _cmdSelectedIndex = Math.min(_cmdSelectedIndex, matches.length - 1);
    }

    chatInput?.addEventListener('keydown', e => {
        // ── MCP panel keyboard navigation ──
        if (isMcpPanelOpen()) {
            if (handleMcpKeydown(e)) return;
        }
        if (cmdSuggestions?.classList.contains('show')) {
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
            if (e.key === 'Escape') { cmdSuggestions.classList.remove('show'); return; }
        }
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    chatInput?.addEventListener('input', function () {
        if (isMcpPanelOpen()) return;  // suppress suggestions while MCP panel is open
        this.style.height = 'auto';
        this.style.height = this.scrollHeight + 'px';
        _cmdSelectedIndex = 0;
        updateCmdSuggestions();
    });
    chatInput?.addEventListener('blur', () => {
        setTimeout(() => cmdSuggestions?.classList.remove('show'), 150);
    });
    chatInput?.addEventListener('focus', updateCmdSuggestions);

    let _typingTimer;
    chatInput?.addEventListener('keydown', () => {
        if (isMcpPanelOpen()) return;  // suppress typing indicator while MCP panel is open
        clearTimeout(_typingTimer);
        setStatus('typing');
        const ws = getWs();
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'command', command: 'typing' }));
        _typingTimer = setTimeout(() => {
            setStatus('ready');
            if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'command', command: 'stop_typing' }));
        }, 2000);
    });

    // ─── Core functions ───
    function setStatus(state) {
        const el = document.getElementById('chat-avatar-status');
        const avatar = document.getElementById('chat-avatar');
        if (!el || !avatar) return;
        avatar.className = 'chat-avatar';
        const labels = {
            thinking: 'status.thinking',
            speaking: 'status.speaking',
            listening: 'status.listening',
            typing: 'status.typing',
            error: 'status.error',
        };
        el.textContent = t(labels[state] || 'status.ready');
        if (state && labels[state]) avatar.classList.add(state);
    }

    function setCharacterAvatar(charName) {
        const el = document.getElementById('chat-avatar-name');
        if (el) el.textContent = charName;
    }

    function updateSpeakButtons() {
        document.querySelectorAll('.msg-assistant .msg-action[data-action="speak"], .msg-assistant .msg-action[data-action="stop-speak"]').forEach(btn => {
            const msg = btn.closest('.msg');
            const isSpeaking = msg.dataset.msgId === getSpeakingMsgId();
            btn.dataset.action = isSpeaking ? 'stop-speak' : 'speak';
            btn.title = isSpeaking ? 'Stop' : 'Speak';
            btn.innerHTML = isSpeaking ? '<span class="material-icons-round">stop</span>' : '<span class="material-icons-round">volume_up</span>';
        });
    }

    function updateSessionButtons() {
        const newBtn = document.getElementById('new-chat-btn');
        const newSessBtn = document.getElementById('new-session-btn');
        const vis = getSessionHasMessages() ? '' : 'none';
        if (newBtn) newBtn.style.display = vis;
        if (newSessBtn) newSessBtn.style.display = vis;
    }

    function addMessage(role, text) {
        if (!chatMessages) return null;
        const welcome = chatMessages.querySelector('.welcome-message');
        if (welcome) welcome.remove();

        const div = document.createElement('div');
        div.className = `msg msg-${role}`;
        div.dataset.msgId = 'msg-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
        // Set body via DOM to avoid XSS
        const bodyDiv = document.createElement('div');
        bodyDiv.innerHTML = getMessageHtml(role, text);
        while (bodyDiv.firstChild) div.appendChild(bodyDiv.firstChild);
        chatMessages.appendChild(div);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        if (!getSessionHasMessages()) {
            setSessionHasMessages(true);
            updateSessionButtons();
            setTimeout(loadHistory, 1000);
        }

        const body = div.querySelector('.msg-body');
        if (body && body.scrollHeight > 500) {
            div.classList.add('collapsible');
            const expandBtn = document.createElement('button');
            expandBtn.className = 'msg-expand-btn';
            expandBtn.textContent = 'Show more...';
            expandBtn.addEventListener('click', () => {
                const expanded = body.classList.toggle('expanded');
                expandBtn.textContent = expanded ? 'Show less' : 'Show more...';
            });
            div.appendChild(expandBtn);
        }
        return div;
    }

    function showWelcomeMessage() {
        if (!chatMessages) return;
        chatMessages.innerHTML = '';
        const welcome = document.createElement('div');
        welcome.className = 'welcome-message';
        welcome.setAttribute('role', 'status');
        welcome.innerHTML = `
            <div class="welcome-icon" aria-hidden="true">
                <span class="material-icons-round" style="font-size:3rem">forum</span>
            </div>
            <h2>${t('welcome.title')}</h2>
            <p>${t('welcome.subtitle')}</p>
            <div class="welcome-hints">
                <button class="welcome-hint" data-prompt="${escHtml(t('welcome.hint_about'))}">${escHtml(t('welcome.hint_about'))}</button>
                <button class="welcome-hint" data-prompt="${escHtml(t('welcome.hint_capabilities'))}">${escHtml(t('welcome.hint_capabilities'))}</button>
                <button class="welcome-hint" data-prompt="${escHtml(t('welcome.hint_brainstorm'))}">${escHtml(t('welcome.hint_brainstorm'))}</button>
            </div>
        `;
        chatMessages.appendChild(welcome);

        welcome.querySelectorAll('.welcome-hint').forEach(btn => {
            btn.addEventListener('click', () => {
                const prompt = btn.dataset.prompt;
                const ws = getWs();
                if (prompt && ws?.readyState === WebSocket.OPEN) {
                    addMessage('user', prompt);
                    ws.send(JSON.stringify({ type: 'user_message', text: prompt }));
                    chatInput.value = '';
                    setStatus('thinking');
                }
            });
        });
    }

    function clearErrors() {
        chatMessages?.querySelectorAll('.msg-assistant.msg-error').forEach(el => {
            const prev = el.previousElementSibling;
            if (prev?.classList.contains('msg-user')) prev.remove();
            el.remove();
        });
    }

    let _sending = false;
    function sendMessage() {
        if (_sending) return;
        _sending = true;
        try {
            _sendMessageInner();
        } catch (e) {
            console.error('sendMessage error:', e);
            showToast('Failed to send message', 'danger');
        } finally {
            _sending = false;
        }
    }
    function _sendMessageInner() {
        const text = chatInput.value.trim();
        if (!text) return;
        const ws = getWs();
        if (!ws) { showToast('Not connected', 'danger'); return; }
        if (ws.readyState === WebSocket.CONNECTING) { showToast('Connecting...', 'danger'); return; }
        if (ws.readyState !== WebSocket.OPEN) {
            getPendingMessages().push(JSON.stringify({ type: 'user_message', text }));
            chatInput.value = '';
            chatInput.style.height = 'auto';
            showToast('Message queued — reconnecting...', 'warning');
            return;
        }

        if (text.startsWith('/')) {
            const parts = text.split(/\s+/);
            const command = parts[0].substring(1).toLowerCase();
            const args = parts.slice(1).join(' ');
            // Intercept /mcp — open interactive panel instead of sending
            if (command === 'mcp') {
                chatInput.value = '';
                chatInput.style.height = 'auto';
                openMcpPanel();
                return;
            }
            ws.send(JSON.stringify({ type: 'slash_command', command, args }));
            chatInput.value = '';
            chatInput.style.height = 'auto';
            return;
        }

        clearErrors();
        flushTTSQueue();
        if (typeof getAvatarRenderer()?.interact === 'function') getAvatarRenderer().interact();

        const editId = chatInput.dataset.editTarget;
        if (editId) {
            const oldMsg = chatMessages?.querySelector(`[data-msg-id="${editId}"]`);
            if (oldMsg) {
                const next = oldMsg.nextElementSibling;
                if (next?.classList.contains('msg-assistant')) next.remove();
                oldMsg.remove();
            }
            delete chatInput.dataset.editTarget;
        }

        clearTimeout(_typingTimer);
        setStatus('ready');
        try { ws.send(JSON.stringify({ type: 'command', command: 'stop_typing' })); } catch (e) {}
        setLastUserMessage(addMessage('user', text));
        const msg = { type: 'user_message', text, session_id: getCurrentSessionId() || undefined };
        if (_pendingImageData) {
            msg.images = [_pendingImageData];
            _pendingImageData = null;
            if (imgPreview) imgPreview.style.display = 'none';
            if (imgPreviewSrc) imgPreviewSrc.src = '';
            if (imgInput) imgInput.value = '';
        }
        try { ws.send(JSON.stringify(msg)); } catch (e) { showToast('Send failed', 'danger'); }

        const av = getAvatarRenderer();
        if (av?._idleManager) av._idleManager.wake();
        chatInput.value = '';
        chatInput.style.height = 'auto';
    }

    if (sendBtn) sendBtn.addEventListener('click', () => {
        if (isMcpPanelOpen()) return;
        sendMessage();
    });


    async function fetchCommands() {
        try {
            const data = await api(BASE_URL + '/api/commands');
            CMD_LIST = data?.commands || [];
        } catch { CMD_LIST = []; }
    }

    async function loadSession(sessionId) {
        if (!chatMessages) return;
        chatMessages.innerHTML = '<div class="msg msg-system" style="text-align:center;color:var(--muted);padding:2rem"><span class="material-icons-round" style="font-size:1.5rem;display:block;margin-bottom:0.5rem">hourglass_top</span>Loading conversation...</div>';
        setSessionHasMessages(false);
        updateSessionButtons();
        const _setHash = (sid) => {
            const tab = document.querySelector('.tab-panel.active');
            if (!tab || tab.id === 'tab-chat') location.hash = 'chat/' + sid;
        };
        try {
            const session = await api(BASE_URL + `/api/memory/session/${sessionId}`);
            chatMessages.innerHTML = '';
            if (session?.exists === false) {
                const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
                if (res?.session_id) { setCurrentSessionId(res.session_id); _setHash(res.session_id); }
                return;
            }
            if (session?.messages?.length) {
                setSessionHasMessages(true);
                session.messages.forEach((m, i) => {
                    let role = m.role;
                    const content = stripMarkers(m.content);
                    if (role === 'system' && (content.startsWith('Tool result') || content.startsWith('Tool parse error'))) role = 'tool';
                    const div = document.createElement('div');
                    div.className = `msg msg-${role}`;
                    div.dataset.msgId = `msg-loaded-${i}`;
                    if (role === 'assistant' && _isErrorText(content)) div.classList.add('msg-error');
                    const msgBody = document.createElement('div');
                    msgBody.innerHTML = getMessageHtml(role, content);
                    while (msgBody.firstChild) div.appendChild(msgBody.firstChild);
                    chatMessages.appendChild(div);
                });
                chatMessages.scrollTop = chatMessages.scrollHeight;
            } else {
                setSessionHasMessages(false);
                updateSessionButtons();
                showWelcomeMessage();
            }
            setCurrentSessionId(session?.session_id || sessionId);
            if (getCurrentSessionId()) _setHash(getCurrentSessionId());
            updateSessionButtons();
        } catch (e) {
            chatMessages.innerHTML = '';
            const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
            setCurrentSessionId(res?.session_id || sessionId);
            if (res?.session_id) _setHash(res.session_id);
            updateSessionButtons();
        }
    }

    // Expose for memory graph and other external modules
    window.loadChatSession = loadSession;

    async function loadCharacters() {
        const grid = document.getElementById('characters-grid');
        if (!grid) return;
        grid.setAttribute('aria-busy', 'true');
        grid.innerHTML = Array(3).fill('').map(() => `
            <div class="char-card" aria-hidden="true">
                <div class="skeleton skeleton-circle"></div>
                <div class="char-info">
                    <div class="skeleton skeleton-text" style="width:40%"></div>
                    <div class="skeleton skeleton-text"></div>
                </div>
            </div>
        `).join('');
        grid.setAttribute('aria-busy', 'true');

        const chars = await api(BASE_URL + '/api/characters');
        if (!chars) {
            grid.innerHTML = `<p class="muted" style="padding:1rem">${t('characters.no_characters') || 'No characters found'}</p>`;
            grid.removeAttribute('aria-busy');
            return;
        }
        const s = getSettings();
        if (s) s._cached_chars = chars;
        const active = s?.character?.active || 'amalgam';
        grid.innerHTML = '';
        grid.removeAttribute('aria-busy');

        for (const [id, c] of Object.entries(chars)) {
            const card = document.createElement('div');
            card.className = `char-card ${id === active ? 'active' : ''}`;
            let iconUrl = c.icon_url || './icons/logo.png';
            if (iconUrl.startsWith('/')) iconUrl = BASE_URL + iconUrl;
            const searchText = [id, c.name, c.description, c.personality, c.voice].filter(Boolean).join(' ').toLowerCase();
            card.dataset.search = searchText;
            card.innerHTML = `
                <img src="${escHtml(iconUrl)}" alt="${escHtml(c.name)} avatar" class="char-avatar" onerror="this.src='./icons/logo.png'">
                <div class="char-info">
                    <h3>${escHtml(c.name || id)}</h3>
                    <p>${escHtml(c.description || '')}</p>
                    <div class="char-tags">
                        ${c.personality ? `<span class="tag">${escHtml(c.personality)}</span>` : ''}
                        ${c.voice ? `<span class="tag tag-voice">${escHtml(c.voice.split('-').pop().replace('Neural', ''))}</span>` : ''}
                    </div>
                </div>
            `;
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
                setCharacterAvatar(c.name || id);
                await fetchCommands();
                let vrmPath = c.model_url || '/characters/default/model.vrm';
                if (vrmPath.startsWith('/')) vrmPath = BASE_URL + vrmPath;
                const av = getAvatarRenderer();
                const apr = getAvatarPreviewRenderer();
                if (av) av.loadVRM(vrmPath);
                if (apr) apr.loadVRM(vrmPath);
                await api(BASE_URL + '/api/settings/set', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: 'avatar.model_path', value: vrmPath.replace(/^\/+/, '') })
                });
                showToast(`Switched to ${c.name || id}`);
            });
            grid.appendChild(card);
        }
    }

    async function loadRelationship() {
        try {
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
            const relStats = [
                { label: 'Stage', value: data.stage || 'stranger' },
                { label: 'Interactions', value: data.interaction_count || 0 },
                { label: 'Sentiment', value: data.avg_sentiment ?? 0.5 },
                { label: 'Depth', value: data.avg_depth ?? 0 },
                { label: 'User words', value: data.total_words_user || 0 },
                { label: 'Assistant words', value: data.total_words_assistant || 0 },
            ];
            container.innerHTML = relStats.map(s =>
                `<div class="rel-stat"><span class="rel-stat-label">${escHtml(s.label)}</span><span>${escHtml(String(s.value))}</span></div>`
            ).join('');
        } catch (e) {
            console.warn('Failed to load relationship:', e);
            const container = document.getElementById('relationship-display');
            if (container) container.innerHTML = '<p class="muted">Could not load relationship data.</p>';
        }
    }

    async function loadSessions() {
        try {
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
                    <strong>${escHtml(s.title || s.id)}</strong>
                    <span class="muted">${s.message_count || '?'} msgs</span>
                    <span class="data-session-delete" data-id="${escHtml(s.id)}">delete</span>
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
        } catch (e) {
            console.warn('Failed to load sessions:', e);
        }
    }

    function applySettings(d) {
        setSettingsCache(d);
        initIdleManager();
        updateCompanionSettings(d);
        _applyVoiceInput(d.ui?.voice_input ?? true);
        _applyVoiceOutput(d.ui?.voice_output ?? true);

        const thinkingToggle = document.getElementById('thinking-toggle');
        if (thinkingToggle) {
            thinkingToggle.checked = d.ui?.thinking_enabled ?? true;
            thinkingToggle.onchange = async function() {
                await fetch(BASE_URL + '/api/settings/set', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ key: 'ui.thinking_enabled', value: this.checked })
                });
            };
        }

        applyTheme(d.ui?.theme || 'dark');
        document.documentElement.style.setProperty('--font-size', (d.ui?.font_size || 14) + 'px');

        const charId = d.character?.active || 'amalgam';
        const cachedChars = d._cached_chars;
        const charEntry = cachedChars?.[charId];
        setCharacterAvatar(charEntry?.name || (charId.charAt(0).toUpperCase() + charId.slice(1)));
    }

    // ─── Character search ───
    const charSearchInput = document.getElementById('char-search-input');
    let _charSearchTimer = null;
    charSearchInput?.addEventListener('input', () => {
        clearTimeout(_charSearchTimer);
        _charSearchTimer = setTimeout(() => {
            const q = charSearchInput.value.toLowerCase();
            document.querySelectorAll('#characters-grid .char-card').forEach(card => {
                const text = card.dataset.search || '';
                card.style.display = text.includes(q) ? '' : 'none';
            });
        }, 200);
    });

    // ─── Shell permission ───
    function hideShellPermission() {
        const overlay = document.getElementById('shell-permission-overlay');
        if (overlay) overlay.style.display = 'none';
    }
    async function approveShellCommand(mode) {
        const cmdDisplay = document.getElementById('shell-pending-cmd');
        const cmd = cmdDisplay?.textContent || '';
        if (!cmd) return;
        hideShellPermission();
        if (mode === 'decline') { showToast('Command declined'); return; }
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

    // ─── Keyboard shortcuts ───
    function setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                const sendBtn = document.getElementById('send-btn');
                if (sendBtn && !sendBtn.disabled) { e.preventDefault(); sendBtn.click(); }
                return;
            }
            if (e.key === 'Escape') {
                const historyPanel = document.getElementById('history-panel');
                if (historyPanel?.classList.contains('visible')) { historyPanel.classList.remove('visible'); return; }
                const kbdHint = document.getElementById('kbd-hint');
                if (kbdHint?.classList.contains('visible')) { kbdHint.classList.remove('visible'); return; }
                const shellOverlay = document.getElementById('shell-permission-overlay');
                if (shellOverlay && shellOverlay.style.display !== 'none') { shellOverlay.style.display = 'none'; return; }
                const setupWizard = document.getElementById('setup-wizard-overlay');
                if (setupWizard && setupWizard.style.display !== 'none') {
                    setupWizard.style.display = 'none';
                    if (setupWizard._trapFocusHandler) { setupWizard.removeEventListener('keydown', setupWizard._trapFocusHandler); delete setupWizard._trapFocusHandler; }
                    return;
                }
                return;
            }
            if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
                if (chatInput && document.activeElement !== chatInput) {
                    const activeTag = document.activeElement?.tagName?.toLowerCase();
                    if (activeTag !== 'input' && activeTag !== 'textarea' && activeTag !== 'select') {
                        e.preventDefault();
                        chatInput.focus();
                    }
                }
            }
        });
    }

    // ─── Wire up ws.js callbacks ───
    const { setWsCallbacks } = await import('./modules/ws.js');
    setWsCallbacks({ addMessage, setStatus, loadSession, fetchCommands, loadCharacters, applySettings });
    setHistoryDeps({ loadSession, showToast });

    // ─── Settings tab observer ───
    const settingsTab = document.getElementById('tab-settings');
    if (settingsTab) {
        const renderSettingsWithProviders = async () => {
            await Promise.all([refreshProviderList(), refreshCharacterList()]);
            renderSettings();
            _attachSettingsDelegates();
            loadRelationship();
            loadSessions();
            refreshCharacterInfo();
            const settings = getSettings() || {};
            const active = settings.provider?.active;
            if (active) setTimeout(() => fetchModels(active), 100);
        };
        let _settingsTabWasActive = settingsTab.classList.contains('active');
        const observer = new MutationObserver(() => {
            const isNowActive = settingsTab.classList.contains('active');
            if (isNowActive && !_settingsTabWasActive) renderSettingsWithProviders();
            _settingsTabWasActive = isNowActive;
        });
        observer.observe(settingsTab, { attributes: true, attributeFilter: ['class'] });
        if (settingsTab.classList.contains('active')) renderSettingsWithProviders();
    }

    // ─── History events ───
    initHistoryEvents();

    // ─── Boot ───
    initCustomSelects();
    connectWS();
    init().catch(e => {
        console.error('Init failed:', e);
        showToast('Failed to connect to server', 'danger');
        _initComplete = true;
    });

    async function init() {
        const settings = await api(BASE_URL + '/api/settings');
        if (settings) { applySettings(settings); _settingsLoaded = true; }
        initCompanion();
        await loadCharacters();
        await fetchCommands();
        setupKeyboardShortcuts();
        const parts = location.hash.replace('#', '').split('/');
        const sessionId = parts[0] === 'chat' && parts[1] ? parts[1] : null;
        await loadSession(sessionId || 'current');
        await loadHistory();
        _initComplete = true;
    }

    // ─── Keyboard avoidance ───
    if (window.visualViewport) {
        const adjustForKeyboard = () => {
            const chatInputArea = document.querySelector('.chat-input-area');
            if (!chatInputArea) return;
            const diff = window.innerHeight - window.visualViewport.height;
            if (diff > 100) {
                chatInputArea.style.position = 'fixed';
                chatInputArea.style.bottom = (window.innerHeight - window.visualViewport.height) + 'px';
                chatInputArea.style.left = '0';
                chatInputArea.style.right = '0';
                chatInputArea.style.zIndex = '1001';
            } else {
                chatInputArea.style.position = '';
                chatInputArea.style.bottom = '';
                chatInputArea.style.left = '';
                chatInputArea.style.right = '';
                chatInputArea.style.zIndex = '';
            }
        };
        window.visualViewport.addEventListener('resize', adjustForKeyboard);
        window.visualViewport.addEventListener('scroll', adjustForKeyboard);
    }

    // ─── Periodic health refresh ───
    const _healthInterval = setInterval(refreshHealth, 30000);
    window.addEventListener('beforeunload', () => clearInterval(_healthInterval));
    refreshHealth();

    // ─── Online/offline detection ───
    // Set initial offline-bar state based on navigator.onLine
    const initBar = document.getElementById('offline-bar');
    if (initBar) {
        if (navigator.onLine) {
            initBar.classList.add('hidden');
            initBar.classList.remove('visible');
        } else {
            initBar.classList.remove('hidden');
            initBar.classList.add('visible');
        }
    }
    window.addEventListener('online', () => {
        const bar = document.getElementById('offline-bar');
        if (bar) { bar.classList.add('hidden'); bar.classList.remove('visible'); }
        const ws = getWs();
        if (ws && ws.readyState !== WebSocket.OPEN && ws.readyState !== WebSocket.CONNECTING) connectWS();
    });
    window.addEventListener('offline', () => {
        const bar = document.getElementById('offline-bar');
        if (bar) { bar.classList.remove('hidden'); bar.classList.add('visible'); }
    });

});

// ─── Setup wizard second DOMContentLoaded ───
document.addEventListener('DOMContentLoaded', () => {
    _initSetupWizard();
    document.addEventListener('input', e => {
        if (e.target.id === 'setup-api-key') {
            const provider = document.getElementById('setup-provider-grid')?.querySelector('.selected');
            const apiKeyInput = document.getElementById('setup-api-key');
            const continueBtn = document.getElementById('setup-continue-btn');
            if (continueBtn && provider) {
                continueBtn.disabled = !apiKeyInput?.value?.trim();
            }
        }
    });
});

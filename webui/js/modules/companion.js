/**
 * companion.js — Unified companion mode module for Amalgam WebUI.
 *
 * Provides:
 *  - Idle detection -> sends idle_enter/idle_exit events to backend
 *  - Companion message display (floating companion bubble)
 *  - State synchronization with backend CompanionEngine
 *
 * Usage:
 *   import { initCompanion, updateCompanionSettings } from './modules/companion.js';
 *   initCompanion();
 *   updateCompanionSettings(settings);
 */

import { getSettings } from './state.js';

// ── Constants ──────────────────────────────────────────────────────────

const IDLE_TIMEOUT_MS = 5 * 60 * 1000;       // 5 minutes before idle
const AWAY_TIMEOUT_MS = 2 * 60 * 1000;       // 2 more minutes -> away
const ACTIVITY_EVENTS = ['mousedown', 'keydown', 'touchstart', 'scroll', 'mousemove'];
const BUBBLE_DISPLAY_MS = 8000;

// ── State ──────────────────────────────────────────────────────────────

let _companionEnabled = false;
let _idleTimer = null;
let _awayTimer = null;
let _isIdle = false;
let _isAway = false;
let _bubbleTimer = null;
let _initialized = false;
let _ws = null;

let _companionBubble = null;
let _companionStatus = null;

// ── Initialization ─────────────────────────────────────────────────────

export function initCompanion() {
    if (_initialized) return;
    _initialized = true;
    _companionEnabled = getSettings()?.companion?.enabled ?? false;
    _createCompanionUI();
    _startIdleTracking();
    _startListening();
    console.debug('[Companion] initialized, enabled:', _companionEnabled);
}

export function updateCompanionSettings(settings) {
    const wasEnabled = _companionEnabled;
    _companionEnabled = settings?.companion?.enabled ?? false;
    if (_companionStatus) {
        _companionStatus.textContent = _companionEnabled ? 'ON' : 'OFF';
        _companionStatus.className = _companionEnabled ? 'companion-status on' : 'companion-status off';
    }
    if (_companionEnabled && !wasEnabled) {
        _resetIdleState();
    } else if (!_companionEnabled && wasEnabled) {
        if (_isIdle) _sendIdleExit();
        _clearIdleTimers();
    }
}

// ── Idle Detection ─────────────────────────────────────────────────────

function _startIdleTracking() {
    ACTIVITY_EVENTS.forEach(evt => {
        document.addEventListener(evt, _onActivity, { passive: true });
    });
    _resetIdleTimer();
}

function _stopIdleTracking() {
    ACTIVITY_EVENTS.forEach(evt => {
        document.removeEventListener(evt, _onActivity);
    });
    _clearIdleTimers();
}

function _onActivity() {
    if (!_companionEnabled) return;
    const wasIdle = _isIdle;
    const wasAway = _isAway;
    _resetIdleState();
    if (wasIdle || wasAway) _sendIdleExit();
    _resetIdleTimer();
}

function _resetIdleState() {
    _isIdle = false; _isAway = false; _clearIdleTimers();
}

function _resetIdleTimer() {
    _clearIdleTimers();
    _idleTimer = setTimeout(_onIdleTimeout, IDLE_TIMEOUT_MS);
}

function _clearIdleTimers() {
    if (_idleTimer) { clearTimeout(_idleTimer); _idleTimer = null; }
    if (_awayTimer) { clearTimeout(_awayTimer); _awayTimer = null; }
}

function _onIdleTimeout() {
    if (!_companionEnabled) return;
    _isIdle = true;
    _sendIdleEnter();
    _awayTimer = setTimeout(() => {
        _isAway = true;
        _sendIdleTimeout();
    }, AWAY_TIMEOUT_MS);
}

// ── WebSocket Messages ─────────────────────────────────────────────────

function _getWs() {
    try {
        const mod = window.__WS_MODULE;
        if (mod && mod.getWs) {
            const ws = mod.getWs();
            if (ws && ws.readyState === WebSocket.OPEN) { _ws = ws; return ws; }
        }
    } catch (_) {}
    if (_ws && _ws.readyState === WebSocket.OPEN) return _ws;
    return null;
}

function _sendIdleEnter() {
    const ws = _getWs();
    if (ws) ws.send(JSON.stringify({ type: 'idle_enter' }));
}

function _sendIdleExit() {
    const ws = _getWs();
    if (ws) ws.send(JSON.stringify({ type: 'idle_exit' }));
}

function _sendIdleTimeout() {
    const ws = _getWs();
    if (ws) ws.send(JSON.stringify({ type: 'idle_timeout' }));
}

// ── Companion Message Display ──────────────────────────────────────────

export function showCompanionMessage(text, context, icon) {
    if (!_companionBubble) return;
    if (_bubbleTimer) { clearTimeout(_bubbleTimer); _bubbleTimer = null; }

    const textEl = _companionBubble.querySelector('.companion-bubble-text');
    if (textEl) textEl.textContent = text;

    // If the backend provided an icon, use it; otherwise derive from context
    const ctxEl = _companionBubble.querySelector('.companion-bubble-context');
    if (ctxEl) {
        ctxEl.textContent = icon || _iconForContext(context);
        ctxEl.className = 'companion-bubble-context';
        if (context) ctxEl.classList.add('ctx-' + context);
    }

    _companionBubble.classList.remove('companion-bubble-hidden');
    _companionBubble.classList.add('companion-bubble-visible');

    _bubbleTimer = setTimeout(() => {
        _companionBubble.classList.remove('companion-bubble-visible');
        _companionBubble.classList.add('companion-bubble-hidden');
        _bubbleTimer = null;
    }, BUBBLE_DISPLAY_MS);
}

function _iconForContext(context) {
    // Deterministic emoji derived from context string — no hardcoded map.
    // Uses the sum of character codes to index into a pool of emoji,
    // so the same context always gets the same icon without a lookup table.
    if (!context) return '\u{1F4AC}'; // 💬 default
    const pool = ['\u{1F4AC}','\u{1F44B}','\u{1F4AD}','\u{2728}','\u{23F0}','\u{1F916}',
                  '\u{1F31F}','\u{1F389}','\u{1F3B5}','\u{1F30D}','\u{1F4A1}','\u{1F50D}'];
    let hash = 0;
    for (let i = 0; i < context.length; i++) hash = ((hash << 5) - hash) + context.charCodeAt(i);
    return pool[Math.abs(hash) % pool.length];
}

// ── UI Creation ────────────────────────────────────────────────────────

function _createCompanionUI() {
    const headerRight = document.querySelector('.header-right, .app-header .right');
    if (headerRight && !document.getElementById('companion-status-indicator')) {
        const el = document.createElement('div');
        el.id = 'companion-status-indicator';
        el.className = 'companion-indicator';
        el.innerHTML = `
            <span class="companion-icon">🤖</span>
            <span class="companion-status ${_companionEnabled ? 'on' : 'off'}"
                  id="companion-status-text">${_companionEnabled ? 'ON' : 'OFF'}</span>
        `;
        el.title = 'Companion Mode';
        headerRight.appendChild(el);
        _companionStatus = document.getElementById('companion-status-text');
    }

    if (!document.getElementById('companion-bubble')) {
        const bubble = document.createElement('div');
        bubble.id = 'companion-bubble';
        bubble.className = 'companion-bubble companion-bubble-hidden';
        bubble.innerHTML = `
            <div class="companion-bubble-avatar">🤖</div>
            <div class="companion-bubble-content">
                <div class="companion-bubble-context">💬</div>
                <div class="companion-bubble-text">Hello!</div>
            </div>
        `;
        document.body.appendChild(bubble);
        _companionBubble = bubble;
    }
}

// ── WebSocket Listener ─────────────────────────────────────────────────

function _startListening() {
    document.addEventListener('companion-message', (e) => {
        const detail = e.detail;
        if (detail && detail.content) showCompanionMessage(detail.content, detail.context, detail.icon);
    });
    window._showCompanionMessage = showCompanionMessage;
}

// ── Cleanup ────────────────────────────────────────────────────────────

export function destroyCompanion() {
    _stopIdleTracking();
    _clearIdleTimers();
    if (_bubbleTimer) { clearTimeout(_bubbleTimer); _bubbleTimer = null; }
    _initialized = false;
}


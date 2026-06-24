/**
 * companion.js — Companion mode frontend module
 *
 * Handles idle detection, sends idle_enter/idle_exit events,
 * and displays companion messages in chat with a distinct style.
 */
import { BASE_URL } from './config.js';
import { showToast } from './utils.js';
import { getWs, getSettings } from './state.js';

// --- Idle detection ---
let _idleTimer = null;
let _isIdle = false;
let _companionEnabled = false;
let _idleTimeoutMs = 0; // populated from settings in initCompanion()

const IDLE_EVENTS = ['mousedown', 'keydown', 'touchstart', 'scroll', 'mousemove'];

function _resetIdleTimer() {
    if (_idleTimer) clearTimeout(_idleTimer);

    if (_isIdle && _companionEnabled) {
        _isIdle = false;
        _sendIdleExit();
    }

    _idleTimer = setTimeout(_onIdleTimeout, _idleTimeoutMs);
}

function _onIdleTimeout() {
    if (!_isIdle && _companionEnabled) {
        _isIdle = true;
        _sendIdleEnter();
    }
}

function _sendIdleEnter() {
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'idle_enter' }));
    }
}

function _sendIdleExit() {
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'idle_exit' }));
    }
}

// --- Initialization ---

export function initCompanion() {
    const settings = getSettings();
    _companionEnabled = settings?.companion?.enabled ?? false;
    _idleTimeoutMs = (settings?.companion?.idle_check_delay ?? 5) * 60 * 1000;
    // Use a slightly shorter idle detection on the frontend to give
    // the backend time to start its own check-in timer
    _idleTimeoutMs = Math.max(_idleTimeoutMs * 0.5, 60_000); // at least 1 min

    if (_companionEnabled) {
        _startIdleTracking();
    }
}

export function updateCompanionSettings(settings) {
    const wasEnabled = _companionEnabled;
    _companionEnabled = settings?.companion?.enabled ?? false;
    _idleTimeoutMs = (settings?.companion?.idle_check_delay ?? 5) * 60 * 1000;
    _idleTimeoutMs = Math.max(_idleTimeoutMs * 0.5, 60_000);

    if (_companionEnabled && !wasEnabled) {
        _startIdleTracking();
    } else if (!_companionEnabled && wasEnabled) {
        _stopIdleTracking();
        // If currently idle when disabled, send idle_exit
        if (_isIdle) {
            _isIdle = false;
            _sendIdleExit();
        }
    }
}

function _startIdleTracking() {
    IDLE_EVENTS.forEach(evt => document.addEventListener(evt, _resetIdleTracker, { passive: true }));
    _resetIdleTimer();
}

function _stopIdleTracking() {
    IDLE_EVENTS.forEach(evt => document.removeEventListener(evt, _resetIdleTracker));
    if (_idleTimer) { clearTimeout(_idleTimer); _idleTimer = null; }
}

function _resetIdleTracker() {
    _resetIdleTimer();
}

export function isCompanionEnabled() {
    return _companionEnabled;
}

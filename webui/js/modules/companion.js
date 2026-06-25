/**
 * companion.js — Companion mode orchestrator
 *
 * v2: Integrates overlay, voice tools, idle detection, and settings persistence.
 *
 * Lifecycle:
 *   1. initCompanion() — called once on app boot (reads settings, sets up idle)
 *   2. enableCompanionMode() — called when companion mode is turned ON
 *      - Shows overlay, starts STT/TTS, shows palette
 *   3. disableCompanionMode() — called when companion mode is turned OFF
 *      - Hides overlay, stops STT, resets state
 *   4. updateCompanionSettings() — called on settings change
 *   5. _onCompanionAction() — handles palette button actions via DOM events
 *   6. _applyCompanionState() — applies state from a settings snapshot
 */

import { BASE_URL } from './config.js';
import { showToast } from './utils.js';
import { api } from './api-client.js';
import {
    getSettings,
    getWs,
    getVoiceInputEnabled, setVoiceInputEnabled,
    getVoiceOutputEnabled, setVoiceOutputEnabled,
} from './state.js';
import { initOverlay, showOverlay, hideOverlay, isOverlayVisible, updateMuteIndicator, updateTtsIndicator, getLastState, showDisconnectedIndicator, hideDisconnectedIndicator } from './companion-overlay.js';
import { _applyVoiceInput, _applyVoiceOutput } from './voice.js';

// --- Internal state ---
let _companionEnabled = false;
let _idleTimer = null;
let _isIdle = false;
let _idleTimeoutMs = 60000; // default 1 min
let _overlayInitialized = false;

const IDLE_EVENTS = ['mousedown', 'keydown', 'touchstart', 'scroll', 'mousemove'];

// ═════════════════════════════════════════════════════════════════
//  Initialization
// ═════════════════════════════════════════════════════════════════

/**
 * initCompanion()
 * Called once from app.js init().
 * Initializes the overlay DOM refs and sets up idle detection based on settings.
 */
export function initCompanion() {
    // Init overlay DOM refs
    initOverlay();
    _overlayInitialized = true;

    const settings = getSettings();
    _companionEnabled = settings?.companion?.enabled ?? false;
    _idleTimeoutMs = (settings?.companion?.idle_check_delay ?? 5) * 60 * 1000;
    _idleTimeoutMs = Math.max(_idleTimeoutMs * 0.5, 60000);

    // If companion was previously enabled (from last session), re-enable
    if (_companionEnabled) {
        enableCompanionMode({ restore: true });
    } else {
        // If overlay was left open (session restore), make sure it's hidden
        hideOverlay();
    }

    // Bind companion action events
    document.addEventListener('companion:action', _onCompanionAction);

    // Bind WS disconnect/reconnect events
    document.addEventListener('ws:disconnected', _onWsDisconnected);
    document.addEventListener('ws:connected', _onWsReconnected);
}

/**
 * enableCompanionMode(options)
 * Turns on the companion overlay, voice, and idle detection.
 *
 * @param {Object} [options]
 * @param {boolean} [options.restore=false] - Restore previous overlay position/size
 * @param {boolean} [options.silent=false] - Don't show toast
 */
export function enableCompanionMode(options = {}) {
    if (_companionEnabled && !options.restore) return;
    _companionEnabled = true;

    // 1. Show overlay with VRM avatar (retry if renderer not ready yet)
    if (_overlayInitialized) {
        _showOverlayWithRetry();
    }

    // 2. Enable voice input (mic) if not already on
    if (!getVoiceInputEnabled()) {
        _applyVoiceInput(true, { persist: true, toast: false });
    }

    // 3. Enable voice output (speaker) if not already on
    if (!getVoiceOutputEnabled()) {
        _applyVoiceOutput(true, { persist: true, toast: false });
    }

    // 4. Update palette mute/TTS button states
    _updatePaletteStates();

    // 5. Start idle tracking
    _startIdleTracking();

    // 6. Tell the backend
    _sendCompanionState(true);

    // 7. Persist to settings
    _persistCompanionEnabled(true);

    if (!options.silent) {
        showToast('Companion mode enabled', 'success');
    }

    // Dispatch event for other modules
    document.dispatchEvent(new CustomEvent('companion:state', { detail: { enabled: true } }));
}

/**
 * _showOverlayWithRetry()
 * Attempts to show the overlay. If the avatar renderer is not yet available
 * (still loading asynchronously), retries up to the given number of attempts.
 */
function _showOverlayWithRetry(maxAttempts = 20, intervalMs = 500) {
    const attempt = (n) => {
        if (n >= maxAttempts) {
            console.warn('[Companion] Overlay show failed after max retries — avatar renderer never became available');
            return;
        }
        if (showOverlay({})) {
            // Success
            return;
        }
        // Retry after interval — the avatar module might still be loading
        setTimeout(() => attempt(n + 1), intervalMs);
    };
    attempt(0);
}

/**
 * disableCompanionMode(options)
 * Turns off the companion overlay, voice, and idle detection.
 */
export function disableCompanionMode(options = {}) {
    if (!_companionEnabled) return;
    _companionEnabled = false;

    // 1. Hide overlay
    if (_overlayInitialized) {
        hideOverlay();
    }

    // 2. Stop voice input (mic)
    if (getVoiceInputEnabled()) {
        _applyVoiceInput(false, { persist: true, toast: false });
    }

    // 3. Keep voice output as is (user may still want TTS in chat)

    // 4. Stop idle tracking
    _stopIdleTracking();
    if (_isIdle) {
        _isIdle = false;
        _sendIdleExit();
    }

    // 5. Tell the backend
    _sendCompanionState(false);

    // 6. Persist to settings
    _persistCompanionEnabled(false);

    if (!options.silent) {
        showToast('Companion mode disabled', 'info');
    }

    document.dispatchEvent(new CustomEvent('companion:state', { detail: { enabled: false } }));
}

/**
 * toggleCompanionMode()
 * Toggle companion on/off.
 */
export function toggleCompanionMode() {
    if (_companionEnabled) {
        disableCompanionMode();
    } else {
        enableCompanionMode();
    }
}

export function isCompanionEnabled() {
    return _companionEnabled;
}

// ═════════════════════════════════════════════════════════════════
//  Settings update handler
// ═════════════════════════════════════════════════════════════════

/**
 * updateCompanionSettings(settings)
 * Called whenever settings change (from WS or local update).
 * Syncs the companion state with settings.
 */
export function updateCompanionSettings(settings) {
    const wasEnabled = _companionEnabled;
    const newEnabled = settings?.companion?.enabled ?? false;
    _idleTimeoutMs = (settings?.companion?.idle_check_delay ?? 5) * 60 * 1000;
    _idleTimeoutMs = Math.max(_idleTimeoutMs * 0.5, 60000);

    if (newEnabled && !wasEnabled) {
        enableCompanionMode({ silent: true });
    } else if (!newEnabled && wasEnabled) {
        disableCompanionMode({ silent: true });
    }

    // Update idle tracking even if companion state didn't change
    if (newEnabled) {
        _startIdleTracking();
    }
}

/**
 * _applyCompanionState(state)
 * Apply a full companion state snapshot from settings or external push.
 * Used when settings are pushed from another client or on initial load.
 *
 * @param {Object} state - Companion state object, e.g. { enabled: true, overlay_position_x: '50%', ... }
 */
export function _applyCompanionState(state) {
    if (!state) return;
    const shouldEnable = state.enabled === true;
    if (shouldEnable && !_companionEnabled) {
        enableCompanionMode({ silent: true, restore: true });
    } else if (!shouldEnable && _companionEnabled) {
        disableCompanionMode({ silent: true });
    }
}

// ═════════════════════════════════════════════════════════════════
//  Idle Detection
// ═════════════════════════════════════════════════════════════════

function _startIdleTracking() {
    _stopIdleTracking();
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

// ═════════════════════════════════════════════════════════════════
//  Palette UI helpers
// ═════════════════════════════════════════════════════════════════

function _updatePaletteStates() {
    const palette = document.getElementById('companion-palette');
    if (!palette) return;
    // Update mute button
    const muteBtn = palette.querySelector('[data-action="mute"]');
    if (muteBtn) {
        const muted = !getVoiceInputEnabled();
        muteBtn.classList.toggle('active', muted);
        muteBtn.querySelector('.material-icons-round').textContent = muted ? 'mic_off' : 'mic';
        muteBtn.title = muted ? 'Unmute mic' : 'Mute mic';
    }
    // Update TTS button
    const ttsBtn = palette.querySelector('[data-action="tts-toggle"]');
    if (ttsBtn) {
        const ttsOff = !getVoiceOutputEnabled();
        ttsBtn.classList.toggle('active', ttsOff);
        ttsBtn.querySelector('.material-icons-round').textContent = ttsOff ? 'volume_off' : 'volume_up';
        ttsBtn.title = ttsOff ? 'Enable TTS' : 'Disable TTS';
    }
    updateMuteIndicator(!getVoiceInputEnabled());
}

// ═════════════════════════════════════════════════════════════════
//  Backend communication
// ═════════════════════════════════════════════════════════════════

function _sendCompanionState(enabled) {
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'companion_state',
            enabled: enabled,
        }));
    }
}

function _persistCompanionEnabled(enabled) {
    api(BASE_URL + '/api/settings/set', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'companion.enabled', value: enabled }),
    }).catch(() => {});
}

// ═════════════════════════════════════════════════════════════════
//  Companion action handler (from palette)
// ═════════════════════════════════════════════════════════════════

/**
 * _onCompanionAction(e)
 * Handles 'companion:action' custom events dispatched from palette buttons
 * or other parts of the UI.
 *
 * @param {CustomEvent} e - Event with e.detail.action
 */
export function _onCompanionAction(e) {
    const { action } = e.detail || {};
    switch (action) {
        case 'mute':
            const newMicState = !getVoiceInputEnabled();
            _applyVoiceInput(newMicState, { persist: true, toast: false });
            _updatePaletteStates();
            showToast(newMicState ? 'Mic on' : 'Mic muted', 'info');
            break;

        case 'tts-toggle':
            const newTtsState = !getVoiceOutputEnabled();
            _applyVoiceOutput(newTtsState, { persist: true, toast: false });
            _updatePaletteStates();
            showToast(newTtsState ? 'TTS on' : 'TTS off', 'info');
            break;

        case 'close':
            disableCompanionMode();
            break;

        case 'settings':
            // Switch to settings tab with companion section focused
            document.dispatchEvent(new CustomEvent('switch-tab', { detail: { tab: 'settings', section: 'Character' } }));
            break;
    }
}

// ═════════════════════════════════════════════════════════════════
//  WS disconnect / reconnect handling
// ═════════════════════════════════════════════════════════════════

let _isDisconnected = false;

function _onWsDisconnected() {
    if (!_companionEnabled) return;
    _isDisconnected = true;

    // Show toast and disconnected indicator on overlay
    showToast('Connection lost', 'warning');
    showDisconnectedIndicator();
}

function _onWsReconnected() {
    if (!_companionEnabled) {
        _isDisconnected = false;
        return;
    }
    _isDisconnected = false;

    // Hide disconnected indicator
    hideDisconnectedIndicator();

    // Re-enable voice/STT on reconnect
    if (getVoiceInputEnabled()) {
        _applyVoiceInput(true, { persist: false, toast: false });
    }
    if (getVoiceOutputEnabled()) {
        _applyVoiceOutput(true, { persist: false, toast: false });
    }

    // Refresh palette states
    _updatePaletteStates();

    showToast('Reconnected', 'success');
}

// ═════════════════════════════════════════════════════════════════
//  TTS playback indicator (called from ws.js or tts.js)
// ═════════════════════════════════════════════════════════════════

export function setCompanionTtsPlaying(playing) {
    updateTtsIndicator(playing);
}

/**
 * Called when companion WebSocket message "companion" type arrives
 * (proactive companion messages).
 */
export function handleCompanionWSMessage(data) {
    // Currently companion messages are displayed as assistant messages in chat.
    // In overlay mode we could optionally display them as floating text.
    console.debug('[Companion] Received proactive message:', data.content);
}

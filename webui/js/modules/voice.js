/**
 * voice.js — Voice input/output management
 */
import { BASE_URL } from './config.js';
import { api } from './api-client.js';
import { showToast, _getNestedValue } from './utils.js';
import {
    getVoiceInputEnabled, setVoiceInputEnabled,
    getVoiceOutputEnabled, setVoiceOutputEnabled,
    getWs,
} from './state.js';
import { getSettings } from './state.js';

let browserSpeechRec = null;
let browserSpeechRestartTimer = null;
let _voiceToggleListenersAttached = false;

export function isBrowserStt() {
    const el = document.getElementById('stt-engine');
    if (el) return el.value === 'browser';
    return (_getNestedValue(getSettings(), 'voice.stt_engine') || 'browser') === 'browser';
}

/**
 * Destroy the current browserSpeechRec and create a fresh instance.
 * This is necessary because the SpeechRecognition API doesn't allow
 * calling .start() again after certain error states.
 */
function _destroyBrowserSpeechRec() {
    if (browserSpeechRec) {
        try {
            browserSpeechRec.onresult = null;
            browserSpeechRec.onerror = null;
            browserSpeechRec.onend = null;
            browserSpeechRec.stop();
        } catch (_) {}
        browserSpeechRec = null;
    }
}

export function startBrowserSpeechRec() {
    // Always destroy existing instance first to avoid stale listeners
    _destroyBrowserSpeechRec();

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        showToast('Speech Recognition not supported in this browser. Try Chrome.', 'danger');
        console.error('Browser STT: SpeechRecognition API not available');
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
        if (finalText.trim()) {
            // Race condition fix: import tts flush inline to stop any playing audio
            // before the backend processes the new user message
            import('./tts.js').then(({ flushTTSQueue }) => {
                flushTTSQueue();
            }).catch(() => {});

            const ws = getWs();
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'user_message', text: finalText.trim() }));
            }
        }
    };

    browserSpeechRec.onerror = (event) => {
        console.warn('Browser SpeechRecognition error:', event.error);
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
            showToast('Microphone access denied. Check browser permissions.', 'danger');
            _destroyBrowserSpeechRec();
        } else if (event.error === 'aborted') {
            // Ignore — normal during stop/restart
        } else if (event.error === 'no-speech') {
            // Ignore — user was just silent
        } else if (event.error === 'network') {
            showToast('Speech recognition network error. Retrying...', 'danger');
            // Don't destroy — onend will restart via fresh instance
        } else {
            // For recoverable errors (audio-capture, etc.), don't destroy here.
            // Let onend handle restart to ensure browser STT recovers after errors.
            console.warn(`Browser STT recoverable error: ${event.error}`);
        }
    };

    browserSpeechRec.onend = () => {
        if (getVoiceInputEnabled() && isBrowserStt()) {
            browserSpeechRestartTimer = setTimeout(() => {
                browserSpeechRestartTimer = null;
                if (getVoiceInputEnabled() && isBrowserStt()) {
                    try {
                        // Always create fresh instance for reliability
                        startBrowserSpeechRec();
                    } catch (e) {
                        console.warn('Browser SpeechRecognition restart failed:', e);
                    }
                }
            }, 300);
        }
    };

    try {
        browserSpeechRec.start();
        console.log('Browser SpeechRecognition started');
    } catch (e) {
        console.warn('Browser SpeechRecognition start failed:', e);
        // Clear reference so onend won't try to restart a broken instance
        browserSpeechRec = null;
    }
}

export function stopBrowserSpeechRec() {
    if (browserSpeechRestartTimer) {
        clearTimeout(browserSpeechRestartTimer);
        browserSpeechRestartTimer = null;
    }
    _destroyBrowserSpeechRec();
}

/**
 * Reset browser STT on WS disconnect. Does NOT re-enable voice input.
 */
export function resetBrowserStt() {
    stopBrowserSpeechRec();
}

export function _applyVoiceInput(enabled, { persist = false, toast = false } = {}) {
    setVoiceInputEnabled(enabled);
    const toggle = document.getElementById('voice-input-toggle');
    const toggleSettings = document.getElementById('voice-input-toggle-settings');
    if (toggle) {
        toggle.querySelector('.material-icons-round').textContent = enabled ? 'mic' : 'mic_off';
        toggle.classList.toggle('active', enabled);
    }
    if (toggleSettings) toggleSettings.checked = enabled;

    if (enabled && isBrowserStt()) {
        startBrowserSpeechRec();
    } else if (!enabled && isBrowserStt()) {
        stopBrowserSpeechRec();
    }
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'command', command: enabled ? 'voice_input_on' : 'voice_input_off' }));
    }
    if (persist) {
        api(BASE_URL + '/api/settings/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: 'ui.voice_input', value: enabled })
        });
    }
    if (toast) showToast(enabled ? 'Voice input on' : 'Voice input off');
}

export function _applyVoiceOutput(enabled, { persist = false, toast = false } = {}) {
    setVoiceOutputEnabled(enabled);
    const toggle = document.getElementById('voice-output-toggle');
    const toggleSettings = document.getElementById('voice-output-toggle-settings');
    if (toggle) {
        toggle.querySelector('.material-icons-round').textContent = enabled ? 'volume_up' : 'volume_off';
        toggle.classList.toggle('active', enabled);
    }
    if (toggleSettings) toggleSettings.checked = enabled;
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'command', command: enabled ? 'voice_output_on' : 'voice_output_off' }));
    }
    if (persist) {
        api(BASE_URL + '/api/settings/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: 'ui.voice_output', value: enabled })
        });
    }
    if (toast) showToast(enabled ? 'Voice output on' : 'Voice output off');
}

// Called by orchestrator to wire up toggle event listeners
export function initVoiceToggles() {
    // Guard: prevent duplicate listener attachment (memory leak fix)
    if (_voiceToggleListenersAttached) return;
    _voiceToggleListenersAttached = true;

    const voiceInputToggle = document.getElementById('voice-input-toggle');
    const voiceOutputToggle = document.getElementById('voice-output-toggle');
    const voiceInputToggleSettings = document.getElementById('voice-input-toggle-settings');
    const voiceOutputToggleSettings = document.getElementById('voice-output-toggle-settings');

    if (voiceInputToggle) {
        voiceInputToggle.addEventListener('click', () => _applyVoiceInput(!getVoiceInputEnabled(), { persist: true, toast: true }));
    }
    if (voiceOutputToggle) {
        voiceOutputToggle.addEventListener('click', () => _applyVoiceOutput(!getVoiceOutputEnabled(), { persist: false, toast: true }));
    }
    if (voiceInputToggleSettings) {
        voiceInputToggleSettings.addEventListener('change', () => _applyVoiceInput(voiceInputToggleSettings.checked, { toast: true }));
    }
    if (voiceOutputToggleSettings) {
        voiceOutputToggleSettings.addEventListener('change', () => _applyVoiceOutput(voiceOutputToggleSettings.checked, { persist: true, toast: true }));
    }
}

export function updateVoiceState(state) {
    const bars = document.getElementById('voice-bars');
    if (bars) {
        bars.className = 'voice-bars';
        if (state === 'recording' || state === 'speaking') {
            bars.classList.add('active');
        }
    }
    if (_updateVoiceStatus) {
        if (state === 'recording') _updateVoiceStatus('listening');
        else if (state === 'speaking') _updateVoiceStatus('speaking');
        else _updateVoiceStatus('ready');
    }
}

let _updateVoiceStatus = null;
export function setVoiceStatusCallback(fn) { _updateVoiceStatus = fn; }

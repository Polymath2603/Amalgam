/**
 * tts.js — Text-to-Speech queue and audio playback
 */
import { showToast } from './utils.js';
import {
    getAudioContext, setAudioContext,
    getCurrentAudioSource, setCurrentAudioSource,
    getIsPlayingTTS, setIsPlayingTTS,
    getTtsQueue, setTtsQueue,
    getTtsQueuePlaying, setTtsQueuePlaying,
    getTtsFlushRequested, setTtsFlushRequested,
    getSpeakingMsgId, setSpeakingMsgId,
    getAvatarRenderer, getAvatarPreviewRenderer,
} from './state.js';

// These will be set by the orchestrator after all modules are initialized
let _setStatus = () => {};
let _updateSpeakButtons = () => {};

// TTS playback timeout (30s max per audio clip)
const TTS_PLAYBACK_TIMEOUT_MS = 30000;

export function setTtsCallbacks({ setStatus, updateSpeakButtons }) {
    _setStatus = setStatus;
    _updateSpeakButtons = updateSpeakButtons;
}

export function ensureAudioContext() {
    let ctx = getAudioContext();
    if (!ctx || ctx.state === 'closed') {
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        setAudioContext(ctx);
    }
    if (ctx.state === 'suspended') {
        ctx.resume().catch(e => console.warn('AudioContext resume failed:', e));
    }
    return ctx;
}

/**
 * Stop and clean up the current audio source, if any.
 */
function _stopCurrentAudio() {
    const src = getCurrentAudioSource();
    if (src) {
        try {
            src.onended = null;
            src.stop();
        } catch (_) {}
        setCurrentAudioSource(null);
    }
    const av = getAvatarRenderer();
    if (av) {
        try { av.stopLipSync(); } catch (_) {}
        if (av._idleManager) av._idleManager.deactivate();
    }
    const avPrev = getAvatarPreviewRenderer();
    if (avPrev) {
        try { avPrev.stopLipSync(); } catch (_) {}
    }
}

export function processTTSQueue() {
    if (getTtsQueuePlaying() || getTtsQueue().length === 0) return;
    setTtsQueuePlaying(true);

    const q = getTtsQueue();
    q.sort((a, b) => a.idx - b.idx);
    const item = q.shift();
    setTtsQueue(q);
    playTTSAudio(item.audio, item.duration, item.visemeSchedule, () => {
        if (getTtsFlushRequested()) {
            setTtsFlushRequested(false);
            setTtsQueue([]);
            setTtsQueuePlaying(false);
            setIsPlayingTTS(false);
            setSpeakingMsgId(null);
            _setStatus('ready');
            _updateSpeakButtons();
            _stopCurrentAudio();
            return;
        }
        setTtsQueuePlaying(false);

        if (getTtsQueue().length > 0) {
            processTTSQueue();
        } else {
            setIsPlayingTTS(false);
            setSpeakingMsgId(null);
            _setStatus('ready');
            _updateSpeakButtons();
            _stopCurrentAudio();
        }
    });
}

export function flushTTSQueue() {
    setTtsFlushRequested(true);
    _stopCurrentAudio();
    setIsPlayingTTS(false);
    setTtsQueuePlaying(false);
    setTtsQueue([]);
    setSpeakingMsgId(null);
    setTtsFlushRequested(false); // Clear flag so future processTTSQueue() calls work
    _updateSpeakButtons();
}

export async function playTTSAudio(base64Wav, duration, visemeSchedule, onComplete) {
    let playbackTimer = null;
    try {
        const ctx = ensureAudioContext();
        const avatarRenderer = getAvatarRenderer();
        const avatarPreviewRenderer = getAvatarPreviewRenderer();

        let binaryStr;
        try {
            binaryStr = atob(base64Wav);
        } catch (e) {
            console.warn('TTS: malformed base64, skipping');
            if (typeof onComplete === 'function') onComplete();
            return;
        }
        const bytes = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) {
            bytes[i] = binaryStr.charCodeAt(i);
        }

        let audioBuffer;
        try {
            audioBuffer = await ctx.decodeAudioData(bytes.buffer);
        } catch (e) {
            console.warn('TTS: malformed audio data, skipping');
            if (typeof onComplete === 'function') onComplete();
            return;
        }

        // Honor flush requested during decode
        if (getTtsFlushRequested()) {
            if (typeof onComplete === 'function') onComplete();
            return;
        }

        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;

        const analyser = ctx.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        source.connect(ctx.destination);
        setCurrentAudioSource(source);
        setIsPlayingTTS(true);
        _updateSpeakButtons();

        if (avatarRenderer?._idleManager) avatarRenderer._idleManager.activate();

        _setStatus('speaking');

        if (avatarRenderer) avatarRenderer.startLipSync(ctx, analyser, visemeSchedule);
        if (avatarPreviewRenderer) avatarPreviewRenderer.startLipSync(ctx, analyser, visemeSchedule);

        let completed = false;
        source.onended = () => {
            if (completed) return; // Prevent double-firing
            completed = true;
            clearTimeout(playbackTimer);
            setIsPlayingTTS(false);
            setCurrentAudioSource(null);
            setSpeakingMsgId(null);
            _updateSpeakButtons();
            try {
                if (avatarRenderer) avatarRenderer.stopLipSync();
                if (avatarPreviewRenderer) avatarPreviewRenderer.stopLipSync();
                if (avatarRenderer?._idleManager) avatarRenderer._idleManager.deactivate();
            } catch (e) {
                console.warn('TTS avatar cleanup error:', e);
            }
            if (onComplete) onComplete();
        };

        // Safety timeout: if onended never fires, force completion
        playbackTimer = setTimeout(() => {
            if (!completed) {
                console.warn(`TTS: playback timeout after ${TTS_PLAYBACK_TIMEOUT_MS}ms`);
                completed = true;
                try { source.stop(); } catch (_) {}
                setIsPlayingTTS(false);
                setCurrentAudioSource(null);
                setSpeakingMsgId(null);
                _updateSpeakButtons();
                try {
                    if (avatarRenderer) avatarRenderer.stopLipSync();
                    if (avatarPreviewRenderer) avatarPreviewRenderer.stopLipSync();
                    if (avatarRenderer?._idleManager) avatarRenderer._idleManager.deactivate();
                } catch (_) {}
                if (onComplete) onComplete();
            }
        }, TTS_PLAYBACK_TIMEOUT_MS);

        source.start(0);
    } catch (err) {
        console.error('TTS playback error:', err);
        clearTimeout(playbackTimer);
        setIsPlayingTTS(false);
        setCurrentAudioSource(null);
        setSpeakingMsgId(null);
        _updateSpeakButtons();
        const av = getAvatarRenderer();
        if (av) {
            try { av.setMouthOpen(0); av.stopLipSync(); } catch (_) {}
        }
        if (onComplete) onComplete();
    }
}

// Audio context cleanup on page unload
window.addEventListener('beforeunload', () => {
    const src = getCurrentAudioSource();
    if (src) {
        try {
            src.onended = null;
            src.stop();
        } catch (_) {}
    }
    const ctx = getAudioContext();
    if (ctx && ctx.state !== 'closed') {
        ctx.close().catch(() => {});
    }
});

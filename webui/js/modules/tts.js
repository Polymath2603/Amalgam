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

export function setTtsCallbacks({ setStatus, updateSpeakButtons }) {
    _setStatus = setStatus;
    _updateSpeakButtons = updateSpeakButtons;
}

export function ensureAudioContext() {
    let ctx = getAudioContext();
    if (!ctx) {
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        setAudioContext(ctx);
    }
    if (ctx.state === 'suspended') {
        ctx.resume();
    }
    return ctx;
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
            _setStatus('ready');
            const av = getAvatarRenderer();
            if (av?._idleManager) av._idleManager.deactivate();
            return;
        }
        setTtsQueuePlaying(false);

        if (getTtsQueue().length > 0) {
            processTTSQueue();
        } else {
            setIsPlayingTTS(false);
            _setStatus('ready');
            const av = getAvatarRenderer();
            if (av?._idleManager) av._idleManager.deactivate();
        }
    });
}

export function flushTTSQueue() {
    setTtsFlushRequested(true);
    const src = getCurrentAudioSource();
    if (src) {
        try {
            src.onended = null; // Prevent onended from firing after flush
            src.stop();
        } catch (_) {}
        setCurrentAudioSource(null);
    }
    setIsPlayingTTS(false);
    setTtsQueuePlaying(false);
    setTtsQueue([]);
    setTtsFlushRequested(false); // Clear flag so future processTTSQueue() calls work
    _updateSpeakButtons();

    const av = getAvatarRenderer();
    if (av?._idleManager) av._idleManager.deactivate();
}

export async function playTTSAudio(base64Wav, duration, visemeSchedule, onComplete) {
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

        // Check if a flush was requested while we were decoding
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
            setIsPlayingTTS(false);
            setCurrentAudioSource(null);
            setSpeakingMsgId(null);
            _updateSpeakButtons();
            if (avatarRenderer) avatarRenderer.stopLipSync();
            if (avatarPreviewRenderer) avatarPreviewRenderer.stopLipSync();
            if (avatarRenderer?._idleManager) avatarRenderer._idleManager.deactivate();
            if (onComplete) onComplete();
        };

        source.start(0);
    } catch (err) {
        console.error('TTS playback error:', err);
        setIsPlayingTTS(false);
        setCurrentAudioSource(null);
        const av = getAvatarRenderer();
        if (av) av.setMouthOpen(0);
        if (onComplete) onComplete();
    }
}

// Audio context cleanup on page unload
window.addEventListener('beforeunload', () => {
    const ctx = getAudioContext();
    if (ctx && ctx.state !== 'closed') ctx.close();
});

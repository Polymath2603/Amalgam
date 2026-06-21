/**
 * state.js — Shared mutable application state
 *
 * ES module `export let` bindings are live only when accessed via `import * as ns`.
 * Destructured imports capture a snapshot. So we export getter/setter pairs instead.
 * All modules call getXxx() / setXxx() for any shared mutable state.
 */

// --- DOM references (set during init) ---
let _chatMessages = null;
let _chatInput = null;
let _statusDot = null;
let _statusText = null;

export function getChatMessages() { return _chatMessages; }
export function getChatInput() { return _chatInput; }
export function getStatusDot() { return _statusDot; }
export function getStatusText() { return _statusText; }

export function setDomRefs({ chatMessages, chatInput, statusDot, statusText }) {
    if (chatMessages !== undefined) _chatMessages = chatMessages;
    if (chatInput !== undefined) _chatInput = chatInput;
    if (statusDot !== undefined) _statusDot = statusDot;
    if (statusText !== undefined) _statusText = statusText;
}

// --- Settings ---
let _settingsCache = null;
export function getSettings() { return _settingsCache; }
export function setSettingsCache(s) { _settingsCache = s; }

// --- WebSocket ---
let _ws = null;
export function getWs() { return _ws; }
export function setWs(v) { _ws = v; }

// --- Chat state ---
let _currentAssistantMessage = null;
let _lastUserMessage = null;
let _currentSessionId = null;
let _sessionHasMessages = false;

export function getCurrentAssistantMessage() { return _currentAssistantMessage; }
export function setCurrentAssistantMessage(v) { _currentAssistantMessage = v; }
export function getLastUserMessage() { return _lastUserMessage; }
export function setLastUserMessage(v) { _lastUserMessage = v; }
export function getCurrentSessionId() { return _currentSessionId; }
export function setCurrentSessionId(v) { _currentSessionId = v; }
export function getSessionHasMessages() { return _sessionHasMessages; }
export function setSessionHasMessages(v) { _sessionHasMessages = v; }

// --- Voice ---
let _voiceInputEnabled = false;
let _voiceOutputEnabled = false;
export function getVoiceInputEnabled() { return _voiceInputEnabled; }
export function setVoiceInputEnabled(v) { _voiceInputEnabled = v; }
export function getVoiceOutputEnabled() { return _voiceOutputEnabled; }
export function setVoiceOutputEnabled(v) { _voiceOutputEnabled = v; }

// --- TTS ---
let _audioContext = null;
let _currentAudioSource = null;
let _isPlayingTTS = false;
let _ttsQueue = [];
let _ttsQueuePlaying = false;
let _ttsFlushRequested = false;
let _speakingMsgId = null;

export function getAudioContext() { return _audioContext; }
export function setAudioContext(v) { _audioContext = v; }
export function getCurrentAudioSource() { return _currentAudioSource; }
export function setCurrentAudioSource(v) { _currentAudioSource = v; }
export function getIsPlayingTTS() { return _isPlayingTTS; }
export function setIsPlayingTTS(v) { _isPlayingTTS = v; }
export function getTtsQueue() { return _ttsQueue; }
export function setTtsQueue(v) { _ttsQueue = v; }
export function getTtsQueuePlaying() { return _ttsQueuePlaying; }
export function setTtsQueuePlaying(v) { _ttsQueuePlaying = v; }
export function getTtsFlushRequested() { return _ttsFlushRequested; }
export function setTtsFlushRequested(v) { _ttsFlushRequested = v; }
export function getSpeakingMsgId() { return _speakingMsgId; }
export function setSpeakingMsgId(v) { _speakingMsgId = v; }

/** Reset all voice/TTS state to defaults. Called on WS disconnect or cleanup. */
export function resetVoiceState() {
    _voiceInputEnabled = false;
    _voiceOutputEnabled = false;
    _isPlayingTTS = false;
    _ttsQueue = [];
    _ttsQueuePlaying = false;
    _ttsFlushRequested = false;
    _speakingMsgId = null;
    if (_currentAudioSource) {
        try { _currentAudioSource.onended = null; _currentAudioSource.stop(); } catch (_) {}
        _currentAudioSource = null;
    }
    if (_audioContext && _audioContext.state !== 'closed') {
        try { _audioContext.close(); } catch (_) {}
    }
    _audioContext = null;
}

// --- Avatar ---
let _avatarRenderer = null;
let _avatarPreviewRenderer = null;


export function getAvatarRenderer() { return _avatarRenderer; }
export function setAvatarRenderer(v) { _avatarRenderer = v; }
export function getAvatarPreviewRenderer() { return _avatarPreviewRenderer; }
export function setAvatarPreviewRenderer(v) { _avatarPreviewRenderer = v; }


// --- MCP ---
let _mcpServersCache = [];
export function getMcpServersCache() { return _mcpServersCache; }
export function setMcpServersCache(v) { _mcpServersCache = v; }

// --- Stream buffer ---
export const streamBuffer = new Map();
let _streamBufferTimer = null;
export function getStreamBufferTimer() { return _streamBufferTimer; }
export function setStreamBufferTimer(v) { _streamBufferTimer = v; }

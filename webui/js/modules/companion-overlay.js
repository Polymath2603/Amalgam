/**
 * companion-overlay.js — Full-screen companion overlay controller
 *
 * Manages the overlay DOM, mounts/unmounts the avatar renderer,
 * handles visibility, position/size persistence, and coordinates
 * with the tool palette.
 *
 * Supports:
 *  - Drag via pointer events (desktop) + touch events (mobile)
 *  - Double-click (desktop) & double-tap (mobile) toggle avatar show/hide
 *  - Tab visibility pausing (saves CPU when user switches tabs)
 *  - WS disconnect indicator
 */
import { BASE_URL } from './config.js';
import { api } from './api-client.js';
import { getAvatarRenderer, setAvatarRenderer, getAvatarPreviewRenderer } from './state.js';
import { showToast } from './utils.js';

// --- State ---
let _overlayEl = null;           // #companion-overlay
let _avatarContainer = null;    // #companion-avatar-container
let _paletteEl = null;          // #companion-palette
let _muteIndicator = null;      // #companion-mute-indicator
let _ttsIndicator = null;       // #companion-tts-indicator
let _disconnectedBar = null;    // #companion-disconnected-bar
let _disconnectedText = null;   // #companion-disconnected-text
let _resizeHandle = null;       // .companion-resize-handle
let _isVisible = false;
let _avatarHidden = false;
let _paletteTimer = null;
let _isDragging = false;
let _isResizing = false;
let _dragOffset = { x: 0, y: 0 };
let _resizeStart = { x: 0, y: 0, w: 0, h: 0 };
let _savedPosition = null;      // { x, y } as percentage strings or px
let _savedScale = 1;
let _avatarRendererRef = null;  // reference to the active avatar renderer

// Tab visibility
let _tabVisible = true;
let _renderPaused = false;

// Double-tap detection
let _lastTapTime = 0;

// --- Persistence keys ---
const STORAGE_PREFIX = 'companion_overlay_';
const SETTINGS_POS_X_KEY = 'companion.overlay_position_x';
const SETTINGS_POS_Y_KEY = 'companion.overlay_position_y';
const SETTINGS_SCALE_KEY = 'companion.overlay_scale';
const SETTINGS_LAST_STATE_KEY = 'companion.overlay_last_state';

// --- Initialization ---

/**
 * initOverlay()
 * Called once during app bootstrap. Grabs DOM refs.
 * Does NOT show the overlay — that's done by showOverlay().
 */
export function initOverlay() {
    _overlayEl = document.getElementById('companion-overlay');
    _avatarContainer = document.getElementById('companion-avatar-container');
    _paletteEl = document.getElementById('companion-palette');
    _muteIndicator = document.getElementById('companion-mute-indicator');
    _ttsIndicator = document.getElementById('companion-tts-indicator');
    _disconnectedBar = document.getElementById('companion-disconnected-bar');
    _disconnectedText = document.getElementById('companion-disconnected-text');

    if (!_overlayEl || !_avatarContainer || !_paletteEl) {
        console.warn('[CompanionOverlay] Missing DOM elements');
        return;
    }

    // Create resize handle
    _resizeHandle = document.createElement('div');
    _resizeHandle.className = 'companion-resize-handle';
    _avatarContainer.appendChild(_resizeHandle);

    // Bind global events for drag/resize
    _bindEvents();

    // Tab visibility listener
    document.addEventListener('visibilitychange', _onVisibilityChange);
}

/**
 * showOverlay()
 * Shows the overlay and mounts the avatar renderer canvas into it.
 * Called when companion mode is enabled.
 *
 * @param {Object} options
 * @param {Object} [options.position] - { x: '50%', y: '50%' } saved position
 * @param {number} [options.scale=1] - Saved scale factor
 */
export function showOverlay(options = {}) {
    if (!_overlayEl || _isVisible) return;

    const renderer = getAvatarRenderer();
    if (!renderer) {
        console.warn('[CompanionOverlay] No avatar renderer available');
        return;
    }

    _avatarRendererRef = renderer;

    // Restore saved position/size
    const pos = options.position || _loadPosition();
    const scale = options.scale || _loadScale();

    // Move the avatar canvas from its original container into the overlay
    const canvas = renderer.renderer?.domElement;
    if (canvas && canvas.parentElement !== _avatarContainer) {
        // Detach from original container
        if (canvas.parentElement) {
            canvas.remove();
        }
        _avatarContainer.appendChild(canvas);
    }

    // Position the container
    if (pos) {
        _avatarContainer.style.left = pos.x || '50%';
        _avatarContainer.style.top = pos.y || '50%';
        _avatarContainer.style.transform = `translate(-50%, -50%) scale(${scale})`;
    } else {
        _avatarContainer.style.left = '50%';
        _avatarContainer.style.top = '50%';
        _avatarContainer.style.transform = 'translate(-50%, -50%) scale(1)';
    }
    _savedPosition = pos;
    _savedScale = scale;

    // Re-trigger resize so avatar renderer matches new container size
    if (renderer._onResize) {
        requestAnimationFrame(() => renderer._onResize());
    }

    // Show overlay with fade-in (two-phase to trigger CSS transition)
    _overlayEl.classList.remove('hidden', 'fade-out');
    // Force reflow so the browser registers the element as displayed with opacity 0
    void _overlayEl.offsetWidth;
    _overlayEl.classList.add('fade-in');
    _isVisible = true;

    // Persist last state as companion mode
    _saveLastState('companion');

    // Show palette (starts visible, then auto-hides)
    showPalette();

    // Reset indicators
    updateMuteIndicator(false);
    updateTtsIndicator(false);

    // If tab is hidden, pause render immediately
    if (_tabVisible === false) {
        _pauseRender();
    }
}

/**
 * hideOverlay()
 * Hides the overlay, moves the avatar canvas back to its original container.
 */
export function hideOverlay() {
    if (!_overlayEl || !_isVisible) return;

    // Clear disconnected indicator
    hideDisconnectedIndicator();

    // Resume render if paused so canvas moves back cleanly
    if (_renderPaused) {
        _resumeRender();
    }

    // Fade out then hide
    _overlayEl.classList.remove('fade-in');
    _overlayEl.classList.add('fade-out');
    _isVisible = false;
    _avatarHidden = false;
    hidePalette();
    clearPaletteTimer();

    // Move canvas back to original avatar container after fade completes
    const renderer = getAvatarRenderer();
    if (renderer?.renderer?.domElement) {
        const canvas = renderer.renderer.domElement;
        const originalContainer = document.getElementById('avatar-canvas');
        if (originalContainer && canvas.parentElement !== originalContainer) {
            originalContainer.appendChild(canvas);
            requestAnimationFrame(() => renderer._onResize());
        }
    }

    // After fade animation, add hidden class
    setTimeout(() => {
        if (!_isVisible) {
            _overlayEl.classList.add('hidden');
        }
    }, 300);

    // Persist last state
    _saveLastState('chat');
}

/**
 * toggleOverlay()
 * Convenience toggler.
 */
export function toggleOverlay() {
    if (_isVisible) hideOverlay();
    else showOverlay();
}

export function isOverlayVisible() {
    return _isVisible;
}

// --- Avatar visibility ---

export function toggleAvatarVisibility() {
    _avatarHidden = !_avatarHidden;
    if (_avatarContainer) {
        _avatarContainer.style.display = _avatarHidden ? 'none' : '';
    }
    // Update palette button state
    const btn = _paletteEl?.querySelector('[data-action="show-hide"]');
    if (btn) {
        btn.classList.toggle('active', _avatarHidden);
        btn.querySelector('.material-icons-round').textContent = _avatarHidden ? 'visibility_off' : 'visibility';
        btn.title = _avatarHidden ? 'Show avatar' : 'Hide avatar';
    }
}

// --- Position / Size persistence ---

export function savePosition() {
    _savePosition();
}

function _savePosition() {
    if (!_avatarContainer) return;
    const left = _avatarContainer.style.left;
    const top = _avatarContainer.style.top;
    const transform = _avatarContainer.style.transform;

    // Extract scale from transform
    let scale = 1;
    const scaleMatch = transform?.match(/scale\(([\d.]+)\)/);
    if (scaleMatch) scale = parseFloat(scaleMatch[1]);

    const data = { x: left, y: top, scale };

    // Save to localStorage (fast, for immediate restore)
    try {
        localStorage.setItem(STORAGE_PREFIX + 'position', JSON.stringify(data));
    } catch (_) {}

    // Save to backend settings (persistent across devices)
    _saveSetting(SETTINGS_POS_X_KEY, left).catch(() => {});
    _saveSetting(SETTINGS_POS_Y_KEY, top).catch(() => {});
    _saveSetting(SETTINGS_SCALE_KEY, scale).catch(() => {});

    _savedPosition = { x: left, y: top };
    _savedScale = scale;
}

async function _saveSetting(key, value) {
    try {
        await api(BASE_URL + '/api/settings/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key, value }),
        });
    } catch (_) {}
}

function _loadPosition() {
    try {
        const raw = localStorage.getItem(STORAGE_PREFIX + 'position');
        if (raw) return JSON.parse(raw);
    } catch (_) {}
    return null;
}

function _loadScale() {
    return _savedScale || 1;
}

function _saveLastState(state) {
    try {
        localStorage.setItem(STORAGE_PREFIX + 'last_state', state);
    } catch (_) {}
    _saveSetting(SETTINGS_LAST_STATE_KEY, state).catch(() => {});
}

export function getLastState() {
    try {
        return localStorage.getItem(STORAGE_PREFIX + 'last_state') || 'chat';
    } catch (_) {
        return 'chat';
    }
}

// --- Palette visibility ---

export function showPalette() {
    if (!_paletteEl) return;
    // Two-phase to trigger CSS transition
    _paletteEl.classList.remove('hidden');
    void _paletteEl.offsetWidth;
    _paletteEl.classList.add('visible');
    _startPaletteAutoHide();
}

export function hidePalette() {
    if (!_paletteEl) return;
    _paletteEl.classList.remove('visible');
    _paletteEl.classList.add('hidden');
}

function _startPaletteAutoHide() {
    clearPaletteTimer();
    _paletteTimer = setTimeout(() => {
        hidePalette();
    }, 30000);
}

export function clearPaletteTimer() {
    if (_paletteTimer) {
        clearTimeout(_paletteTimer);
        _paletteTimer = null;
    }
}

function _resetPaletteTimer() {
    showPalette(); // This restarts the timer
}

// --- Indicator updates ---

export function updateMuteIndicator(muted) {
    if (!_muteIndicator) return;
    if (muted) {
        _muteIndicator.classList.remove('hidden');
    } else {
        _muteIndicator.classList.add('hidden');
    }
}

export function updateTtsIndicator(playing) {
    if (!_ttsIndicator) return;
    if (playing) {
        _ttsIndicator.classList.remove('hidden');
    } else {
        _ttsIndicator.classList.add('hidden');
    }
}

// --- WS disconnect / reconnect indicator ---

export function showDisconnectedIndicator() {
    if (!_overlayEl || !_isVisible) return;
    if (_disconnectedBar) _disconnectedBar.style.display = '';
    if (_disconnectedText) {
        _disconnectedText.classList.add('visible');
        _disconnectedText.style.display = '';
    }
    showToast('Connection lost', 'warning');
}

export function hideDisconnectedIndicator() {
    if (_disconnectedBar) _disconnectedBar.style.display = 'none';
    if (_disconnectedText) {
        _disconnectedText.classList.remove('visible');
        _disconnectedText.style.display = 'none';
    }
}

// --- Tab visibility handling ---

function _onVisibilityChange() {
    _tabVisible = !document.hidden;
    if (!_isVisible) return;

    if (!_tabVisible) {
        // Tab hidden — pause render loop
        _pauseRender();
    } else {
        // Tab visible again — resume render loop
        _resumeRender();
    }
}

function _pauseRender() {
    if (_renderPaused || !_avatarRendererRef) return;
    _renderPaused = true;

    if (_avatarRendererRef._rafId) {
        cancelAnimationFrame(_avatarRendererRef._rafId);
        _avatarRendererRef._rafId = null;
        console.debug('[CompanionOverlay] Render loop paused (tab hidden)');
    }
}

function _resumeRender() {
    if (!_renderPaused || !_avatarRendererRef) return;
    _renderPaused = false;

    // Restart the animate loop
    if (typeof _avatarRendererRef._animate === 'function') {
        // Reset the clock to avoid huge delta
        if (_avatarRendererRef.clock) {
            _avatarRendererRef.clock.start();
        }
        _avatarRendererRef._animate();
        console.debug('[CompanionOverlay] Render loop resumed (tab visible)');
    }
}

// --- Drag / Resize event binding ---

function _bindEvents() {
    // Palette auto-hide reset on mousemove over overlay
    document.addEventListener('mousemove', _onMouseMove, { passive: true });
    document.addEventListener('touchstart', _resetPaletteTimer, { passive: true });

    // Drag: pointerdown on avatar container (not on resize handle)
    _avatarContainer?.addEventListener('pointerdown', _onDragStart);
    // Resize: pointerdown on resize handle
    _resizeHandle?.addEventListener('pointerdown', _onResizeStart);

    // Touch drag (mobile) — handled by pointer events but also bind for fallback
    _avatarContainer?.addEventListener('touchstart', _onTouchDragStart, { passive: true });

    // Scroll to resize (desktop)
    _avatarContainer?.addEventListener('wheel', _onScrollResize, { passive: true });

    // Pinch to resize (mobile)
    _avatarContainer?.addEventListener('gesturestart', (e) => e.preventDefault(), { passive: false });
    _avatarContainer?.addEventListener('gesturechange', _onPinchResize, { passive: true });

    // Double-click/tap: toggle avatar visibility
    _avatarContainer?.addEventListener('dblclick', _onDoubleClick);
    _avatarContainer?.addEventListener('touchend', _onTouchEnd);

    // Palette button handlers (delegated)
    _paletteEl?.addEventListener('click', _onPaletteAction);
}

let _lastMouseMove = 0;
function _onMouseMove() {
    const now = Date.now();
    if (now - _lastMouseMove > 1000) { // Throttle to 1s
        _lastMouseMove = now;
        _resetPaletteTimer();
    }
}

function _onDragStart(e) {
    if (e.target.classList.contains('companion-resize-handle')) return;
    if (_isResizing) return;
    if (_isDragging) return;

    _isDragging = true;
    const rect = _avatarContainer.getBoundingClientRect();
    _dragOffset.x = e.clientX - rect.left;
    _dragOffset.y = e.clientY - rect.top;
    _avatarContainer.classList.add('dragging');

    document.addEventListener('pointermove', _onDragMove);
    document.addEventListener('pointerup', _onDragEnd);
    e.preventDefault();
}

function _onDragMove(e) {
    if (!_isDragging) return;
    const newLeft = e.clientX - _dragOffset.x;
    const newTop = e.clientY - _dragOffset.y;
    // Switch from percentage to px positioning during drag
    _avatarContainer.style.left = newLeft + 'px';
    _avatarContainer.style.top = newTop + 'px';
    _avatarContainer.style.transform = _avatarContainer.style.transform.replace(/translate\([^)]+\)/, '');
}

function _onDragEnd() {
    _isDragging = false;
    _avatarContainer?.classList.remove('dragging');
    document.removeEventListener('pointermove', _onDragMove);
    document.removeEventListener('pointerup', _onDragEnd);
    _savePosition();
}

// --- Touch drag (mobile fallback) ---

function _onTouchDragStart(e) {
    if (e.target.classList.contains('companion-resize-handle')) return;
    if (_isResizing) return;
    if (_isDragging) return;

    const touch = e.touches[0];
    if (!touch) return;

    _isDragging = true;
    const rect = _avatarContainer.getBoundingClientRect();
    _dragOffset.x = touch.clientX - rect.left;
    _dragOffset.y = touch.clientY - rect.top;
    _avatarContainer.classList.add('dragging');

    document.addEventListener('touchmove', _onTouchDragMove, { passive: false });
    document.addEventListener('touchend', _onTouchDragEnd);
}

function _onTouchDragMove(e) {
    if (!_isDragging) return;
    e.preventDefault();
    const touch = e.touches[0];
    if (!touch) return;
    const newLeft = touch.clientX - _dragOffset.x;
    const newTop = touch.clientY - _dragOffset.y;
    _avatarContainer.style.left = newLeft + 'px';
    _avatarContainer.style.top = newTop + 'px';
    _avatarContainer.style.transform = _avatarContainer.style.transform.replace(/translate\([^)]+\)/, '');
}

function _onTouchDragEnd() {
    _isDragging = false;
    _avatarContainer?.classList.remove('dragging');
    document.removeEventListener('touchmove', _onTouchDragMove);
    document.removeEventListener('touchend', _onTouchDragEnd);
    _savePosition();
}

// --- Double-tap detection (mobile) ---

function _onTouchEnd(e) {
    // Only handle single-finger taps
    if (e.changedTouches.length !== 1) return;
    const now = Date.now();
    const timeSince = now - _lastTapTime;
    _lastTapTime = now;

    if (timeSince < 300 && timeSince > 0) {
        // Double-tap detected
        e.preventDefault();
        toggleAvatarVisibility();
    }
}

// --- Resize ---

function _onResizeStart(e) {
    e.stopPropagation();
    _isResizing = true;
    const rect = _avatarContainer.getBoundingClientRect();
    _resizeStart = { x: e.clientX, y: e.clientY, w: rect.width, h: rect.height };

    document.addEventListener('pointermove', _onResizeMove);
    document.addEventListener('pointerup', _onResizeEnd);
    e.preventDefault();
}

function _onResizeMove(e) {
    if (!_isResizing) return;
    const dx = e.clientX - _resizeStart.x;
    const dy = e.clientY - _resizeStart.y;
    const newW = Math.max(200, _resizeStart.w + dx);
    const newH = Math.max(300, _resizeStart.h + dy);
    _avatarContainer.style.width = newW + 'px';
    _avatarContainer.style.height = newH + 'px';
}

function _onResizeEnd() {
    _isResizing = false;
    document.removeEventListener('pointermove', _onResizeMove);
    document.removeEventListener('pointerup', _onResizeEnd);
    // Trigger avatar renderer resize
    if (_avatarRendererRef?._onResize) {
        requestAnimationFrame(() => _avatarRendererRef._onResize());
    }
    _savePosition();
}

// Scroll to resize (desktop)
function _onScrollResize(e) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.05 : 0.05;
    _savedScale = Math.max(0.3, Math.min(3, _savedScale + delta));
    _avatarContainer.style.transform = _avatarContainer.style.transform.replace(
        /scale\([\d.]+\)/,
        `scale(${_savedScale})`
    );
    _savePosition();
}

// Pinch to resize (mobile)
function _onPinchResize(e) {
    e.preventDefault();
    // e.scale is the pinch scale factor (gesturechange event)
    const newScale = Math.max(0.3, Math.min(3, e.scale));
    _avatarContainer.style.transform = _avatarContainer.style.transform.replace(
        /scale\([\d.]+\)/,
        `scale(${newScale})`
    );
}

// Double-click: toggle fullscreen avatar
function _onDoubleClick() {
    if (_avatarContainer.style.width === '100vw' || _avatarContainer.style.width === '100%') {
        // Restore saved size
        _avatarContainer.style.width = '';
        _avatarContainer.style.height = '';
    } else {
        // Enter fullscreen
        _avatarContainer.style.left = '0';
        _avatarContainer.style.top = '0';
        _avatarContainer.style.width = '100vw';
        _avatarContainer.style.height = '100vh';
        _avatarContainer.style.transform = 'none';
    }
    if (_avatarRendererRef?._onResize) {
        requestAnimationFrame(() => _avatarRendererRef._onResize());
    }
    _savePosition();
}

// --- Palette action dispatch ---

function _onPaletteAction(e) {
    const btn = e.target.closest('.palette-btn');
    if (!btn) return;
    const action = btn.dataset.action;

    switch (action) {
        case 'show-hide':
            toggleAvatarVisibility();
            break;
        case 'mute':
        case 'tts-toggle':
        case 'close':
        case 'settings':
            // Dispatch custom event — companion.js or app.js handles the actual toggle
            document.dispatchEvent(new CustomEvent('companion:action', { detail: { action } }));
            break;
    }
}

// --- Cleanup ---

export function destroyOverlay() {
    hideOverlay();
    clearPaletteTimer();
    document.removeEventListener('mousemove', _onMouseMove);
    document.removeEventListener('touchstart', _resetPaletteTimer);
    document.removeEventListener('visibilitychange', _onVisibilityChange);
    // Clean up drag/resize listeners
    if (_avatarContainer) {
        _avatarContainer.removeEventListener('pointerdown', _onDragStart);
        _avatarContainer.removeEventListener('touchstart', _onTouchDragStart);
        _avatarContainer.removeEventListener('wheel', _onScrollResize);
        _avatarContainer.removeEventListener('dblclick', _onDoubleClick);
        _avatarContainer.removeEventListener('touchend', _onTouchEnd);
    }
    if (_resizeHandle) {
        _resizeHandle.removeEventListener('pointerdown', _onResizeStart);
    }
    document.removeEventListener('pointermove', _onDragMove);
    document.removeEventListener('pointerup', _onDragEnd);
    document.removeEventListener('touchmove', _onTouchDragMove);
    document.removeEventListener('touchend', _onTouchDragEnd);
    document.removeEventListener('pointermove', _onResizeMove);
    document.removeEventListener('pointerup', _onResizeEnd);
}

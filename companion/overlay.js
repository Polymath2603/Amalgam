/**
 * overlay.js — Full-screen transparent VRM overlay for companion mode.
 *
 * Three.js renders VRM on green bg -> chroma-key -> putImageData to
 * full-screen 2D canvas (alpha works in QtWebEngine).
 *
 * Idle detection, companion message display, expression blending,
 * lip-sync visemes, and WebSocket keepalive.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

// ── Config ──────────────────────────────────────────────────────────

// WS port injected by launcher.py via overlay.html URL query param
const _WS_PORT = (typeof _wsPort !== 'undefined' && _wsPort) ? _wsPort : '8000';
const BACKEND_WS = `ws://127.0.0.1:${_WS_PORT}`;
const RECONNECT_DELAYS = [500, 1000, 2000, 5000, 10000, 30000];
const VRM_W = 280, VRM_H = 420, CHROMA_TOL = 55;
const IDLE_MS = 5 * 60 * 1000;
const AWAY_MS = 2 * 60 * 1000;
const HEARTBEAT_MS = 15000;
const BLEND_EXPR = 0.08;
const BLEND_MOUTH = 0.25;
const BUBBLE_MS = 10000;

// ── Three.js State ──────────────────────────────────────────────────

let renderer, scene, camera, vrm, mixer, clock = new THREE.Clock();
let mouthVal = 0, mouthAa = 0, mouthOh = 0;
let muted = false;
let animId = null, hideTimer = null;
let dispCanvas, dispCtx, chromaBuf, chromaCtx;

// ── Companion State ─────────────────────────────────────────────────

let ws = null, wsRetry = 0, wsTimer = null, pingInterval = null;
let bubbleTimer = null;
let idleTimer = null, awayTimer = null;
let isIdle = false, isAway = false;
let companionEnabled = false;

// ── Expression Blending ─────────────────────────────────────────────

let _currentExpr = 'neutral', _targetExpr = 'neutral';
let _exprWeights = {}, _exprBlending = false;

// ── DOM Refs ────────────────────────────────────────────────────────

const statusEl = document.getElementById('status');
const ctrlEl = document.getElementById('controls');
const muteBtn = document.getElementById('btn-mute');
const closeBtn = document.getElementById('btn-close');
const bubbleEl = document.getElementById('companion-bubble');
const bubbleTextEl = bubbleEl?.querySelector('.bubble-text');

// ====================================================================
//  BOOT
// ====================================================================

async function boot() {
    initThree();
    await loadAvatar();
    clock.start();
    animFrame();
    startIdleDetection();
    connectWS();
    showCtrl();
}

boot().catch(e => {
    console.error('[Overlay]', e);
    if (statusEl) statusEl.textContent = 'error';
});

// ====================================================================
//  THREE.JS SETUP
// ====================================================================

function initThree() {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0, 1, 0);

    camera = new THREE.PerspectiveCamera(22, VRM_W / VRM_H, 0.1, 20);
    camera.position.set(0, 1.35, 2.8);
    camera.lookAt(0, 1.2, 0);

    renderer = new THREE.WebGLRenderer({ alpha: false, antialias: true });
    renderer.setSize(VRM_W, VRM_H);
    renderer.setPixelRatio(1);
    renderer.setClearColor(0, 1, 0, 1);
    renderer.domElement.style.cssText = 'position:fixed;top:-9999px;left:-9999px';
    document.body.appendChild(renderer.domElement);

    dispCanvas = document.createElement('canvas');
    dispCanvas.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh';
    document.getElementById('avatar-canvas').appendChild(dispCanvas);
    dispCtx = dispCanvas.getContext('2d', { alpha: true });
    resizeDisp();

    chromaBuf = document.createElement('canvas');
    chromaBuf.width = VRM_W;
    chromaBuf.height = VRM_H;
    chromaCtx = chromaBuf.getContext('2d', { willReadFrequently: true });

    window.addEventListener('resize', resizeDisp);

    const key = new THREE.DirectionalLight(0xffffff, 1.2);
    key.position.set(0.8, 1.5, 1.0);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x8888ff, 0.3);
    fill.position.set(-0.5, 0.5, 1.5);
    scene.add(fill);
    scene.add(new THREE.AmbientLight(0xffffff, 0.4));
}

function resizeDisp() {
    dispCanvas.width = window.innerWidth;
    dispCanvas.height = window.innerHeight;
}


// ====================================================================
//  AVATAR LOADING
// ====================================================================

async function loadAvatar() {
    let vrmPath = BACKEND_HTTP + '/characters/default/model.vrm';
    try {
        const s = await (await fetch(BACKEND_HTTP + '/api/settings')).json();
        if (s?.avatar?.model_path) {
            vrmPath = BACKEND_HTTP + '/' + s.avatar.model_path;
        } else if (s?.character?.active) {
            const chars = await (await fetch(BACKEND_HTTP + '/api/characters')).json();
            const u = chars?.[s.character.active]?.model_url;
            if (u) vrmPath = u.startsWith('http') ? u : BACKEND_HTTP + u;
        }
    } catch (_) {}
    await loadVRM(vrmPath);
}

async function loadVRM(path) {
    const loader = new GLTFLoader();
    loader.register(p => new VRMLoaderPlugin(p));
    const g = await loader.loadAsync(path);
    if (!g.userData.vrm) throw new Error('No VRM');
    vrm = g.userData.vrm;
    VRMUtils.rotateVRM0(vrm);
    VRMUtils.removeUnnecessaryVertices(vrm.scene);
    scene.add(vrm.scene);

    mixer = new THREE.AnimationMixer(vrm.scene);
    const animPath = path.replace(/\/[^/]*$/, '/anim/idle_loop.vrma');
    try {
        const r = await fetch(animPath);
        if (r.ok) {
            const arr = await r.arrayBuffer();
            const { loadVRMAnimation } = await import('../webui/js/vrm-animation.js');
            const clip = await loadVRMAnimation(arr, vrm);
            if (clip) { const a = mixer.clipAction(clip); if (a) a.play(); }
        }
    } catch (_) {}

    if (vrm.expressionManager) {
        const map = vrm.expressionManager.expressionMap;
        if (map) for (const k of Object.keys(map)) _exprWeights[k] = 0;
    }
}


// ====================================================================
//  ANIMATION LOOP
// ====================================================================

function animFrame() {
    animId = requestAnimationFrame(animFrame);
    const dt = Math.min(clock.getDelta(), 0.05);

    if (vrm?.update) vrm.update(dt);
    if (mixer) mixer.update(dt);

    // Smooth mouth visemes for lip-sync
    if (vrm?.expressionManager) {
        mouthAa += (mouthVal - mouthAa) * BLEND_MOUTH;
        mouthOh += (mouthVal * 0.3 - mouthOh) * BLEND_MOUTH;
        vrm.expressionManager.setValue('aa', mouthAa);
        vrm.expressionManager.setValue('oh', mouthOh);
        vrm.expressionManager.setValue('ee', mouthOh * 0.2);

        // Smooth expression blending
        if (_exprBlending) {
            let done = true;
            const map = vrm.expressionManager.expressionMap;
            if (map) {
                for (const k of Object.keys(map)) {
                    const tgt = k === _targetExpr ? 1.0 : 0.0;
                    const cur = _exprWeights[k] || 0;
                    const nxt = cur + (tgt - cur) * BLEND_EXPR;
                    _exprWeights[k] = nxt;
                    vrm.expressionManager.setValue(k, nxt);
                    if (Math.abs(nxt - tgt) > 0.01) done = false;
                }
            }
            if (done) { _exprBlending = false; _currentExpr = _targetExpr; }
        }
    }

    renderer.render(scene, camera);

    // Chroma-key: green pixels -> transparent
    chromaCtx.drawImage(renderer.domElement, 0, 0, VRM_W, VRM_H);
    const id = chromaCtx.getImageData(0, 0, VRM_W, VRM_H);
    const d = id.data;
    for (let i = 0; i < d.length; i += 4) {
        if (d[i + 1] > d[i] + CHROMA_TOL && d[i + 1] > d[i + 2] + CHROMA_TOL) {
            d[i + 3] = 0;
        }
    }

    // Composite to full-screen canvas at bottom-right
    const dw = dispCanvas.width, dh = dispCanvas.height;
    const dx = dw - VRM_W - 20, dy = dh - VRM_H - 20;
    dispCtx.clearRect(0, 0, dw, dh);
    dispCtx.putImageData(id, dx, dy);
}


// ====================================================================
//  IDLE DETECTION
// ====================================================================

function startIdleDetection() {
    ['mousemove','mousedown','keydown','touchstart','wheel'].forEach(evt => {
        document.addEventListener(evt, onActivity, { passive: true });
    });
    resetIdleTimer();
}

function onActivity() {
    const wasIdle = isIdle, wasAway = isAway;
    isIdle = false; isAway = false;
    clearIdleTimers();
    if (wasIdle || wasAway) sendIdleExit();
    resetIdleTimer();
}

function resetIdleTimer() {
    clearIdleTimers();
    idleTimer = setTimeout(() => {
        if (!companionEnabled) return;
        isIdle = true;
        sendIdleEnter();
        awayTimer = setTimeout(() => {
            isAway = true;
            sendIdleTimeout();
        }, AWAY_MS);
    }, IDLE_MS);
}

function clearIdleTimers() {
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
    if (awayTimer) { clearTimeout(awayTimer); awayTimer = null; }
}

// ====================================================================
//  WEBSOCKET
// ====================================================================

function connectWS() {
    if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;
    try { ws = new WebSocket(BACKEND_WS); } catch (_) { reconnect(); return; }
    ws.onopen = () => {
        wsRetry = 0; setConnected(true);
        ws.send(JSON.stringify({ type: 'join', mode: 'companion' }));
        ws.send(JSON.stringify({ type: 'client_hello', capabilities: { platform: 'overlay' } }));
        startHeartbeat();
    };
    ws.onclose = () => { setConnected(false); stopHeartbeat(); ws = null; reconnect(); };
    ws.onerror = () => {};
    ws.onmessage = e => { try { onMsg(JSON.parse(e.data)); } catch (_) {} };
}

function reconnect() {
    if (wsTimer) return;
    const d = RECONNECT_DELAYS[Math.min(wsRetry, RECONNECT_DELAYS.length - 1)];
    wsRetry++;
    wsTimer = setTimeout(() => { wsTimer = null; connectWS(); }, d);
}

function setConnected(c) {
    if (statusEl) { statusEl.textContent = c ? 'connected' : 'disconnected'; statusEl.className = c ? 'connected' : 'disconnected'; }
}

function startHeartbeat() {
    stopHeartbeat();
    pingInterval = setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
    }, HEARTBEAT_MS);
}

function stopHeartbeat() {
    if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
}

function sendIdleEnter()   { if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'idle_enter' })); }
function sendIdleExit()    { if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'idle_exit' })); }
function sendIdleTimeout() { if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'idle_timeout' })); }


// ====================================================================
//  MESSAGE HANDLER
// ====================================================================

function onMsg(d) {
    switch (d.type) {
        case 'tts_state':
            mouthVal = d.playing ? 0.7 : 0;
            break;
        case 'voice_level':
            if (d.level !== undefined) mouthVal = Math.min(1, d.level * 2);
            break;
        case 'emotion':
        case 'expression':
            if ((d.emotion || d.expression) && vrm?.expressionManager) {
                setExpr(d.emotion || d.expression, d.intensity || 1.0);
            }
            break;
        case 'interrupt':
            if (d.action === 'stop_audio_and_animation') mouthVal = 0;
            break;
        case 'companion':
            if (d.enabled !== undefined) companionEnabled = d.enabled;
            if (d.content) showBubble(d.content, d.context || 'proactive');
            break;
        case 'settings_update':
            if (d.settings?.companion?.enabled !== undefined) companionEnabled = d.settings.companion.enabled;
            break;
    }
}

// ====================================================================
//  EXPRESSION CONTROL
// ====================================================================

function setExpr(expression, intensity = 1.0) {
    if (!vrm?.expressionManager) return;
    const map = vrm.expressionManager.expressionMap;
    if (!map) return;
    // Dynamic lookup: try exact, then case-insensitive, then prefix match
    const normalized = expression.toLowerCase();
    const keys = Object.keys(map);
    let target = keys.find(k => k === expression)
              || keys.find(k => k.toLowerCase() === normalized)
              || keys.find(k => k.toLowerCase().startsWith(normalized))
              || keys.find(k => normalized.startsWith(k.toLowerCase()));
    if (!target) return;
    _targetExpr = target;
    _exprBlending = true;
}

// ====================================================================
//  COMPANION BUBBLE
// ====================================================================

function showBubble(text, context) {
    if (!bubbleEl || !bubbleTextEl) return;
    bubbleTextEl.textContent = text;
    bubbleEl.classList.add('visible');
    if (bubbleTimer) clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(() => {
        bubbleEl.classList.remove('visible');
        bubbleTimer = null;
    }, BUBBLE_MS);
}

// ====================================================================
//  CONTROLS
// ====================================================================

function showCtrl() {
    ctrlEl.classList.add('visible');
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => ctrlEl.classList.remove('visible'), 5000);
}

muteBtn.onclick = () => {
    muted = !muted;
    muteBtn.textContent = muted ? '\u{1F507}' : '\u{1F3A4}';
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'mute', muted }));
    showCtrl();
};

closeBtn.onclick = () => { window.close(); };
document.addEventListener('mousemove', showCtrl);
document.addEventListener('keydown', e => { if (e.key === 'Escape') window.close(); });


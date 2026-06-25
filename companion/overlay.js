/**
 * overlay.js — Standalone VRM overlay for Amalgam
 *
 * Uses chroma-key compositing to work around QtWebEngine's
 * broken WebGL alpha. Renders against a green background,
 * then replaces green pixels with transparent on a 2D canvas.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const BACKEND_HTTP = 'http://127.0.0.1:8000';
const BACKEND_WS = 'ws://127.0.0.1:8000/ws/chat';
const RECONNECT_DELAYS = [500, 1000, 2000, 5000, 10000];

// Chroma-key green — bright, unlikely to appear on any character
const KEY_R = 0;
const KEY_G = 255;
const KEY_B = 0;
const KEY_TOLERANCE = 60; // how far from pure green to still be keyed out

let ws = null;
let wsReconnectAttempt = 0;
let wsReconnectTimer = null;
let glRenderer = null;
let scene = null;
let camera = null;
let vrm = null;
let clock = new THREE.Clock();
let mixer = null;
let mouthValue = 0;
let currentMouthAa = 0;
let currentMouthOh = 0;
let isMuted = false;
let animId = null;
let controlsTimer = null;

let displayCanvas = null;
let ctx = null;
let compositeCanvas = null; // buffer for pixel manipulation
let compositeCtx = null;

const canvasContainer = document.getElementById('avatar-canvas');
const statusEl = document.getElementById('status');
const controlsEl = document.getElementById('controls');
const muteBtn = document.getElementById('btn-mute');
const closeBtn = document.getElementById('btn-close');

// ═════════════════════════════════════════════════════════════════
//  Scene
// ═════════════════════════════════════════════════════════════════

function initScene() {
    scene = new THREE.Scene();
    // Chroma-key green background
    scene.background = new THREE.Color(KEY_R/255, KEY_G/255, KEY_B/255);

    camera = new THREE.PerspectiveCamera(22, 280 / 420, 0.1, 20);
    camera.position.set(0, 1.35, 2.8);
    camera.lookAt(0, 1.2, 0);
    scene.add(camera);

    // Hidden WebGL renderer
    glRenderer = new THREE.WebGLRenderer({
        alpha: false,  // opaque — we handle transparency via chroma-key
        antialias: true,
    });
    glRenderer.setSize(280, 420);
    glRenderer.setPixelRatio(window.devicePixelRatio);
    glRenderer.setClearColor(KEY_R/255, KEY_G/255, KEY_B/255, 1);
    glRenderer.domElement.style.position = 'fixed';
    glRenderer.domElement.style.top = '-9999px';
    glRenderer.domElement.style.left = '-9999px';
    document.body.appendChild(glRenderer.domElement);

    // Visible 2D canvas for compositing
    displayCanvas = document.createElement('canvas');
    displayCanvas.width = 280 * window.devicePixelRatio;
    displayCanvas.height = 420 * window.devicePixelRatio;
    displayCanvas.style.width = '100%';
    displayCanvas.style.height = '100%';
    canvasContainer.appendChild(displayCanvas);
    ctx = displayCanvas.getContext('2d');

    // Offscreen canvas for pixel manipulation
    compositeCanvas = document.createElement('canvas');
    compositeCanvas.width = displayCanvas.width;
    compositeCanvas.height = displayCanvas.height;
    compositeCtx = compositeCanvas.getContext('2d', { willReadFrequently: true });

    // Lights
    const key = new THREE.DirectionalLight(0xffffff, 1.2);
    key.position.set(0.8, 1.5, 1.0);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x8888ff, 0.3);
    fill.position.set(-0.5, 0.5, 1.5);
    scene.add(fill);
    scene.add(new THREE.AmbientLight(0xffffff, 0.4));
}

// ═════════════════════════════════════════════════════════════════
//  VRM Loading
// ═════════════════════════════════════════════════════════════════

async function loadVRM(path) {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync(path);
    if (!gltf.userData.vrm) throw new Error('No VRM data');
    vrm = gltf.userData.vrm;
    VRMUtils.rotateVRM0(vrm);
    VRMUtils.removeUnnecessaryVertices(vrm.scene);
    scene.add(vrm.scene);

    mixer = new THREE.AnimationMixer(vrm.scene);

    // Load idle loop animation
    const animUrl = path.replace(/\/[^/]*$/, '/anim/idle_loop.vrma');
    try {
        const resp = await fetch(animUrl);
        if (resp.ok) {
            const buf = await resp.arrayBuffer();
            const { loadVRMAnimation } = await import('../webui/js/vrm-animation.js');
            const clip = await loadVRMAnimation(buf, vrm);
            if (clip) {
                const a = mixer.clipAction(clip);
                if (a) { a.play(); console.log('[Overlay] Idle animation playing'); }
                else { console.log('[Overlay] clipAction returned null'); }
            } else { console.log('[Overlay] loadVRMAnimation returned null'); }
        } else { console.log('[Overlay] No idle anim, HTTP', resp.status); }
    } catch (e) { console.log('[Overlay] Anim load error:', e.message); }

    return vrm;
}

// ═════════════════════════════════════════════════════════════════
//  Animation Loop with Chroma-Key Compositing
// ═════════════════════════════════════════════════════════════════

function animate() {
    animId = requestAnimationFrame(animate);
    const delta = Math.min(clock.getDelta(), 0.05);

    if (vrm?.update) vrm.update(delta);
    if (mixer) mixer.update(delta);

    // Lip-sync
    if (vrm?.expressionManager) {
        const s = 0.25;
        currentMouthAa += (mouthValue - currentMouthAa) * s;
        currentMouthOh += (mouthValue * 0.3 - currentMouthOh) * s;
        vrm.expressionManager.setValue('aa', currentMouthAa);
        vrm.expressionManager.setValue('oh', currentMouthOh);
        vrm.expressionManager.setValue('ee', currentMouthOh * 0.2);
    }

    // Render to WebGL (against green background)
    glRenderer.render(scene, camera);

    // ── Chroma-key compositing pipeline ──
    const w = compositeCanvas.width;
    const h = compositeCanvas.height;

    // Step 1: draw WebGL output onto composite canvas
    compositeCtx.drawImage(glRenderer.domElement, 0, 0, w, h);

    // Step 2: read pixels
    const imageData = compositeCtx.getImageData(0, 0, w, h);
    const pixels = imageData.data;
    const len = pixels.length;

    // Step 3: replace green pixels with transparent
    // A pixel is "green" if its green channel is significantly higher than red+blue
    const tol = KEY_TOLERANCE;
    for (let i = 0; i < len; i += 4) {
        const r = pixels[i];
        const g = pixels[i + 1];
        const b = pixels[i + 2];
        // Detection: green is dominant and far from gray
        if (g > r + tol && g > b + tol) {
            pixels[i + 3] = 0; // transparent
        } else {
            pixels[i + 3] = 255; // opaque
        }
    }
    imageData.data.set(pixels);

    // Step 4: put processed pixels onto composite canvas
    compositeCtx.putImageData(imageData, 0, 0);

    // Step 5: draw final result to display canvas (scales to fit)
    ctx.clearRect(0, 0, displayCanvas.width, displayCanvas.height);
    ctx.drawImage(compositeCanvas, 0, 0, displayCanvas.width, displayCanvas.height);
}

// ═════════════════════════════════════════════════════════════════
//  WebSocket
// ═════════════════════════════════════════════════════════════════

function connectWS() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    try { ws = new WebSocket(BACKEND_WS); } catch (_) { scheduleReconnect(); return; }
    ws.onopen = () => {
        wsReconnectAttempt = 0;
        setConnected(true);
        ws.send(JSON.stringify({ type: 'join' }));
        ws.send(JSON.stringify({ type: 'companion_state', enabled: true }));
    };
    ws.onclose = () => { setConnected(false); ws = null; scheduleReconnect(); };
    ws.onerror = () => {};
    ws.onmessage = (ev) => { try { handleMsg(JSON.parse(ev.data)); } catch (_) {} };
}

function scheduleReconnect() {
    if (wsReconnectTimer) return;
    const d = RECONNECT_DELAYS[Math.min(wsReconnectAttempt, RECONNECT_DELAYS.length - 1)];
    wsReconnectAttempt++;
    wsReconnectTimer = setTimeout(() => { wsReconnectTimer = null; connectWS(); }, d);
}

function setConnected(c) {
    statusEl.textContent = c ? 'connected' : 'disconnected';
    statusEl.className = c ? 'connected' : 'disconnected';
}

function handleMsg(data) {
    switch (data.type) {
        case 'tts_state': mouthValue = data.playing ? 0.7 : 0.0; break;
        case 'voice_level': if (data.level !== undefined) mouthValue = Math.min(1, data.level * 2.0); break;
        case 'emotion': if (data.emotion && vrm?.expressionManager) setExpression(data.emotion); break;
        case 'interrupt': if (data.action === 'stop_audio_and_animation') mouthValue = 0; break;
        case 'settings_update': if (data.settings?.companion?.enabled === false) closeOverlay(); break;
    }
}

function setExpression(emotion) {
    if (!vrm?.expressionManager) return;
    const emap = vrm.expressionManager.expressionMap;
    if (!emap) return;
    for (const k of Object.keys(emap)) vrm.expressionManager.setValue(k, 0);
    const m = { happy:'happy', joy:'happy', neutral:'neutral', sad:'sad', angry:'angry', surprise:'surprised', relaxed:'relaxed' };
    const t = m[emotion] || emotion;
    if (emap[t]) vrm.expressionManager.setValue(t, 1);
}

// ═════════════════════════════════════════════════════════════════
//  Controls
// ═════════════════════════════════════════════════════════════════

function showControls() {
    controlsEl.classList.add('visible');
    if (controlsTimer) clearTimeout(controlsTimer);
    controlsTimer = setTimeout(() => controlsEl.classList.remove('visible'), 5000);
}

muteBtn.addEventListener('click', () => {
    isMuted = !isMuted;
    muteBtn.textContent = isMuted ? '🔇' : '🎤';
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'mute', muted: isMuted }));
    showControls();
});

closeBtn.addEventListener('click', closeOverlay);
document.addEventListener('mousemove', showControls);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeOverlay(); });

function closeOverlay() {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'companion_state', enabled: false }));
    window.close();
    setTimeout(() => { document.body.innerHTML = ''; }, 300);
}

// ═════════════════════════════════════════════════════════════════
//  Boot
// ═════════════════════════════════════════════════════════════════

async function boot() {
    initScene();

    let vrmPath = BACKEND_HTTP + '/characters/default/model.vrm';
    try {
        const s = await (await fetch(BACKEND_HTTP + '/api/settings')).json();
        if (s?.avatar?.model_path) {
            vrmPath = BACKEND_HTTP + '/' + s.avatar.model_path;
        } else if (s?.character?.active) {
            const chars = await (await fetch(BACKEND_HTTP + '/api/characters')).json();
            const url = chars?.[s.character.active]?.model_url;
            if (url) vrmPath = url.startsWith('http') ? url : BACKEND_HTTP + url;
        }
    } catch (e) {
        console.warn('[Overlay] Using default VRM:', e.message);
    }

    console.debug('[Overlay] Loading VRM:', vrmPath);
    await loadVRM(vrmPath);
    clock.start();
    animate();
    connectWS();
    showControls();
    console.debug('[Overlay] Boot complete');
}

boot().catch(err => {
    console.error('[Overlay] Boot error:', err);
    statusEl.textContent = 'error';
});

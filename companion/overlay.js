/**
 * overlay.js — Standalone VRM overlay for Amalgam companion mode
 *
 * Renders VRM avatar with idle animation + TTS lip-sync on a
 * transparent background. Uses a 2D canvas compositing hack to
 * work around QtWebEngine's broken WebGL alpha compositing.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const BACKEND_HTTP = 'http://127.0.0.1:8000';
const BACKEND_WS = 'ws://127.0.0.1:8000/ws/chat';
const RECONNECT_DELAYS = [500, 1000, 2000, 5000, 10000];

let ws = null;
let wsReconnectAttempt = 0;
let wsReconnectTimer = null;
let renderer = null;         // hidden WebGL renderer
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

// Compositing hack: a 2D canvas that composites the WebGL output with alpha
let displayCanvas = null;     // visible 2D canvas
let displayCtx = null;       // 2D context for compositing

const canvasContainer = document.getElementById('avatar-canvas');
const statusEl = document.getElementById('status');
const controlsEl = document.getElementById('controls');
const muteBtn = document.getElementById('btn-mute');
const closeBtn = document.getElementById('btn-close');

// ═════════════════════════════════════════════════════════════════
//  Scene & Compositing Canvas
// ═════════════════════════════════════════════════════════════════

function initScene() {
    scene = new THREE.Scene();

    camera = new THREE.PerspectiveCamera(22, 280 / 420, 0.1, 20);
    camera.position.set(0, 1.35, 2.8);
    camera.lookAt(0, 1.2, 0);
    scene.add(camera);

    // ── Hidden WebGL renderer (alpha matters but QtWebEngine ignores it) ──
    renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        premultipliedAlpha: false,
    });
    renderer.setSize(280, 420);
    renderer.setPixelRatio(1);
    renderer.setClearAlpha(0);
    renderer.setClearColor(0x000000, 0);
    renderer.domElement.style.display = 'none'; // hide the WebGL canvas
    document.body.appendChild(renderer.domElement);

    // ── Visible 2D compositing canvas ──
    displayCanvas = document.createElement('canvas');
    displayCanvas.width = 280;
    displayCanvas.height = 420;
    displayCanvas.style.width = '100%';
    displayCanvas.style.height = '100%';
    displayCanvas.style.display = 'block';
    displayCanvas.style.background = 'transparent';
    canvasContainer.appendChild(displayCanvas);

    displayCtx = displayCanvas.getContext('2d');

    // Lights
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(0.8, 1.5, 1.2);
    scene.add(key);

    const fill = new THREE.DirectionalLight(0x8888ff, 0.4);
    fill.position.set(-0.5, 0.5, 1.5);
    scene.add(fill);

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
}

// ═════════════════════════════════════════════════════════════════
//  VRM Loading
// ═════════════════════════════════════════════════════════════════

async function loadVRM(vrmPath) {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));

    try {
        const gltf = await loader.loadAsync(vrmPath);
        const loadedVrm = gltf.userData.vrm;
        if (!loadedVrm) {
            console.error('[Overlay] No VRM data');
            return null;
        }
        vrm = loadedVrm;
        VRMUtils.rotateVRM0(vrm);
        VRMUtils.removeUnnecessaryVertices(vrm.scene);
        scene.add(vrm.scene);

        mixer = new THREE.AnimationMixer(vrm.scene);

        // Load idle animation
        const animUrl = vrmPath.replace(/\/model\.vrm$/, '/anim/idle_loop.vrma');
        try {
            const resp = await fetch(animUrl);
            if (resp.ok) {
                const buf = await resp.arrayBuffer();
                const { loadVRMAnimation } = await import('../webui/js/vrm-animation.js');
                const clip = await loadVRMAnimation(buf, vrm);
                if (clip) {
                    const action = mixer.clipAction(clip);
                    if (action) {
                        action.play();
                        console.debug('[Overlay] Idle animation playing');
                    }
                }
            }
        } catch (e) {
            console.debug('[Overlay] No idle anim:', e.message);
        }

        console.debug('[Overlay] VRM loaded:', vrmPath);
        return vrm;
    } catch (err) {
        console.error('[Overlay] VRM load failed:', err);
        return null;
    }
}

// ═════════════════════════════════════════════════════════════════
//  Animation Loop (with 2D compositing)
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

    // Render to hidden WebGL canvas
    renderer.render(scene, camera);

    // Composite onto visible 2D canvas with alpha
    // Read back the WebGL pixels as RGBA and draw with proper alpha
    const w = renderer.domElement.width;
    const h = renderer.domElement.height;
    const pixels = new Uint8Array(w * h * 4);
    const gl = renderer.getContext();
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);

    // Create ImageData from pixels (need to flip Y)
    const imageData = displayCtx.createImageData(w, h);
    for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
            const srcIdx = (y * w + x) * 4;
            const dstIdx = ((h - 1 - y) * w + x) * 4;
            // Copy RGBA as-is — the alpha from WebGL clearColor(0,0,0,0)
            // should give us transparent pixels where nothing was rendered
            imageData.data[dstIdx] = pixels[srcIdx];     // R
            imageData.data[dstIdx + 1] = pixels[srcIdx + 1]; // G
            imageData.data[dstIdx + 2] = pixels[srcIdx + 2]; // B
            imageData.data[dstIdx + 3] = pixels[srcIdx + 3]; // A
        }
    }
    displayCtx.putImageData(imageData, 0, 0);

    // Update display canvas size if container changed
    const rect = canvasContainer.getBoundingClientRect();
    if (displayCanvas.width !== Math.round(rect.width) ||
        displayCanvas.height !== Math.round(rect.height)) {
        displayCanvas.width = Math.round(rect.width);
        displayCanvas.height = Math.round(rect.height);
    }
}

// ═════════════════════════════════════════════════════════════════
//  WebSocket
// ═════════════════════════════════════════════════════════════════

function connectWS() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    try {
        ws = new WebSocket(BACKEND_WS);
    } catch (e) {
        scheduleReconnect();
        return;
    }

    ws.onopen = () => {
        wsReconnectAttempt = 0;
        setConnected(true);
        ws.send(JSON.stringify({ type: 'join' }));
        ws.send(JSON.stringify({ type: 'companion_state', enabled: true }));
    };

    ws.onclose = () => {
        setConnected(false);
        ws = null;
        scheduleReconnect();
    };

    ws.onerror = () => {};

    ws.onmessage = (event) => {
        try { handleMessage(JSON.parse(event.data)); } catch (_) {}
    };
}

function scheduleReconnect() {
    if (wsReconnectTimer) return;
    const delay = RECONNECT_DELAYS[Math.min(wsReconnectAttempt, RECONNECT_DELAYS.length - 1)];
    wsReconnectAttempt++;
    wsReconnectTimer = setTimeout(() => { wsReconnectTimer = null; connectWS(); }, delay);
}

function setConnected(c) {
    statusEl.textContent = c ? 'connected' : 'disconnected';
    statusEl.className = c ? 'connected' : 'disconnected';
}

function handleMessage(data) {
    switch (data.type) {
        case 'tts_state':
            mouthValue = data.playing ? 0.7 : 0.0;
            break;
        case 'voice_level':
            if (data.level !== undefined) mouthValue = Math.min(1, data.level * 2.0);
            break;
        case 'emotion':
            if (data.emotion && vrm?.expressionManager) setExpression(data.emotion);
            break;
        case 'interrupt':
            if (data.action === 'stop_audio_and_animation') mouthValue = 0;
            break;
        case 'settings_update':
            if (data.settings?.companion?.enabled === false) closeOverlay();
            break;
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
    setTimeout(() => { document.body.innerHTML = '<div style="padding:2rem;color:#666">Closed</div>'; }, 300);
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
    } catch (_) {}

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

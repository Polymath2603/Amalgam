/**
 * overlay.js — Standalone VRM overlay
 *
 * True transparent compositing:
 * 1. Three.js renders to WebGL framebuffer (alpha=true, preserves per-pixel
 *    alpha from clearColor(0,0,0,0) + scene.background=null)
 * 2. gl.readPixels() reads raw RGBA from the WebGL context — this is the
 *    ONLY way to get per-pixel alpha in QtWebEngine
 * 3. putImageData() writes pixels onto a 2D canvas — 2D canvas alpha
 *    composites correctly in QtWebEngine
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const BACKEND_HTTP = 'http://127.0.0.1:8000';
const BACKEND_WS = 'ws://127.0.0.1:8000/ws/chat';
const RECONNECT_DELAYS = [500, 1000, 2000, 5000, 10000];

let ws, wsRetry = 0, wsTimer = null;
let glr, scene, camera, vrm, mixer, clock = new THREE.Clock();
let mouthVal = 0, mouthAa = 0, mouthOh = 0, muted = false;
let animId = null, hideTimer = null;

// 2D display chain
let disp, dctx;      // visible canvas + context
let buf, bctx;       // offscreen buffer for pixel ops
let pixels, flippedData, pw, ph; // reusable buffers

const container = document.getElementById('avatar-canvas');
const statusEl = document.getElementById('status');
const ctrlEl = document.getElementById('controls');
const muteBtn = document.getElementById('btn-mute');
const closeBtn = document.getElementById('btn-close');

// ═════════════════════════════════════════════════════════════════
//  Scene
// ═════════════════════════════════════════════════════════════════

function init() {
    scene = new THREE.Scene();
    scene.background = null; // CRITICAL: fully transparent

    camera = new THREE.PerspectiveCamera(22, 280/420, 0.1, 20);
    camera.position.set(0, 1.35, 2.8);
    camera.lookAt(0, 1.2, 0);
    scene.add(camera);

    // WebGL renderer with alpha channel in the framebuffer
    glr = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        premultipliedAlpha: false,
        preserveDrawingBuffer: true, // needed for readPixels
    });
    glr.setSize(280, 420);
    glr.setPixelRatio(1);
    glr.setClearAlpha(0);
    glr.setClearColor(0x000000, 0); // transparent clear
    // Keep it offscreen
    glr.domElement.style.cssText = 'position:fixed;top:-9999px;left:-9999px';
    document.body.appendChild(glr.domElement);

    // Visible 2D display canvas — this is what the user sees
    // 2D canvas alpha compositing works correctly in QtWebEngine
    disp = document.createElement('canvas');
    disp.width = 280;
    disp.height = 420;
    container.appendChild(disp);
    dctx = disp.getContext('2d');

    // Offscreen buffer for pixel manipulation
    buf = document.createElement('canvas');
    buf.width = 280;
    buf.height = 420;
    bctx = buf.getContext('2d', { willReadFrequently: true });

    pw = 280;
    ph = 420;
    // Reusable pixel buffers for compositing pipeline
    pixels = new Uint8Array(pw * ph * 4);
    flippedData = new Uint8ClampedArray(pw * ph * 4);

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
//  VRM
// ═════════════════════════════════════════════════════════════════

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

    // Idle animation
    const anim = path.replace(/\/[^/]*$/, '/anim/idle_loop.vrma');
    try {
        const r = await fetch(anim);
        if (r.ok) {
            const buf = await r.arrayBuffer();
            const { loadVRMAnimation } = await import('../webui/js/vrm-animation.js');
            const clip = await loadVRMAnimation(buf, vrm);
            if (clip) {
                const a = mixer.clipAction(clip);
                if (a) a.play();
            }
        }
    } catch (_) {}
    return vrm;
}

// ═════════════════════════════════════════════════════════════════
//  Render loop — WebGL → readPixels → putImageData → 2D canvas
//  This pipeline preserves per-pixel alpha that QtWebEngine would
//  otherwise composite away.
// ═════════════════════════════════════════════════════════════════

function animate() {
    animId = requestAnimationFrame(animate);
    const dt = Math.min(clock.getDelta(), 0.05);

    if (vrm?.update) vrm.update(dt);
    if (mixer) mixer.update(dt);

    // Lip-sync
    if (vrm?.expressionManager) {
        const s = 0.25;
        mouthAa += (mouthVal - mouthAa) * s;
        mouthOh += (mouthVal * 0.3 - mouthOh) * s;
        vrm.expressionManager.setValue('aa', mouthAa);
        vrm.expressionManager.setValue('oh', mouthOh);
        vrm.expressionManager.setValue('ee', mouthOh * 0.2);
    }

    // Render 3D scene to WebGL framebuffer
    // scene.background=null + clearAlpha(0) = transparent everywhere
    // VRM pixels have alpha=255 (opaque)
    glr.render(scene, camera);

    // Read raw RGBA from WebGL framebuffer using gl.readPixels
    // This gives us correct per-pixel alpha values (unlike drawImage which
    // composites against opaque black in QtWebEngine)
    const gl = glr.getContext();
    gl.readPixels(0, 0, pw, ph, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    // WebGL readPixels is bottom-left origin, so flip Y using subarray views
    const rowBytes = pw * 4;
    for (let y = 0; y < ph; y++) {
        const srcStart = y * rowBytes;
        const dstStart = (ph - 1 - y) * rowBytes;
        flippedData.set(pixels.subarray(srcStart, srcStart + rowBytes), dstStart);
    }
    const id = new ImageData(flippedData, pw, ph);
    dctx.putImageData(id, 0, 0);
}

// ═════════════════════════════════════════════════════════════════
//  WS
// ═════════════════════════════════════════════════════════════════

function connectWS() {
    if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;
    try { ws = new WebSocket(BACKEND_WS); } catch (_) { reconnect(); return; }
    ws.onopen = () => { wsRetry = 0; setConnected(true); ws.send(JSON.stringify({type:'join'})); ws.send(JSON.stringify({type:'companion_state',enabled:true})); };
    ws.onclose = () => { setConnected(false); ws = null; reconnect(); };
    ws.onerror = () => {};
    ws.onmessage = e => { try { onMsg(JSON.parse(e.data)); } catch(_) {} };
}
function reconnect() { if (wsTimer) return; const d = RECONNECT_DELAYS[Math.min(wsRetry, RECONNECT_DELAYS.length-1)]; wsRetry++; wsTimer = setTimeout(() => { wsTimer = null; connectWS(); }, d); }
function setConnected(c) { statusEl.textContent = c ? 'connected' : 'disconnected'; statusEl.className = c ? 'connected' : 'disconnected'; }
function onMsg(d) {
    switch (d.type) {
        case 'tts_state': mouthVal = d.playing ? 0.7 : 0; break;
        case 'voice_level': if (d.level !== undefined) mouthVal = Math.min(1, d.level * 2); break;
        case 'emotion': if (d.emotion && vrm?.expressionManager) setExpr(d.emotion); break;
        case 'interrupt': if (d.action === 'stop_audio_and_animation') mouthVal = 0; break;
        case 'settings_update': if (d.settings?.companion?.enabled === false) closeOverlay(); break;
    }
}
function setExpr(e) {
    if (!vrm?.expressionManager) return;
    const m = vrm.expressionManager.expressionMap;
    if (!m) return;
    for (const k of Object.keys(m)) vrm.expressionManager.setValue(k, 0);
    const map = { happy:'happy', joy:'happy', neutral:'neutral', sad:'sad', angry:'angry', surprise:'surprised', relaxed:'relaxed' };
    const t = map[e] || e;
    if (m[t]) vrm.expressionManager.setValue(t, 1);
}

// ═════════════════════════════════════════════════════════════════
//  Controls
// ═════════════════════════════════════════════════════════════════

function showCtrl() { ctrlEl.classList.add('visible'); if (hideTimer) clearTimeout(hideTimer); hideTimer = setTimeout(() => ctrlEl.classList.remove('visible'), 5000); }
muteBtn.onclick = () => { muted = !muted; muteBtn.textContent = muted ? '🔇' : '🎤'; if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type:'mute',muted})); showCtrl(); };
closeBtn.onclick = closeOverlay;
document.addEventListener('mousemove', showCtrl);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeOverlay(); });
function closeOverlay() { if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type:'companion_state',enabled:false})); window.close(); }

// ═════════════════════════════════════════════════════════════════
//  Boot
// ═════════════════════════════════════════════════════════════════

async function boot() {
    init();

    let vp = BACKEND_HTTP + '/characters/default/model.vrm';
    try {
        const s = await (await fetch(BACKEND_HTTP + '/api/settings')).json();
        if (s?.avatar?.model_path) vp = BACKEND_HTTP + '/' + s.avatar.model_path;
        else if (s?.character?.active) {
            const chars = await (await fetch(BACKEND_HTTP + '/api/characters')).json();
            const u = chars?.[s.character.active]?.model_url;
            if (u) vp = u.startsWith('http') ? u : BACKEND_HTTP + u;
        }
    } catch (_) {}

    await loadVRM(vp);
    clock.start();
    animate();
    connectWS();
    showCtrl();
}

boot().catch(e => { console.error('[Overlay]', e); statusEl.textContent = 'error'; });

/**
 * overlay.js — Transparent VRM overlay
 *
 * Pipeline: WebGL renders against green → 2D canvas via drawImage
 * → chroma-key replaces green with transparent → display canvas
 *
 * Why: QtWebEngine composites WebGL against opaque black, BUT
 * drawImage to a 2D canvas preserves the rendered pixels including
 * the green background. Since we control the background color, we
 * can then replace it with transparency on the 2D canvas, which
 * QtWebEngine DOES composite correctly.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const BACKEND_HTTP = 'http://127.0.0.1:8000';
const BACKEND_WS = 'ws://127.0.0.1:8000/ws/chat';
const RECONNECT_DELAYS = [500, 1000, 2000, 5000, 10000];

// Chroma key color — bright green, won't appear on any VRM character
const C = { r: 0, g: 255, b: 0 };
const TOL = 50; // tolerance for green detection

let ws, wsRetry = 0, wsTimer = null;
let glr, scene, camera, vrm, mixer, clock = new THREE.Clock();
let mouthVal = 0, mouthAa = 0, mouthOh = 0, muted = false;
let animId = null, hideTimer = null;

let disp, dctx;      // display canvas (what user sees)
let buf, bctx;       // offscreen buffer for pixel ops
const W = 280, H = 420;

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
    scene.background = new THREE.Color(C.r/255, C.g/255, C.b/255); // solid green

    camera = new THREE.PerspectiveCamera(22, W/H, 0.1, 20);
    camera.position.set(0, 1.35, 2.8);
    camera.lookAt(0, 1.2, 0);
    scene.add(camera);

    // WebGL renderer — alpha:false, opaque green background
    glr = new THREE.WebGLRenderer({ alpha: false, antialias: true });
    glr.setSize(W, H);
    glr.setPixelRatio(1);
    glr.setClearColor(C.r/255, C.g/255, C.b/255, 1);
    glr.domElement.style.cssText = 'position:fixed;top:-9999px;left:-9999px';
    document.body.appendChild(glr.domElement);

    // Display 2D canvas — this handles the alpha compositing
    disp = document.createElement('canvas');
    disp.width = W;
    disp.height = H;
    container.appendChild(disp);
    dctx = disp.getContext('2d');

    // Offscreen buffer for chroma-key
    buf = document.createElement('canvas');
    buf.width = W;
    buf.height = H;
    bctx = buf.getContext('2d', { willReadFrequently: true });

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
//  Render loop — WebGL → 2D drawImage → chroma-key → display
// ═════════════════════════════════════════════════════════════════

function animFrame() {
    animId = requestAnimationFrame(animFrame);
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

    // Step 1: Render 3D to WebGL against green background
    glr.render(scene, camera);

    // Step 2: drawImage WebGL → offscreen 2D canvas
    // drawImage composites the WebGL output (with green background)
    bctx.drawImage(glr.domElement, 0, 0, W, H);

    // Step 3: Chroma-key — replace green pixels with transparent
    const id = bctx.getImageData(0, 0, W, H);
    const d = id.data;
    const len = d.length;
    for (let i = 0; i < len; i += 4) {
        const r = d[i], g = d[i+1], b = d[i+2];
        // If green dominates → make transparent
        if (g > r + TOL && g > b + TOL) {
            d[i+3] = 0; // alpha = 0 (transparent)
        } else {
            d[i+3] = 255; // alpha = 255 (opaque)
        }
    }

    // Step 4: Put chroma-keyed pixels onto display canvas
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
    animFrame();
    connectWS();
    showCtrl();
}

boot().catch(e => { console.error('[Overlay]', e); statusEl.textContent = 'error'; });

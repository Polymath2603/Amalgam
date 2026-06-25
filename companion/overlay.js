/**
 * overlay.js — Full-screen transparent VRM overlay
 *
 * Three.js renders VRM (green bg) → chroma-key → putImageData to
 * full-screen 2D canvas (which handles alpha in QtWebEngine).
 * Avatar composited at bottom-right of screen.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const BACKEND_HTTP = 'http://127.0.0.1:8000';
const BACKEND_WS = 'ws://127.0.0.1:8000/ws/chat';
const RECONNECT_DELAYS = [500, 1000, 2000, 5000, 10000];
const W = 280, H = 420, TOL = 55;

let ws, wsRetry = 0, wsTimer = null;
let glr, scene, camera, vrm, mixer, clock = new THREE.Clock();
let mouthVal = 0, mouthAa = 0, mouthOh = 0, muted = false;
let animId = null, hideTimer = null;
let disp, dctx, buf, bctx;

const statusEl = document.getElementById('status');
const ctrlEl = document.getElementById('controls');
const muteBtn = document.getElementById('btn-mute');
const closeBtn = document.getElementById('btn-close');

function init() {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0, 1, 0);

    camera = new THREE.PerspectiveCamera(22, W/H, 0.1, 20);
    camera.position.set(0, 1.35, 2.8);
    camera.lookAt(0, 1.2, 0);
    scene.add(camera);

    glr = new THREE.WebGLRenderer({ alpha: false, antialias: true });
    glr.setSize(W, H);
    glr.setPixelRatio(1);
    glr.setClearColor(0, 1, 0, 1);
    glr.domElement.style.cssText = 'position:fixed;top:-9999px;left:-9999px';
    document.body.appendChild(glr.domElement);

    // Full-screen display canvas
    disp = document.createElement('canvas');
    disp.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh';
    document.getElementById('avatar-canvas').appendChild(disp);
    dctx = disp.getContext('2d');
    _resize();

    // VRM-size buffer for chroma-key
    buf = document.createElement('canvas');
    buf.width = W; buf.height = H;
    bctx = buf.getContext('2d', { willReadFrequently: true });

    window.addEventListener('resize', _resize);

    const key = new THREE.DirectionalLight(0xffffff, 1.2);
    key.position.set(0.8, 1.5, 1.0);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x8888ff, 0.3);
    fill.position.set(-0.5, 0.5, 1.5);
    scene.add(fill);
    scene.add(new THREE.AmbientLight(0xffffff, 0.4));
}

function _resize() {
    disp.width = window.innerWidth;
    disp.height = window.innerHeight;
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
    const anim = path.replace(/\/[^/]*$/, '/anim/idle_loop.vrma');
    try {
        const r = await fetch(anim);
        if (r.ok) {
            const arr = await r.arrayBuffer();
            const { loadVRMAnimation } = await import('../webui/js/vrm-animation.js');
            const clip = await loadVRMAnimation(arr, vrm);
            if (clip) { const a = mixer.clipAction(clip); if (a) a.play(); }
        }
    } catch (_) {}
    return vrm;
}

function animFrame() {
    animId = requestAnimationFrame(animFrame);
    const dt = Math.min(clock.getDelta(), 0.05);
    if (vrm?.update) vrm.update(dt);
    if (mixer) mixer.update(dt);
    if (vrm?.expressionManager) {
        const s = 0.25;
        mouthAa += (mouthVal - mouthAa) * s;
        mouthOh += (mouthVal * 0.3 - mouthOh) * s;
        vrm.expressionManager.setValue('aa', mouthAa);
        vrm.expressionManager.setValue('oh', mouthOh);
        vrm.expressionManager.setValue('ee', mouthOh * 0.2);
    }

    glr.render(scene, camera);

    // Chroma-key: WebGL → buffer → green→transparent
    bctx.drawImage(glr.domElement, 0, 0, W, H);
    const id = bctx.getImageData(0, 0, W, H);
    const d = id.data;
    for (let i = 0; i < d.length; i += 4) {
        if (d[i+1] > d[i] + TOL && d[i+1] > d[i+2] + TOL) {
            d[i+3] = 0;
        }
    }

    // Composite onto full-screen canvas at bottom-right
    const dw = disp.width, dh = disp.height;
    const dx = dw - W - 20, dy = dh - H - 20;

    // Clear entire display to transparent
    dctx.clearRect(0, 0, dw, dh);

    // Put chroma-keyed VRM pixels at bottom-right
    dctx.putImageData(id, dx, dy);
}

function connectWS() {
    if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;
    try { ws = new WebSocket(BACKEND_WS); } catch (_) { reconnect(); return; }
    ws.onopen = () => { wsRetry = 0; setConnected(true); ws.send(JSON.stringify({type:'join',mode:'companion'})); };
    ws.onclose = () => { setConnected(false); ws = null; reconnect(); };
    ws.onerror = () => {};
    ws.onmessage = e => { try { onMsg(JSON.parse(e.data)); } catch(_) {} };
}
function reconnect() { if (wsTimer) return; const d = RECONNECT_DELAYS[Math.min(wsRetry, RECONNECT_DELAYS.length-1)]; wsRetry++; wsTimer = setTimeout(()=>{wsTimer=null;connectWS();}, d); }
function setConnected(c) { statusEl.textContent = c ? 'connected' : 'disconnected'; statusEl.className = c ? 'connected' : 'disconnected'; }
function onMsg(d) {
    switch (d.type) {
        case 'tts_state': mouthVal = d.playing ? 0.7 : 0; break;
        case 'voice_level': if (d.level!==undefined) mouthVal = Math.min(1, d.level*2); break;
        case 'emotion': if (d.emotion && vrm?.expressionManager) setExpr(d.emotion); break;
        case 'interrupt': if (d.action==='stop_audio_and_animation') mouthVal = 0; break;
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

function showCtrl() { ctrlEl.classList.add('visible'); if (hideTimer) clearTimeout(hideTimer); hideTimer = setTimeout(()=>ctrlEl.classList.remove('visible'),5000); }
muteBtn.onclick = () => { muted = !muted; muteBtn.textContent = muted ? '🔇' : '🎤'; if (ws?.readyState===WebSocket.OPEN) ws.send(JSON.stringify({type:'mute',muted})); showCtrl(); };
closeBtn.onclick = () => { window.close(); };
document.addEventListener('mousemove', showCtrl);
document.addEventListener('keydown', e => { if (e.key === 'Escape') window.close(); });

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

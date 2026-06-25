/**
 * overlay.js — Standalone VRM overlay for Amalgam companion mode
 *
 * Renders a VRM avatar on a transparent background, connects to the
 * backend via WebSocket for voice/TTS/mood events.
 *
 * This is a self-contained module (no dependency on webui/state.js).
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

// ── Config ─────────────────────────────────────────────────────────
const BACKEND_HTTP = 'http://127.0.0.1:8000';
const BACKEND_WS = 'ws://127.0.0.1:8000/ws/chat';
const RECONNECT_DELAYS = [500, 1000, 2000, 5000, 10000];
const IDLE_HIDE_MS = 30000; // hide controls after 30s idle

// ── State ──────────────────────────────────────────────────────────
let ws = null;
let wsReconnectAttempt = 0;
let wsReconnectTimer = null;
let renderer = null;
let scene = null;
let camera = null;
let vrm = null;
let clock = new THREE.Clock();
let mixer = null;
let currentEmotion = 'neutral';
let mouthValue = 0;
let idleTimer = null;
let isVisible = true;
let animId = null;

// ── DOM refs ───────────────────────────────────────────────────────
const canvasContainer = document.getElementById('avatar-canvas');
const statusEl = document.getElementById('status');
const disconnectedBar = document.getElementById('disconnected-bar');
const disconnectedText = document.getElementById('disconnected-text');
const controlsEl = document.getElementById('controls');
const muteBtn = document.getElementById('btn-mute');
const exitBtn = document.getElementById('btn-exit');
let isMuted = false;

// ═════════════════════════════════════════════════════════════════
//  Three.js Scene Setup
// ═════════════════════════════════════════════════════════════════

function initScene() {
    scene = new THREE.Scene();

    // Camera
    camera = new THREE.PerspectiveCamera(25, window.innerWidth / window.innerHeight, 0.1, 20);
    camera.position.set(0, 1.3, 3.2);
    camera.lookAt(0, 1.2, 0);
    scene.add(camera);

    // WebGL renderer (transparent)
    renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        preserveDrawingBuffer: false,
    });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0); // fully transparent
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    canvasContainer.appendChild(renderer.domElement);

    // Lights
    const light = new THREE.DirectionalLight(0xffffff, Math.PI);
    light.position.set(1, 1, 1).normalize();
    scene.add(light);
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));

    // Subtle grid
    const grid = new THREE.GridHelper(10, 10, 0x333355, 0x222244);
    scene.add(grid);

    // Resize handler
    window.addEventListener('resize', onResize);
}

function onResize() {
    if (!renderer || !camera) return;
    const w = window.innerWidth;
    const h = window.innerHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
}

// ═════════════════════════════════════════════════════════════════
//  VRM Model Loading
// ═════════════════════════════════════════════════════════════════

async function loadVRM(vrmPath) {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));

    try {
        const gltf = await loader.loadAsync(vrmPath);
        const loadedVrm = gltf.userData.vrm;
        if (!loadedVrm) {
            console.error('[Overlay] No VRM data in loaded model');
            return null;
        }
        vrm = loadedVrm;
        vrm.scene.name = 'VRM';

        // Auto-detect hips and reposition
        VRMUtils.rotateVRM0(vrm);
        VRMUtils.removeUnnecessaryVertices(vrm.scene);

        scene.add(vrm.scene);

        // Setup animation mixer
        mixer = new THREE.AnimationMixer(vrm.scene);

        // Try to load idle animation
        try {
            const animPath = vrmPath.replace(/model\.vrm$/, 'anim/idle_loop.vrma');
            const animResp = await fetch(animPath);
            if (animResp.ok) {
                const animBuffer = await animResp.arrayBuffer();
                const { loadVRMAnimation } = await import('../webui/js/vrm-animation.js');
                const clip = await loadVRMAnimation(animBuffer, vrm);
                if (clip) {
                    const action = mixer.clipAction(clip);
                    action.play();
                }
            }
        } catch (_) {
            // No idle animation — no problem
        }

        console.debug('[Overlay] VRM loaded:', vrmPath);
        return vrm;
    } catch (err) {
        console.error('[Overlay] Failed to load VRM:', err);
        return null;
    }
}

// ═════════════════════════════════════════════════════════════════
//  Animation Loop
// ═════════════════════════════════════════════════════════════════

function animate() {
    animId = requestAnimationFrame(animate);
    const delta = clock.getDelta();

    // Update VRM (applies blendshapes, bones)
    if (vrm && vrm.update) {
        vrm.update(delta);
    }

    // Update mixer (animations)
    if (mixer) {
        mixer.update(delta);
    }

    // Apply mouth opening for TTS
    if (vrm && vrm.expressionManager) {
        const current = mouthValue;
        // Smoothly approach mouth value
        const smooth = 0.3;
        const aa = vrm.expressionManager.getValue('aa') || 0;
        const newAa = aa + (current - aa) * smooth;
        vrm.expressionManager.setValue('aa', Math.max(0, Math.min(1, newAa)));
        vrm.expressionManager.setValue('oh', Math.max(0, Math.min(1, newAa * 0.3)));
    }

    renderer.render(scene, camera);
}

// ═════════════════════════════════════════════════════════════════
//  WebSocket Connection
// ═════════════════════════════════════════════════════════════════

function connectWS() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

    try {
        ws = new WebSocket(BACKEND_WS);
    } catch (e) {
        console.error('[Overlay] WS connection failed:', e);
        scheduleReconnect();
        return;
    }

    ws.onopen = () => {
        console.debug('[Overlay] WS connected');
        wsReconnectAttempt = 0;
        setConnected(true);
        // Send auth / join
        ws.send(JSON.stringify({ type: 'join' }));
        // Request companion state
        ws.send(JSON.stringify({ type: 'companion_state', enabled: true }));
    };

    ws.onclose = () => {
        console.debug('[Overlay] WS disconnected');
        setConnected(false);
        ws = null;
        if (isVisible) scheduleReconnect();
    };

    ws.onerror = (e) => {
        console.error('[Overlay] WS error:', e);
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleMessage(data);
        } catch (e) {
            console.error('[Overlay] Failed to parse message:', e);
        }
    };
}

function scheduleReconnect() {
    if (wsReconnectTimer) return;
    const delay = RECONNECT_DELAYS[Math.min(wsReconnectAttempt, RECONNECT_DELAYS.length - 1)];
    wsReconnectAttempt++;
    console.debug(`[Overlay] Reconnecting in ${delay}ms (attempt ${wsReconnectAttempt})`);
    wsReconnectTimer = setTimeout(() => {
        wsReconnectTimer = null;
        connectWS();
    }, delay);
}

function setConnected(connected) {
    statusEl.textContent = connected ? 'connected' : 'disconnected';
    statusEl.className = connected ? 'connected' : 'disconnected';
    if (connected) {
        disconnectedBar.style.display = 'none';
        disconnectedText.style.display = 'none';
        disconnectedText.classList.remove('visible');
    } else {
        disconnectedBar.style.display = '';
        disconnectedText.style.display = '';
        disconnectedText.classList.add('visible');
    }
}

// ═════════════════════════════════════════════════════════════════
//  Message Handling
// ═════════════════════════════════════════════════════════════════

function handleMessage(data) {
    switch (data.type) {
        case 'error':
            console.error('[Overlay] Server error:', data.message);
            break;

        case 'settings_update':
            // Backend pushed settings change — check companion state
            if (data.settings?.companion?.enabled === false) {
                // Companion was disabled by backend — close overlay
                closeOverlay();
            }
            break;

        case 'tts_state':
            // Mouth animation based on TTS
            if (data.playing !== undefined) {
                mouthValue = data.playing ? 0.7 : 0.0;
            }
            break;

        case 'emotion':
            // Emotion from backend
            if (data.emotion) {
                currentEmotion = data.emotion;
                applyEmotion(data.emotion);
            }
            break;

        case 'voice_level':
            // Real-time audio level (0-1) for mouth animation
            if (data.level !== undefined) {
                mouthValue = Math.min(1, data.level * 1.5);
            }
            break;

        case 'interrupt':
            if (data.action === 'stop_audio_and_animation') {
                mouthValue = 0;
            }
            break;

        default:
            // Generic message types — log only
            if (data.type !== 'pong' && data.type !== 'health') {
                console.debug('[Overlay] Unhandled message type:', data.type);
            }
    }
}

function applyEmotion(emotion) {
    if (!vrm || !vrm.expressionManager) return;
    // Reset all expressions
    const names = vrm.expressionManager.expressionMap ? 
        Object.keys(vrm.expressionManager.expressionMap) : [];
    for (const name of names) {
        vrm.expressionManager.setValue(name, 0);
    }
    // Set the target emotion
    const emotionMap = {
        'happy': 'happy', 'joy': 'happy',
        'sad': 'sad', 'angry': 'angry',
        'surprised': 'surprised', 'surprise': 'surprised',
        'relaxed': 'relaxed', 'neutral': 'neutral',
    };
    const target = emotionMap[emotion] || emotion;
    if (vrm.expressionManager.expressionMap?.[target]) {
        vrm.expressionManager.setValue(target, 1);
    }
}

// ═════════════════════════════════════════════════════════════════
//  Controls & UI
// ═════════════════════════════════════════════════════════════════

function showControls() {
    controlsEl.classList.remove('hidden');
    resetIdleTimer();
}

function hideControls() {
    controlsEl.classList.add('hidden');
}

function resetIdleTimer() {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(hideControls, IDLE_HIDE_MS);
}

// Mute toggle
muteBtn.addEventListener('click', () => {
    isMuted = !isMuted;
    muteBtn.classList.toggle('active', isMuted);
    muteBtn.textContent = isMuted ? '🔇' : '🎤';
    // Send mute state to backend
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'mute', muted: isMuted }));
    }
});

// Exit button
exitBtn.addEventListener('click', closeOverlay);

function closeOverlay() {
    // Tell backend we're leaving companion mode
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'companion_state', enabled: false }));
    }
    // Exit the window
    if (typeof window !== 'undefined') {
        window.close();
    }
    // If window.close() didn't work (browser security), try sending a signal
    setTimeout(() => {
        document.body.innerHTML = '<div style="padding:2rem;text-align:center;color:#888">Companion closed</div>';
    }, 500);
}

// Mouse movement shows controls
document.addEventListener('mousemove', showControls);
document.addEventListener('touchstart', showControls);

// Keyboard shortcut: Esc to close
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeOverlay();
    if (e.key === 'm' || e.key === 'M') muteBtn.click();
});

// ═════════════════════════════════════════════════════════════════
//  Boot
// ═════════════════════════════════════════════════════════════════

async function boot() {
    initScene();

    // Determine VRM path from backend settings
    let vrmPath = BACKEND_HTTP + '/characters/default/model.vrm';
    try {
        const resp = await fetch(BACKEND_HTTP + '/api/settings');
        if (resp.ok) {
            const settings = await resp.json();
            const charActive = settings?.character?.active;
            if (charActive) {
                const charsResp = await fetch(BACKEND_HTTP + '/api/characters');
                if (charsResp.ok) {
                    const chars = await charsResp.json();
                    const charModelUrl = chars?.[charActive]?.model_url;
                    if (charModelUrl) {
                        vrmPath = charModelUrl.startsWith('http')
                            ? charModelUrl
                            : BACKEND_HTTP + charModelUrl;
                    }
                }
            }
            if (settings?.avatar?.model_path) {
                vrmPath = BACKEND_HTTP + '/' + settings.avatar.model_path;
            }
        }
    } catch (e) {
        console.warn('[Overlay] Failed to fetch settings, using default VRM');
    }

    // Load VRM
    await loadVRM(vrmPath);

    // Start render loop
    clock.start();
    animate();

    // Connect to backend
    connectWS();

    // Show controls briefly at start
    showControls();
}

boot().catch(err => {
    console.error('[Overlay] Boot failed:', err);
    statusEl.textContent = 'error';
    statusEl.className = 'disconnected';
});

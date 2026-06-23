


const _origWarn = console.warn;
console.warn = (...args) => {
    if (args[0]?.includes?.('THREE.Clock: This module has been deprecated')) return;
    _origWarn.apply(console, args);
};

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { IS_TAURI, BASE_URL } from './modules/config.js';
import { showToast, escHtml } from './modules/utils.js';

import { loadVRMAnimation } from './vrm-animation.js';
import { AdaptiveLipsyncManager } from './adaptive-lipsync.js';
export { SpriteAvatar } from './sprite-avatar.js';
let AdvancedLipSync = null;
try {
    const mod = await import('./advanced-lipsync.js');
    AdvancedLipSync = mod.AdvancedLipSync;
} catch (e) {
    console.warn('[Avatar] AdvancedLipSync not available, using standard lipsync:', e.message);
}
import { IdleManager } from './idle-manager.js';
import { AnimationManager, ANIM_PRIORITY } from './animation-manager.js';

/**
 * Emotion → candidate VRM expression names (in priority order).
 * Using arrays lets us handle VRM models with non-standard naming.
 * The first expression name that exists in the loaded VRM is used.
 */
const EMOTION_CANDIDATES = {
    neutral:       [null],
    happy:         ['happy', 'joy', 'smile', 'pleasant'],
    angry:         ['angry', 'anger', 'frustrated'],
    sad:           ['sad', 'sorrow', 'cry'],
    relaxed:       ['relaxed', 'neutral'],
    surprised:     ['surprised', 'surprise', 'wow'],
    thinking:      ['relaxed', 'neutral'],
    speaking:      ['happy', 'joy', 'a'],
    listening:     [null],
    confused:      ['surprised', 'surprise', 'angry'],
    // Extended emotions
    shy:           ['relaxed', 'happy', 'neutral'],
    embarrassed:   ['relaxed', 'surprised'],
    jealous:       ['angry', 'sad'],
    bored:         ['relaxed', 'neutral'],
    suspicious:    ['angry', 'relaxed'],
    worried:       ['sad', 'relaxed'],
    victory:       ['happy', 'joy'],
    sleep:         ['relaxed', 'neutral'],
    love:          ['happy', 'joy'],
    excited:       ['surprised', 'happy'],
    flirty:        ['happy', 'joy'],
    smug:          ['happy', 'relaxed'],
    concerned:     ['sad', 'relaxed'],
    disgusted:     ['angry', 'sad'],
    curious:       ['surprised', 'happy'],
    amused:        ['happy', 'joy'],
};

const EXPRESSION_NAMES = ['happy', 'angry', 'sad', 'relaxed', 'surprised'];


const SACCADE_MIN_INTERVAL = 0.5;
const SACCADE_PROC = 0.05;
const SACCADE_RADIUS = 5.0 * (Math.PI / 180); 


const BLINK_CLOSE_MAX = 0.12;
const BLINK_OPEN_MAX = 5;


export class AvatarRenderer {
    constructor(container, vrmPath, options = {}) {
        this.container = container;
        this.vrmPath = vrmPath || (BASE_URL + '/characters/default/model.vrm');
        this.preview = options.preview || false;
        this.animConfig = Object.assign({
            idle: BASE_URL + '/characters/default/anim/idle_loop.vrma',
        }, options.animations || {});
        this.vrm = null;
        this.clock = new THREE.Clock();
        this.ready = false;
        this.currentEmotion = 'neutral';
        this.mouthValue = 0;
        this._targetExpressions = {};
        for (const expr of EXPRESSION_NAMES) this._targetExpressions[expr] = 0;

        
        this._lipsyncManager = null;
        this._audioContext = null;

        this._blinkTimer = BLINK_OPEN_MAX;
        this._blinkIsOpen = true;
        this._blinkEnabled = true;
        
        // Pending emotion queue — setEmotion calls before VRM is ready
        // are deferred and applied once the VRM model finishes loading.
        this._pendingEmotion = null;

        // Auto-neutral timer: emotions auto-reset after duration to prevent sticking
        this._emotionDuration = 5000;  // 5 seconds default
        this._emotionTimer = null;

        this._saccadeYaw = 0;
        this._saccadePitch = 0;
        this._saccadeTimer = 0;
        this._yawDamped = 0;
        this._pitchDamped = 0;

        // Breathing animation
        this._breathingEnabled = true;
        this._breathingPhase = Math.random() * Math.PI * 2;
        this._breathingAmplitude = 0.003;
        this._breathingSpeed = 1.5;

        this._mixer = null;
        this._currentAction = null;
        this._idleAction = null;
        this._animationQueue = [];

        this._animManager = new AnimationManager(this);


        this._lookAtFallback = false;

        
        this._headPositionListeners = [];
        this._lastHeadScreenPos = null;

        
        this._hitAreaEnabled = !this.preview;
        this._idleBehaviorTimer = null;

        
        this._idleManager = null;
        this._sleepBlinkOpenSec = null; 

        
        this.renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
        const initW = this.container.clientWidth || 800;
        const initH = this.container.clientHeight || 600;
        this.renderer.setSize(initW, initH);
        // Limit pixelRatio to 1.0 on mobile for better performance
        this._isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
        this.renderer.setPixelRatio(this._isMobile ? 1.0 : Math.min(window.devicePixelRatio, 2));
        this.renderer.setClearColor(0x000000, 0);
        this.container.appendChild(this.renderer.domElement);

        // WebGL context loss handlers for tab switch recovery
        this.renderer.domElement.addEventListener('webglcontextlost', (e) => {
            e.preventDefault();
            console.warn('[Avatar] WebGL context lost — pausing render loop');
            if (this._rafId) {
                cancelAnimationFrame(this._rafId);
                this._rafId = null;
            }
        }, false);

        this.renderer.domElement.addEventListener('webglcontextrestored', () => {
            console.log('[Avatar] WebGL context restored — resuming');
            this._animate();
        }, false);

        
        const aspect = this.container.clientWidth / this.container.clientHeight || 1;
        this.camera = new THREE.PerspectiveCamera(this.preview ? 18 : 25, aspect, 0.1, 20);
        if (this.preview) {
            this.camera.position.set(0, 1.5, 1.2);
            this.camera.lookAt(0, 1.5, 0);
        } else {
            this.camera.position.set(0, 1.3, 3.2);
            this.camera.lookAt(0, 1.2, 0);
        }

        
        this.scene = new THREE.Scene();
        this.scene.add(this.camera);

        // Post-processing pipeline (must be after scene + camera init)
        this._composer = null;
        this._postProcessingEnabled = false;
        this._initComposer();

        
        const light = new THREE.DirectionalLight(0xffffff, Math.PI);
        light.position.set(1, 1, 1).normalize();
        this.scene.add(light);
        this.scene.add(new THREE.AmbientLight(0xffffff, 0.7));

        
        if (!this.preview) {
            const grid = new THREE.GridHelper(10, 10, 0x333355, 0x222244);
            this.scene.add(grid);
        }

        
        this._onResize = () => {
            const w = this.container.clientWidth;
            const h = this.container.clientHeight;
            if (w > 0 && h > 0) {
                this.camera.aspect = w / h;
                this.camera.updateProjectionMatrix();
                this.renderer.setSize(w, h);
            }
        };
        this._resizeObserver = new ResizeObserver(() => this._onResize());
        this._resizeObserver.observe(this.container);

        // Visibility change handler to pause/resume render loop and save battery on mobile
        this._visibilityHandler = () => {
            if (document.hidden) {
                if (this._rafId) {
                    cancelAnimationFrame(this._rafId);
                    this._rafId = null;
                }
            } else if (!this._rafId) {
                this._animate();
            }
        };
        document.addEventListener('visibilitychange', this._visibilityHandler);

        this._loadVRM();
        this._animate();
        if (this._hitAreaEnabled) {
            this._setupHitAreas();
        }
        if (!this.preview) {
            this._setupDragAndDrop();
        }
    }

    loadVRM(newPath) {
        if (this.vrm) {
            this.scene.remove(this.vrm.scene);
            VRMUtils.deepDispose(this.vrm.scene);
            this.vrm = null;
            this.ready = false;
        }
        
        if (this._saccadeTarget) {
            this.camera.remove(this._saccadeTarget);
            this._saccadeTarget = null;
        }
        this._lookAtFallback = false;
        this._mixer = null;
        this._idleAction = null;
        this._currentAction = null;
        // Clear life state machine interval before VRM reload to prevent leak
        if (this._lifeInterval) {
            clearInterval(this._lifeInterval);
            this._lifeInterval = null;
        }
        this.vrmPath = newPath;
        this._loadVRM();
    }

    _loadVRM() {
        const loader = new GLTFLoader();
        loader.crossOrigin = 'anonymous';
        loader.register((parser) => new VRMLoaderPlugin(parser));

        const loadPath = this.vrmPath;
        const isFallback = loadPath === BASE_URL + '/characters/default/model.vrm';
        let abandoned = false;

        
        const timeout = setTimeout(() => {
            console.warn(`VRM load timeout for ${loadPath} (60s)`);
            if (!isFallback) {
                console.warn('Falling back to default VRM');
                abandoned = true;
                this.vrmPath = BASE_URL + '/characters/default/model.vrm';
                this._loadVRM();
            }
        }, 60000);

        loader.load(
            loadPath,
            async (gltf) => {
                if (abandoned) return;
                clearTimeout(timeout);

                console.debug(`[Avatar] Model loaded successfully: ${loadPath}`);
                const vrm = gltf.userData.vrm;
                if (!vrm) {
                    console.error(`[Avatar] Loaded file but no VRM data found in: ${loadPath}`);
                    if (!isFallback) {
                        console.warn('Falling back to default VRM');
                        this.vrmPath = BASE_URL + '/characters/default/model.vrm';
                        this._loadVRM();
                    }
                    return;
                }

                VRMUtils.removeUnnecessaryVertices(gltf.scene);
                try { VRMUtils.combineSkeletons(gltf.scene); } catch(e) { console.warn('[Avatar] combineSkeletons failed:', e.message); }
                try { VRMUtils.combineMorphs(vrm); } catch(e) { console.warn('[Avatar] combineMorphs failed:', e.message); }

                
                if (vrm.meta?.metaVersion === '0') {
                    vrm.scene.rotation.y = Math.PI;
                }
                vrm.scene.traverse((obj) => { obj.frustumCulled = false; });

                this.vrm = vrm;
                
                
                vrm.update(0);
                vrm.scene.updateMatrixWorld(true);
                
                this.scene.add(vrm.scene);

                
                
                this._saccadeTarget = new THREE.Object3D();
                this._saccadeTarget.position.set(0, 0, -1);
                this.camera.add(this._saccadeTarget);
                if (vrm.lookAt) {
                    vrm.lookAt.target = this._saccadeTarget;
                } else if (vrm.humanoid) {
                    console.warn('[Avatar] No VRM lookAt system, using head bone fallback');
                    this._lookAtFallback = true;
                }

                
                if (vrm.expressionManager) {
                    const { expressionMap, presetExpressionMap } = vrm.expressionManager;
                    const customExpressions = Object.keys(expressionMap).filter(k => !(k in presetExpressionMap));
                    customExpressions.forEach(name => {
                        try {
                            const expr = expressionMap[name];
                            if (expr) vrm.expressionManager.registerExpression(expr);
                        } catch(e) { console.warn(`[Avatar] Failed to register expression "${name}":`, e.message); }
                    });
                    
                    const presetNames = Object.keys(presetExpressionMap || {});
                    const customNames = Object.keys(expressionMap);
                    this._allExpressionNames = [...new Set([...presetNames, ...customNames, ...EXPRESSION_NAMES])];
                } else {
                    console.warn('[Avatar] No expressionManager found on VRM');
                }

                this._mixer = new THREE.AnimationMixer(vrm.scene);

                
                try {
                    this._fitCameraToModel(vrm);
                } catch(e) {
                    console.error('[Avatar] Camera fit failed:', e);
                }

                this.ready = true;

                try {
                    await this._loadIdleAnimation();
                } catch(e) {
                    console.warn('VRMA animations not available, using procedural idle:', e);
                }


                this._animManager.init(vrm, this._mixer);
                this._animManager.onFinish = () => {
                    if (this._idleAction) this._fadeToAction(this._idleAction, 0.5);
                };

                if (this._hitAreaEnabled) {
                    this._startIdleBehaviorLoop();
                }

                // Start life state machine (idle → bored → sleeping)
                this.initLifeStateMachine();

                // Apply any emotion that was queued before VRM was ready
                if (this._pendingEmotion) {
                    const pending = this._pendingEmotion;
                    this._pendingEmotion = null;
                    this.setEmotion(pending);
                }

            },
            () => {},
            (error) => {
                if (abandoned) return;
                clearTimeout(timeout);
                console.error(`VRM load error for ${loadPath}:`, error);
                if (!isFallback) {
                    console.warn('Falling back to default VRM');
                    this.vrmPath = BASE_URL + '/characters/default/model.vrm';
                    this._loadVRM();
                }
            }
        );
    }

    async _loadIdleAnimation() {
        const vrmAnim = await loadVRMAnimation(this.animConfig.idle);
        if (!vrmAnim || !this.vrm || !this._mixer) return;

        const clip = vrmAnim.createAnimationClip(this.vrm);

        this._idleAction = this._mixer.clipAction(clip);
        this._idleAction.loop = THREE.LoopRepeat;
        this._fadeToAction(this._idleAction, 0.5);
    }

    async playAnimation(url, onComplete) {
        if (!this.vrm || !this._mixer || !this._idleAction) {
            if (onComplete) onComplete();
            return;
        }

        try {
            const vrmAnim = await loadVRMAnimation(url);
            if (!vrmAnim) {
                if (onComplete) onComplete();
                return;
            }

            const clip = vrmAnim.createAnimationClip(this.vrm);
            
            const action = this._mixer.clipAction(clip);
            action.clampWhenFinished = true;
            action.loop = THREE.LoopOnce;

            this._fadeToAction(action, 0.5);

            
            const handleFinish = () => {
                this._mixer.removeEventListener('finished', handleFinish);
                this._fadeToAction(this._idleAction, 1);
                if (onComplete) onComplete();
            };
            this._mixer.addEventListener('finished', handleFinish);
        } catch(e) {
            console.warn('Animation load failed:', url, e);
            if (onComplete) onComplete();
        }
    }

    _fadeToAction(destAction, duration) {
        const prev = this._currentAction;
        this._currentAction = destAction;

        if (prev && prev !== destAction) {
            prev.fadeOut(duration);
        }
        destAction.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).fadeIn(duration).play();
    }

    _fitCameraToModel(vrm) {
        
        vrm.update(0);
        vrm.scene.updateMatrixWorld(true);

        
        const box = new THREE.Box3();
        const skipNames = ['collider', 'spring', 'helper', 'joint', 'target', 'shadow', 'collision'];
        vrm.scene.traverse((obj) => {
            if (!obj.isMesh || !obj.visible || !obj.geometry) return;
            const lower = obj.name.toLowerCase();
            if (skipNames.some(s => lower.includes(s))) return;
            const vertCount = obj.geometry.attributes.position?.count || 0;
            if (vertCount < 100) return;
            obj.geometry.computeBoundingBox();
            const bb = obj.geometry.boundingBox;
            if (!bb) return;
            const localSize = new THREE.Vector3();
            bb.getSize(localSize);
            if (localSize.x < 0.01 || localSize.y < 0.01 || localSize.z < 0.01) return;
            const worldBB = bb.clone().applyMatrix4(obj.matrixWorld);
            if (isNaN(worldBB.min.x) || isNaN(worldBB.min.y) || isNaN(worldBB.min.z) ||
                isNaN(worldBB.max.x) || isNaN(worldBB.max.y) || isNaN(worldBB.max.z) ||
                !isFinite(worldBB.min.x) || !isFinite(worldBB.min.y) || !isFinite(worldBB.min.z) ||
                !isFinite(worldBB.max.x) || !isFinite(worldBB.max.y) || !isFinite(worldBB.max.z)) {
                return;
            }
            box.union(worldBB);
        });
        
        if (box.isEmpty()) box.setFromObject(vrm.scene);
        if (box.isEmpty()) {
            console.warn('[Avatar] Empty bounding box, using default camera position');
            this.camera.position.set(0, 1.3, this.preview ? 1.2 : 3.2);
            this.camera.lookAt(0, 1.2, 0);
            return;
        }

        const size = new THREE.Vector3();
        const center = new THREE.Vector3();
        box.getSize(size);
        box.getCenter(center);

        this._modelSize = size;
        this._modelCenter = center;

        
        const upperHeight = Math.max(size.y * 0.6, 0.3);
        const fov = this.camera.fov * (Math.PI / 180);

        const hips = vrm.humanoid?.getNormalizedBoneNode('hips');
        const hipsPos = new THREE.Vector3();
        if (hips) hips.getWorldPosition(hipsPos);
        else hipsPos.copy(center);

        let dist;
        const focalPoint = new THREE.Vector3();

        if (this.preview) {
            
            const headBone = vrm.humanoid?.getNormalizedBoneNode('head');
            const neckBone = vrm.humanoid?.getNormalizedBoneNode('neck');

            if (headBone && neckBone) {
                vrm.update(0);
                vrm.scene.updateMatrixWorld(true);

                const headPos = new THREE.Vector3();
                const neckPos = new THREE.Vector3();
                headBone.getWorldPosition(headPos);
                neckBone.getWorldPosition(neckPos);

                const headLen = headPos.distanceTo(neckPos);

                
                const headBox = new THREE.Box3();
                const halfW = headLen * 0.6;
                const halfD = headLen * 0.6;
                headBox.set(
                    new THREE.Vector3(headPos.x - halfW, neckPos.y, headPos.z - halfD),
                    new THREE.Vector3(headPos.x + halfW, headPos.y + headLen * 1.2, headPos.z + halfD)
                );
                const headSize = headBox.getSize(new THREE.Vector3());
                const maxDim = Math.max(headSize.x, headSize.y, headSize.z);

                dist = maxDim / Math.tan(fov / 2);
                const midY = neckPos.y + headSize.y * 0.45;
                focalPoint.set(headPos.x, midY, headPos.z);
            } else {
                
                const sceneBox = new THREE.Box3().setFromObject(vrm.scene);
                const sceneSize = sceneBox.getSize(new THREE.Vector3());
                const sceneCenter = sceneBox.getCenter(new THREE.Vector3());
                dist = (sceneSize.y * 0.25) / Math.tan(fov / 2);
                const fallbackY = sceneBox.max.y - sceneSize.y * 0.1;
                focalPoint.set(sceneCenter.x, fallbackY, sceneCenter.z);
            }
        } else {
            
            const headBone = vrm.humanoid?.getNormalizedBoneNode('head');
            const headPos = new THREE.Vector3();
            if (headBone) headBone.getWorldPosition(headPos);
            let sc = {x:0,y:0,z:0}, ss = {x:0,y:0,z:0};
            try {
                const sceneBox = new THREE.Box3().setFromObject(vrm.scene);
                sc = sceneBox.getCenter(new THREE.Vector3());
                ss = sceneBox.getSize(new THREE.Vector3());
            } catch(e) {}
            const cx = headBone ? headPos.x : (hips ? hipsPos.x : sc.x);
            const cz = headBone ? headPos.z : (hips ? hipsPos.z : sc.z);
            dist = 3;
            focalPoint.set(cx, sc.y + ss.y * 0.15, cz);
        }

        this.camera.position.set(focalPoint.x, focalPoint.y, focalPoint.z + dist);
        this.camera.lookAt(focalPoint);
        this.camera.updateProjectionMatrix();

        
        if (this._saccadeTarget) {
            this._saccadeTarget.position.set(0, 0, 0);
        }
    }

    getHeadScreenPosition() {
        if (!this.vrm?.humanoid) return null;
        const head = this.vrm.humanoid.getNormalizedBoneNode('head');
        if (!head) return null;
        const pos = new THREE.Vector3();
        head.getWorldPosition(pos);
        pos.y += 0.35;
        pos.project(this.camera);
        const w = this.renderer.domElement.clientWidth;
        const h = this.renderer.domElement.clientHeight;
        return {
            x: (pos.x * 0.5 + 0.5) * w,
            y: (-pos.y * 0.5 + 0.5) * h,
            visible: pos.z <= 1,
        };
    }

    onHeadPosition(callback) {
        this._headPositionListeners.push(callback);
    }

    _animate() {
        this._rafId = requestAnimationFrame(() => this._animate());
        const delta = this.clock.getDelta();

        if (this.vrm) {
            
            if (this._frequencyAnalyzerActive) {
                const visemeFrame = this.updateLipSync();
                if (visemeFrame) {
                    this.setViseme(visemeFrame);
                }
            } else {
                
                const lipSyncScale = this.currentEmotion === 'neutral' ? 0.5 : 0.25;
                this.vrm.expressionManager?.setValue('aa', this.mouthValue * lipSyncScale);
            }

            
            this._updateBlink(delta);

            
            
            const em = this.vrm.expressionManager;
            if (em) {
                for (const expr of (this._allExpressionNames || EXPRESSION_NAMES)) {
                    if (expr === 'aa' || expr === 'ih' || expr === 'ou' || expr === 'ee' || expr === 'oh') continue; 
                    const current = em.getValue(expr) || 0;
                    const target = this._targetExpressions[expr] || 0;
                    const blended = current + (target - current) * Math.min(1, delta * 5);
                    em.setValue(expr, blended);
                }
            }

            
            this._updateSaccade(delta);


            if (this._mixer) {
                this._mixer.update(delta);
            }

            this._animManager.update(delta);


            this._applyLookAtFallback();

            
            this.vrm.update(delta);

            // Subtle breathing animation
            this._applyBreathing(delta);


            const screenPos = this.getHeadScreenPosition();
            this._lastHeadScreenPos = screenPos;
            if (screenPos && this._headPositionListeners.length) {
                for (const cb of this._headPositionListeners) {
                    cb(screenPos);
                }
            }
        }

        try {
            this.renderer.render(this.scene, this.camera);
        } catch (e) {
            console.warn('[Avatar] render error:', e.message);
        }
        if (this._composer && this._postProcessingEnabled && this.scene) {
            try {
                this._composer.render();
            } catch (e) {
                console.warn('[Avatar] composer render error:', e.message);
            }
        }
    }

    /* ── Post-processing pipeline (SMAA, ACESFilmic tone mapping) ── */
    _initComposer() {
        if (this._isMobile || this.preview) return; // skip on mobile/preview
        try {
            const composer = new EffectComposer(this.renderer);
            const renderPass = new RenderPass(this.scene, this.camera);
            composer.addPass(renderPass);

            // Output pass handles color space conversion (ACESFilmic tone mapping)
            const outputPass = new OutputPass();
            composer.addPass(outputPass);

            this._composer = composer;
            this._postProcessingEnabled = true;
            console.debug('[Avatar] Post-processing initialized (ACESFilmic)');
        } catch (e) {
            console.warn('[Avatar] Post-processing not available:', e.message);
            this._composer = null;
        }
    }

    setBloom(_strength = 0.3, _radius = 0.5, _threshold = 0.2) {
        // Bloom removed — kept as no-op for API compatibility
    }

    _updateBlink(delta) {
        if (!this._blinkEnabled || !this.vrm?.expressionManager) return;

        // Halve blink check frequency on mobile for perf
        if (this._isMobile) delta *= 0.5;

        this._blinkTimer -= delta;
        if (this._blinkTimer > 0) return;

        const openMax = this._sleepBlinkOpenSec || BLINK_OPEN_MAX;

        if (this._blinkIsOpen) {
            this.vrm.expressionManager.setValue('blink', 1);
            this._blinkIsOpen = false;
            this._blinkTimer = BLINK_CLOSE_MAX;
        } else {
            this.vrm.expressionManager.setValue('blink', 0);
            this._blinkIsOpen = true;
            this._blinkTimer = openMax;
        }
    }

    
    _setBlinkEnabled(enabled) {
        this._blinkEnabled = enabled;
        if (!this._blinkIsOpen) {
            return this._blinkTimer; 
        }
        return 0;
    }

    _updateSaccade(delta) {
        if (this.preview) return;
        if (this._isMobile) return; // Skip saccade on mobile for perf
        this._saccadeTimer += delta;

        
        if (this._saccadeTimer > SACCADE_MIN_INTERVAL && Math.random() < SACCADE_PROC) {
            this._saccadeYaw = (Math.random() - 0.5) * 2 * SACCADE_RADIUS;
            this._saccadePitch = (Math.random() - 0.5) * 2 * SACCADE_RADIUS;
            this._saccadeTimer = 0;
        }

        
        const smoothFactor = 1 - Math.exp(-4 * delta);
        this._yawDamped += (this._saccadeYaw - this._yawDamped) * smoothFactor;
        this._pitchDamped += (this._saccadePitch - this._pitchDamped) * smoothFactor;

        
        
        
        if (this._saccadeTarget) {
            this._saccadeTarget.position.set(
                this._yawDamped * 0.1,
                this._pitchDamped * 0.1,
                this._saccadeTarget.position.z
            );
        }
    }

    /**
     * Apply subtle breathing animation using sine-wave on spine/chest/upperChest bones.
     */
    _applyBreathing(delta) {
        if (!this.vrm?.humanoid || !this._breathingEnabled) return;
        this._breathingPhase += delta * this._breathingSpeed;
        const breath = Math.sin(this._breathingPhase) * this._breathingAmplitude;
        const boneConfigs = [
            ['spine', 1.0],
            ['chest', 0.7],
            ['upperChest', 0.4],
        ];
        const rotation = new THREE.Quaternion();
        for (const [name, weight] of boneConfigs) {
            const bone = this.vrm.humanoid.getNormalizedBoneNode(name);
            if (!bone) continue;
            rotation.setFromEuler(new THREE.Euler(breath * weight, 0, 0));
            bone.quaternion.multiply(rotation);
        }
    }


    _applyLookAtFallback() {
        if (!this._lookAtFallback || !this.vrm?.humanoid || !this._saccadeTarget) return;

        const head = this.vrm.humanoid.getNormalizedBoneNode('head');
        if (!head) return;

        
        const animatedQuat = head.quaternion.clone();

        // Use touch look target if active, otherwise use saccade
        const lookSource = this._touchLookTarget || this._saccadeTarget;
        const targetPos = new THREE.Vector3();
        lookSource.getWorldPosition(targetPos);


        head.lookAt(targetPos);
        const lookAtQuat = head.quaternion.clone();

        // Reduce gaze follow strength when touch-look is active (smoother)
        const gazeStrength = this._touchLookTarget ? 0.4 : 0.25;
        head.quaternion.copy(animatedQuat).slerp(lookAtQuat, gazeStrength);
    }

    setEmotion(emotion) {
        // If VRM is not loaded yet, queue the emotion for later application
        if (!this.vrm || !this.vrm.expressionManager) {
            this._pendingEmotion = emotion;
            return;
        }

        const manager = this.vrm.expressionManager;

        // Step 1: Reset ALL known emotion expressions to 0 in both the
        // render-target table and the live VRM manager.
        for (const expr of (this._allExpressionNames || EXPRESSION_NAMES)) {
            this._targetExpressions[expr] = 0;
            try { manager.setValue(expr, 0); } catch (e) { /* not in this VRM */ }
        }

        // Step 2: Apply the target emotion using the first working candidate
        const candidates = EMOTION_CANDIDATES[emotion] || [emotion];
        let applied = false;
        if (emotion !== 'neutral') {
            for (const name of candidates) {
                if (name === null) continue;
                try {
                    manager.getValue(name); // throws if expression doesn't exist
                    this._targetExpressions[name] = 1.0;
                    manager.setValue(name, 1.0);
                    applied = true;
                    break;
                } catch (e) {
                    continue; // try next candidate
                }
            }
            if (!applied) {
                console.debug(`[Avatar] Expression '${emotion}' not found in this VRM model`);
            }
        }

        this.currentEmotion = emotion;

        // Step 3: Trigger procedural body animation based on emotion category
        this._playEmotionAnimation(emotion);

        // Step 4: Auto-reset to neutral after a delay
        if (this._emotionTimer) {
            clearTimeout(this._emotionTimer);
            this._emotionTimer = null;
        }
        if (this._emotionDuration > 0 && emotion !== 'neutral') {
            this._emotionTimer = setTimeout(() => {
                this.setEmotion('neutral');
                this._emotionTimer = null;
            }, this._emotionDuration);
        }
    }

    setExpression(name) {
        // Forward to setEmotion so all callers get the full 26-emotion system
        // with VRM expression candidate fallbacks.
        return this.setEmotion(name);
    }

    /**
     * Map extended emotions to procedural body animations.
     * Called by setEmotion() to add physical expressiveness beyond
     * VRM facial expression morphs.
     *
     * Categories:
     *   - sad/troubled/depressed → subtle nod
     *   - angry/frustrated/annoyed → slight forward lean
     *   - shy/embarrassed → head tilt down
     *   - excited/happy → bounce
     *   - bored/tired → slower idle (skip animation, handled by idle speed)
     *   - thinking → thinking pose
     */
    _playEmotionAnimation(emotion) {
        if (!this._animManager) return;

        switch (emotion) {
            // Subtle nod for sadness
            case 'sad':
            case 'troubled':
            case 'depressed':
                this._animManager.play('nod', { priority: ANIM_PRIORITY.LOW });
                break;
            // Slight forward lean for anger
            case 'angry':
            case 'frustrated':
            case 'annoyed':
                this._animManager.play('leanForward', { priority: ANIM_PRIORITY.LOW });
                break;
            // Head tilt down for shyness
            case 'shy':
            case 'embarrassed':
                this._animManager.play('headTiltDown', { priority: ANIM_PRIORITY.LOW });
                break;
            // Bounce for excitement
            case 'excited':
            case 'happy':
                this._animManager.play('excited', { priority: ANIM_PRIORITY.NORMAL });
                break;
            // Thinking pose
            case 'thinking':
                this._animManager.play('thinking', { priority: ANIM_PRIORITY.NORMAL });
                break;
            // bored/tired: no animation, idle manager handles slower breathing
            default:
                break;
        }
    }

    /* ── Animation convenience methods ───────────────────────────── */

    /**
     * Play a greeting (wave) animation.
     * HIGH priority — interrupts other non-idle animations.
     * Emotion is set to 'happy' during the gesture.
     */
    playGreeting() {
        this.setEmotion('happy');
        this._animManager.play('greeting', { priority: ANIM_PRIORITY.HIGH });
    }

    /** Play a nod animation (head pitch down-and-back). */
    playNod() {
        this._animManager.play('nod', { priority: ANIM_PRIORITY.NORMAL });
    }

    /**
     * Play a thinking pose (head tilt + lean forward).
     * Emotion is set to 'thinking' during the gesture.
     */
    playThinking() {
        this.setEmotion('thinking');
        this._animManager.play('thinking', { priority: ANIM_PRIORITY.NORMAL });
    }

    /**
     * Play an excited animation (bounce + torso rock).
     * HIGH priority — interrupts other non-idle animations.
     * Emotion is set to 'excited' during the gesture.
     */
    playExcited() {
        this.setEmotion('excited');
        this._animManager.play('excited', { priority: ANIM_PRIORITY.HIGH });
    }

    /**
     * Apply a mouth shape based on an ARPAbet phoneme code.
     * Called repeatedly during TTS playback to animate the avatar's mouth.
     *
     * Vowels → corresponding VRM viseme shape.
     * Consonants/silence → return mouth to near-closed (null).
     *
     * @param {string} arpabetCode - ARPAbet phoneme code (e.g. 'AA', 'IH', 'B')
     * @param {number} [intensity=0.7] - Mouth openness (0.0 to 1.0)
     */
    applyPhoneme(arpabetCode, intensity = 0.7) {
        // Maps ARPAbet phoneme codes to VRM mouth shape names.
        // VRM standard mouth shapes: aa, ih, ou, ee, oh
        // Consonants return null → mouth returns to near-closed
        const PHONEME_TO_VRM = {
            // Open vowels → 'aa' (wide open, as in "father")
            'AA': 'aa', 'AE': 'aa', 'AH': 'aa',
            // Front vowels → 'ih' (slightly open, as in "bit")
            'IH': 'ih', 'IY': 'ih', 'IX': 'ih',
            // Back/round vowels → 'ou' (rounded, as in "book")
            'OW': 'ou', 'OO': 'ou', 'UH': 'ou', 'UW': 'ou',
            // Mid vowels → 'ee' (spread lips, as in "say")
            'EH': 'ee', 'EY': 'ee', 'ER': 'ee',
            // Open-mid vowels → 'oh' (open-round, as in "thought")
            'AO': 'oh', 'AW': 'oh', 'OY': 'oh',
            // Consonants and silence → null (mouth nearly closed)
            'B': null, 'CH': null, 'D': null, 'DH': null, 'F': null,
            'G': null, 'HH': null, 'JH': null, 'K': null, 'L': null,
            'M': null, 'N': null, 'NG': null, 'P': null, 'R': null,
            'S': null, 'SH': null, 'T': null, 'TH': null, 'V': null,
            'W': null, 'WH': null, 'Y': null, 'Z': null, 'ZH': null,
        };

        const vrmShape = PHONEME_TO_VRM[arpabetCode.toUpperCase()];

        if (!vrmShape) {
            // Consonant or silence — close the mouth
            this._neutralizeMouth();
            return;
        }

        if (!this.vrm || !this.vrm.expressionManager) return;
        const manager = this.vrm.expressionManager;
        const ALL_MOUTH_SHAPES = ['aa', 'ih', 'ou', 'ee', 'oh'];

        // Apply the vowel shape, zero all other mouth shapes
        for (const shape of ALL_MOUTH_SHAPES) {
            const value = shape === vrmShape ? intensity : 0;
            try { manager.setValue(shape, value); } catch (e) { /* shape not in this VRM */ }
        }
    }

    /**
     * Reset all mouth expressions to zero (mouth closed).
     */
    _neutralizeMouth() {
        if (!this.vrm || !this.vrm.expressionManager) return;
        const manager = this.vrm.expressionManager;
        const ALL_MOUTH_SHAPES = ['aa', 'ih', 'ou', 'ee', 'oh'];
        for (const shape of ALL_MOUTH_SHAPES) {
            try { manager.setValue(shape, 0); } catch (e) { /* shape not in this VRM */ }
        }
    }

    setHalfBodyMode(enabled) {
        this._halfBody = !!enabled;
        if (this.camera && this.vrm) {
            const head = this.vrm.humanoid?.getRawBoneNode('head');
            if (!head) return;
            if (this._halfBody) {
                // Bust-shot: camera closer, aimed at chest/neck
                this.camera.position.set(0, head.position.y - 0.25, 0.8);
            } else {
                // Full body: pull back
                this.camera.position.set(0, head.position.y + 0.15, 1.8);
            }
            this.camera.lookAt(0, head.position.y - (this._halfBody ? 0.05 : 0.3), 0);
        }
    }

    setMouthOpen(value) {
        this.mouthValue = Math.min(1, Math.max(0, value));
    }

    startLipSync(audioContext, analyserNode, visemeSchedule = null) {
        this._audioContext = audioContext;
        // Try AdvancedLipSync first (formant-estimating), fall back to standard
        if (AdvancedLipSync) {
            this._lipsyncManager = new AdvancedLipSync(audioContext, analyserNode, {
                smoothingFrames: 3,
                fftSize: 1024,
            });
        } else {
            this._lipsyncManager = new AdaptiveLipsyncManager(audioContext, analyserNode);
        }
        if (visemeSchedule) {
            this._lipsyncManager.setSchedule(visemeSchedule);
        }
        this._frequencyAnalyzerActive = true;
    }

    stopLipSync() {
        this._frequencyAnalyzerActive = false;
        this.setMouthOpen(0);
    }

    
    setViseme(visemeFrame) {
        if (!visemeFrame || !this.vrm?.expressionManager) return;
        const em = this.vrm.expressionManager;
        const shape = visemeFrame.shape;
        const intensity = visemeFrame.intensity;

        
        
        const lipSyncScale = this.currentEmotion === 'neutral' ? 1.0 : 0.6;
        
        
        em.setValue('aa', shape.open * intensity * lipSyncScale);
        em.setValue('ih', (1 - shape.width) * 0.5 * intensity * lipSyncScale);
        em.setValue('ou', shape.round * intensity * lipSyncScale);
        em.setValue('ee', shape.width * 0.5 * intensity * lipSyncScale);
        em.setValue('oh', (shape.open * 0.5 + shape.round * 0.5) * intensity * lipSyncScale);
    }

    
    updateLipSync() {
        if (!this._lipsyncManager) return null;
        return this._lipsyncManager.analyze();
    }

    

    _setupHitAreas() {
        const canvas = this.renderer.domElement;
        canvas.style.cursor = 'pointer';
        this._boundClickHandler = (event) => this._onCanvasClick(event);
        canvas.addEventListener('pointerdown', this._boundClickHandler);
        // Touch-to-look: drive gaze from touch position
        this._boundTouchHandler = (event) => this._onCanvasTouch(event);
        canvas.addEventListener('touchstart', this._boundTouchHandler, { passive: true });
        canvas.addEventListener('touchmove', this._boundTouchHandler, { passive: true });
        canvas.addEventListener('touchend', () => {
            this._touchLookTarget = null;
        }, { passive: true });
    }

    _setupDragAndDrop() {
        const canvas = this.renderer.domElement;
        const container = this.container;

        // Create the drop zone overlay
        this._dropOverlay = document.createElement('div');
        this._dropOverlay.innerHTML = `
            <div class="vrm-drop-indicator" style="text-align:center;pointer-events:none">
                <span class="material-icons-round" style="font-size:3rem;display:block;margin-bottom:0.5rem">file_download</span>
                Drop VRM file here
            </div>
        `;
        Object.assign(this._dropOverlay.style, {
            position: 'absolute',
            top: '0',
            left: '0',
            width: '100%',
            height: '100%',
            display: 'none',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(0,0,0,0.55)',
            border: '3px dashed var(--accent, #6c5ce7)',
            color: '#fff',
            fontSize: '1.1rem',
            zIndex: '10',
            pointerEvents: 'none',
            boxSizing: 'border-box',
            fontFamily: 'system-ui, sans-serif',
            borderRadius: 'inherit',
        });
        container.appendChild(this._dropOverlay);

        // Bind handlers for cleanup
        this._boundDragOver = (e) => this._onDragOver(e);
        this._boundDragLeave = (e) => this._onDragLeave(e);
        this._boundDrop = (e) => this._onDrop(e);

        canvas.addEventListener('dragover', this._boundDragOver);
        canvas.addEventListener('dragleave', this._boundDragLeave);
        canvas.addEventListener('drop', this._boundDrop);
    }

    _onDragOver(e) {
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer) {
            e.dataTransfer.dropEffect = 'copy';
        }
        this._showDropOverlay();
    }

    _onDragLeave(e) {
        // Only hide when truly leaving the canvas area, not entering child elements
        if (!this.renderer.domElement.contains(e.relatedTarget)) {
            this._hideDropOverlay();
        }
    }

    _onDrop(e) {
        e.preventDefault();
        e.stopPropagation();
        this._hideDropOverlay();

        const files = e.dataTransfer?.files;
        if (!files || files.length === 0) return;

        const file = files[0];
        if (!file.name.toLowerCase().endsWith('.vrm')) {
            showToast('Please drop a .vrm file', 'warning', { suggestion: 'The dropped file must have a .vrm extension' });
            return;
        }

        const url = URL.createObjectURL(file);
        showToast(`Loading VRM: ${escHtml(file.name)}`, 'info');
        this.loadVRM(url);
    }

    _showDropOverlay() {
        if (this._dropOverlay) {
            this._dropOverlay.style.display = 'flex';
        }
    }

    _hideDropOverlay() {
        if (this._dropOverlay) {
            this._dropOverlay.style.display = 'none';
        }
    }

    _onCanvasClick(event) {
        if (!this.vrm?.humanoid || !this.ready) return;
        const rect = this.renderer.domElement.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        const y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        const raycaster = new THREE.Raycaster();
        raycaster.setFromCamera(new THREE.Vector2(x, y), this.camera);

        
        const meshes = [];
        this.vrm.scene.traverse((c) => { if (c.isMesh) meshes.push(c); });
        let hitPoint = null;
        if (meshes.length) {
            const intersects = raycaster.intersectObjects(meshes, false);
            if (intersects.length) hitPoint = intersects[0].point;
        }

        
        if (!hitPoint) {
            const head = this.vrm.humanoid.getNormalizedBoneNode('head');
            const hips = this.vrm.humanoid.getNormalizedBoneNode('hips');
            if (!head || !hips) return;

            const headPos = new THREE.Vector3();
            const hipsPos = new THREE.Vector3();
            head.getWorldPosition(headPos);
            hips.getWorldPosition(hipsPos);

            
            headPos.project(this.camera);
            hipsPos.project(this.camera);

            let hitArea;
            if (y > headPos.y - 0.03) hitArea = 'head';
            else if (y > hipsPos.y + 0.05) hitArea = 'chest';
            else if (y > hipsPos.y - 0.03) hitArea = 'groin';
            else hitArea = 'leg';

            this.playAnimation(`${BASE_URL}/characters/default/anim/hitarea_${hitArea}.vrma`);
            return;
        }

        this._playHitAreaAnimation(hitPoint);
    }

    /** Touch-to-look: derive a 3D gaze target from touch position */
    _onCanvasTouch(event) {
        if (!this.vrm?.humanoid || !this.ready) return;
        const touch = event.touches?.[0];
        if (!touch) { this._touchLookTarget = null; return; }
        const rect = this.renderer.domElement.getBoundingClientRect();
        const x = ((touch.clientX - rect.left) / rect.width) * 2 - 1;
        const y = -((touch.clientY - rect.top) / rect.height) * 2 + 1;

        // Project onto a plane at head height so the avatar "looks at" the finger
        const dir = new THREE.Vector3(x, y, 0.5).unproject(this.camera).sub(this.camera.position).normalize();
        const head = this.vrm.humanoid.getNormalizedBoneNode('head');
        if (!head) return;
        const headPos = new THREE.Vector3();
        head.getWorldPosition(headPos);
        const t = (headPos.y - this.camera.position.y) / dir.y;
        if (t > 0) {
            this._touchLookTarget = this.camera.position.clone().add(dir.multiplyScalar(t));
        }
    }

    _playHitAreaAnimation(point) {
        const head = this.vrm.humanoid.getNormalizedBoneNode('head');
        const hips = this.vrm.humanoid.getNormalizedBoneNode('hips');
        if (!head || !hips) return;

        const headPos = new THREE.Vector3();
        const hipsPos = new THREE.Vector3();
        head.getWorldPosition(headPos);
        hips.getWorldPosition(hipsPos);
        const hitY = point.y;

        let hitArea;
        if (hitY > headPos.y - 0.1) hitArea = 'head';
        else if (hitY > hipsPos.y + 0.3) hitArea = 'chest';
        else if (hitY > hipsPos.y - 0.1) hitArea = 'groin';
        else hitArea = 'leg';

        this.playAnimation(`${BASE_URL}/characters/default/anim/hitarea_${hitArea}.vrma`);
    }

    

    
    initIdleManager(options = {}) {
        if (this._idleManager) return;
        this._idleManager = new IdleManager(this, options);
    }

    _startIdleBehaviorLoop() {

        if (this._idleManager) return;
        // If a loaded idle animation is playing, skip micro-anims to prevent conflict
        if (this._idleAction) return;

        if (this._idleBehaviorTimer) clearTimeout(this._idleBehaviorTimer);
        const microAnims = ['curiosity', 'amusement', 'admiration', 'confusion'];
        const scheduleNext = () => {
            const delay = 8000 + Math.random() * 7000;
            this._idleBehaviorTimer = setTimeout(() => {
                if (!this.ready || this.currentEmotion !== 'neutral' || this._frequencyAnalyzerActive) {
                    scheduleNext();
                    return;
                }
                const anim = microAnims[Math.floor(Math.random() * microAnims.length)];
                this.playAnimation(`${BASE_URL}/characters/default/anim/${anim}.vrma`, () => {
                    if (this._idleAction) this._fadeToAction(this._idleAction, 1);
                    scheduleNext();
                });
            }, delay);
        };
        scheduleNext();
    }

    /* ---------- Life state machine (idle → bored → sleeping) ---------- */
    // Source: Amica's autonomous life states (idle→bored→sleeping)
    initLifeStateMachine() {
        this.lifeState = 'idle';   // idle | bored | sleeping
        this._boredTimer = 0;
        this._inactivityThreshold = 30000;  // 30 seconds → bored
        this._sleepThreshold = 300000;       // 5 minutes → sleeping
        this._lifeInterval = setInterval(() => this._updateLifeState(), 5000);
    }

    _updateLifeState() {
        if (this.lifeState === 'sleeping') return;
        if (this.lifeState === 'idle' && this._boredTimer >= this._inactivityThreshold) {
            this.lifeState = 'bored';
            this.setEmotion('bored');
            this._dispatchLifeEvent('bored');
        } else if (this.lifeState === 'bored' && this._boredTimer >= this._sleepThreshold) {
            this.lifeState = 'sleeping';
            this.setEmotion('sleep');
            this._dispatchLifeEvent('sleeping');
        }
        this._boredTimer += 5000;
    }

    _dispatchLifeEvent(event) {
        // Tell the backend the avatar is bored → backend can initiate conversation
        try {
            import('./modules/state.js').then(({ getWs }) => {
                const ws = getWs();
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({
                        type: 'avatar_life_event',
                        event: event,
                    }));
                }
            });
        } catch (_) {}
        // Also dispatch a DOM event so local components can react
        document.dispatchEvent(new CustomEvent('avatarLifeState', { detail: { event } }));
    }

    interact() {
        // User interaction resets the life state
        this._boredTimer = 0;
        this.lifeState = 'idle';
        this.setEmotion('neutral');
    }

    destroy() {
        // Cancel animation frame
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }
        // Clean up ResizeObserver
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
        // Remove visibility change listener
        if (this._visibilityHandler) {
            document.removeEventListener('visibilitychange', this._visibilityHandler);
            this._visibilityHandler = null;
        }
        // Remove pointer/touch handlers from renderer
        if (this._boundClickHandler && this.renderer) {
            this.renderer.domElement.removeEventListener('pointerdown', this._boundClickHandler);
            this._boundClickHandler = null;
        }
        if (this._boundTouchHandler && this.renderer) {
            this.renderer.domElement.removeEventListener('touchstart', this._boundTouchHandler);
            this.renderer.domElement.removeEventListener('touchmove', this._boundTouchHandler);
            this._boundTouchHandler = null;
        }
        this._touchLookTarget = null;
        // Remove drag-and-drop listeners and overlay
        if (this._boundDragOver && this.renderer) {
            this.renderer.domElement.removeEventListener('dragover', this._boundDragOver);
            this.renderer.domElement.removeEventListener('dragleave', this._boundDragLeave);
            this.renderer.domElement.removeEventListener('drop', this._boundDrop);
            this._boundDragOver = null;
            this._boundDragLeave = null;
            this._boundDrop = null;
        }
        if (this._dropOverlay && this._dropOverlay.parentNode) {
            this._dropOverlay.parentNode.removeChild(this._dropOverlay);
            this._dropOverlay = null;
        }
        // Clear emotion timer
        if (this._emotionTimer) {
            clearTimeout(this._emotionTimer);
            this._emotionTimer = null;
        }
        // Dispose VRM and scene objects
        if (this.vrm) {
            this.scene.remove(this.vrm.scene);
            VRMUtils.deepDispose(this.vrm.scene);
            this.vrm = null;
        }
        // Stop all animations
        if (this._mixer) {
            this._mixer.stopAllAction();
            this._mixer = null;
        }
        // Destroy idle manager
        if (this._idleManager) {
            this._idleManager.destroy();
            this._idleManager = null;
        }
        // Clear idle behavior timer
        if (this._idleBehaviorTimer) {
            clearTimeout(this._idleBehaviorTimer);
            this._idleBehaviorTimer = null;
        }
        // Destroy animation manager
        if (this._animManager) {
            this._animManager.destroy();
            this._animManager = null;
        }
        // Clean up lip-sync manager
        if (this._lipsyncManager) {
            this._lipsyncManager.destroy?.();
            this._lipsyncManager = null;
        }
        // Clean up life state machine
        if (this._lifeInterval) {
            clearInterval(this._lifeInterval);
            this._lifeInterval = null;
        }
        // Clean up post-processing composer
        if (this._composer) {
            this._composer.dispose();
            this._composer = null;
        }
        // Close audio context
        if (this._audioContext) {
            this._audioContext.close();
            this._audioContext = null;
        }
        // Remove saccade target from camera
        if (this._saccadeTarget && this.camera) {
            this.camera.remove(this._saccadeTarget);
            this._saccadeTarget = null;
        }
        // Dispose renderer
        if (this.renderer) {
            this.renderer.dispose();
            this.renderer = null;
        }
        // Clear container
        if (this.container) {
            this.container.innerHTML = '';
        }
    }
}

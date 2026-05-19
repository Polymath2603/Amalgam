

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { loadVRMAnimation } from '/static/vrm-animation.js';
import { FrequencyAnalyzer } from '/static/frequency-analyzer.js';

const EMOTION_TO_EXPRESSION = {
    neutral:    null,
    happy:      'happy',
    angry:      'angry',
    sad:        'sad',
    relaxed:    'relaxed',
    surprised:  'surprised',
    thinking:   'relaxed',
    speaking:   'happy',
    listening:  null,
    confused:   'surprised',
    shy:        'relaxed',
    jealous:    'angry',
    bored:      'relaxed',
    suspicious: 'angry',
    victory:    'happy',
    sleep:      'relaxed',
    love:       'happy',
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
        this.vrmPath = vrmPath || '/user_data/avatars/avatar.vrm';
        this.preview = options.preview || false;
        this.vrm = null;
        this.clock = new THREE.Clock();
        this.ready = false;
        this._initialGreetingPlayed = false;

        
        this.currentEmotion = 'neutral';
        this.mouthValue = 0;
        this._targetExpressions = {};
        for (const expr of EXPRESSION_NAMES) this._targetExpressions[expr] = 0;

        
        this._frequencyAnalyzer = null;
        this._audioContext = null;

        
        this._blinkTimer = BLINK_OPEN_MAX;
        this._blinkIsOpen = true;
        this._blinkEnabled = true;

        
        this._saccadeYaw = 0;
        this._saccadePitch = 0;
        this._saccadeTimer = 0;
        this._yawDamped = 0;
        this._pitchDamped = 0;

        
        this._mixer = null;
        this._currentAction = null;
        this._idleAction = null;
        this._animationQueue = [];

        
        this._lookAtFallback = false;

        
        this.renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
        const initW = this.container.clientWidth || 800;
        const initH = this.container.clientHeight || 600;
        this.renderer.setSize(initW, initH);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio * 2, 3));
        this.renderer.setClearColor(0x000000, 0);
        this.container.appendChild(this.renderer.domElement);

        
        const aspect = this.container.clientWidth / this.container.clientHeight || 1;
        this.camera = new THREE.PerspectiveCamera(this.preview ? 20 : 25, aspect, 0.1, 20);
        if (this.preview) {
            this.camera.position.set(0, 1.5, 1.2);
            this.camera.lookAt(0, 1.5, 0);
        } else {
            this.camera.position.set(0, 1.3, 3.2);
            this.camera.lookAt(0, 1.2, 0);
        }

        
        this.scene = new THREE.Scene();
        this.scene.add(this.camera);

        
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

        
        this._loadVRM();

        
        this._animate();
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
        this.vrmPath = newPath;
        this._loadVRM();
    }

    _loadVRM() {
        const loader = new GLTFLoader();
        loader.crossOrigin = 'anonymous';
        loader.register((parser) => new VRMLoaderPlugin(parser));

        const loadPath = this.vrmPath;
        const isFallback = loadPath === '/characters/default/model.vrm';
        let abandoned = false;

        
        const timeout = setTimeout(() => {
            console.warn(`VRM load timeout for ${loadPath} (30s)`);
            if (!isFallback) {
                console.warn('Falling back to default VRM');
                abandoned = true;
                this.vrmPath = '/characters/default/model.vrm';
                this._loadVRM();
            }
        }, 30000);

        loader.load(
            loadPath,
            async (gltf) => {
                if (abandoned) return;
                clearTimeout(timeout);

                const vrm = gltf.userData.vrm;
                if (!vrm) {
                    console.warn('No VRM data in loaded file');
                    if (!isFallback) {
                        console.warn('Falling back to default VRM');
                        this.vrmPath = '/characters/default/model.vrm';
                        this._loadVRM();
                    }
                    return;
                }

                VRMUtils.removeUnnecessaryVertices(gltf.scene);
                VRMUtils.combineSkeletons(gltf.scene);
                VRMUtils.combineMorphs(vrm);

                
                if (vrm.meta?.metaVersion === '0') {
                    vrm.scene.rotation.y = Math.PI;
                }
                vrm.scene.traverse((obj) => { obj.frustumCulled = false; });

                this.vrm = vrm;
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
                        const expr = expressionMap[name];
                        if (expr) vrm.expressionManager.registerExpression(expr);
                    });
                    
                    const presetNames = Object.keys(presetExpressionMap || {});
                    const customNames = Object.keys(expressionMap);
                    this._allExpressionNames = [...new Set([...presetNames, ...customNames, ...EXPRESSION_NAMES])];
                    console.log('[Avatar] Expressions available:', this._allExpressionNames);
                    console.log('[Avatar] Preset expressions:', presetNames);
                } else {
                    console.warn('[Avatar] No expressionManager found on VRM');
                }

                
                this._mixer = new THREE.AnimationMixer(vrm.scene);

                
                const hips = vrm.humanoid?.getNormalizedBoneNode('hips');
                this._baseHipsY = hips ? hips.position.y : 0;

                
                try {
                    this._fitCameraToModel(vrm);
                } catch(e) {
                    console.warn('Camera fit failed, using default position:', e);
                }

                this.ready = true;

                
                try {
                    await this._loadIdleAnimation();
                    
                    if (!this.preview && !this._initialGreetingPlayed) {
                        this._initialGreetingPlayed = true;
                        this.playAnimation('/static/animations/greeting.vrma');
                    }
                } catch(e) {
                    console.warn('VRMA animations not available, using procedural idle:', e);
                }

                console.log('VRM loaded:', vrm.meta?.title || 'Unknown', '| Path:', loadPath);
                console.log('VRM meta version:', vrm.meta?.metaVersion, '| Expressions:', this._allExpressionNames?.length || 0);
            },
            () => {},
            (error) => {
                if (abandoned) return;
                clearTimeout(timeout);
                console.error(`VRM load error for ${loadPath}:`, error);
                if (!isFallback) {
                    console.warn('Falling back to default VRM');
                    this.vrmPath = '/characters/default/model.vrm';
                    this._loadVRM();
                }
            }
        );
    }

    async _loadIdleAnimation() {
        const vrmAnim = await loadVRMAnimation('/static/animations/idle_loop.vrma');
        if (!vrmAnim || !this.vrm || !this._mixer) return;

        const clip = vrmAnim.createAnimationClip(this.vrm);
        this._idleAction = this._mixer.clipAction(clip);
        this._idleAction.loop = THREE.LoopRepeat;
        this._fadeToAction(this._idleAction, 0.5);
    }

    async playAnimation(url) {
        if (!this.vrm || !this._mixer || !this._idleAction) return;

        try {
            const vrmAnim = await loadVRMAnimation(url);
            if (!vrmAnim) return;

            const clip = vrmAnim.createAnimationClip(this.vrm);
            const action = this._mixer.clipAction(clip);
            action.clampWhenFinished = true;
            action.loop = THREE.LoopOnce;

            this._fadeToAction(action, 0.5);

            
            const restoreIdle = () => {
                this._mixer.removeEventListener('finished', restoreIdle);
                this._fadeToAction(this._idleAction, 1);
            };
            this._mixer.addEventListener('finished', restoreIdle);
        } catch(e) {
            console.warn('Animation load failed:', url, e);
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
        const targetY = box.max.y - upperHeight / 2;
        const fov = this.camera.fov * (Math.PI / 180);

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
                const headTop = headPos.y + 0.1;
                const headBottom = neckPos.y - 0.02;
                const headHeight = headTop - headBottom;
                const camZ = (headHeight * 0.65) / Math.tan(fov / 2);
                const midY = (headTop + headBottom) / 2;
                
                const isRotated = Math.abs(vrm.scene.rotation.y) > 0.1;
                const camOffsetZ = isRotated ? camZ : -camZ;
                
                const px = this.preview ? 0 : center.x;
                this.camera.position.set(px, midY, headPos.z + camOffsetZ);
                this.camera.lookAt(px, midY, headPos.z);
            } else {
                const previewTargetY = box.max.y - size.y * 0.15;
                const previewHeight = Math.max(size.y * 0.3, 0.15);
                const camZ = (previewHeight / 2) / Math.tan(fov / 2) * 1.3;
                const isRotated = Math.abs(vrm.scene.rotation.y) > 0.1;
                const camOffsetZ = isRotated ? Math.max(camZ, 0.5) : -Math.max(camZ, 0.5);
                const px = this.preview ? 0 : center.x;
                this.camera.position.set(px, previewTargetY, center.z + camOffsetZ);
                this.camera.lookAt(px, previewTargetY, center.z);
            }
        } else {
            const camZ = (upperHeight / 2) / Math.tan(fov / 2) * 1.3;
            const finalZ = Math.min(Math.max(camZ, 1.5), 10);
            const isRotated = Math.abs(vrm.scene.rotation.y) > 0.1;
            const camOffsetZ = isRotated ? finalZ : -finalZ;
            this.camera.position.set(center.x, center.y, center.z + camOffsetZ);
            this.camera.lookAt(center);
        }

        this.camera.updateProjectionMatrix();
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
                    if (target > 0 && Math.abs(current - target) > 0.01) {
                        if (!this._exprDebugLogged) {
                            console.log(`[Avatar] Blending ${expr}: ${current.toFixed(3)} → ${target.toFixed(3)}`);
                        }
                    }
                    const blended = current + (target - current) * Math.min(1, delta * 5);
                    em.setValue(expr, blended);
                }
                if (!this._exprDebugLogged) this._exprDebugLogged = true;
            }

            
            this._updateSaccade(delta);

            
            if (this._mixer) {
                this._mixer.update(delta);
            }

            
            this._applyLookAtFallback();

            
            this.vrm.update(delta);
        }

        this.renderer.render(this.scene, this.camera);
    }

    _updateBlink(delta) {
        if (!this._blinkEnabled || !this.vrm?.expressionManager) return;

        this._blinkTimer -= delta;
        if (this._blinkTimer > 0) return;

        if (this._blinkIsOpen) {
            this.vrm.expressionManager.setValue('blink', 1);
            this._blinkIsOpen = false;
            this._blinkTimer = BLINK_CLOSE_MAX;
        } else {
            this.vrm.expressionManager.setValue('blink', 0);
            this._blinkIsOpen = true;
            this._blinkTimer = BLINK_OPEN_MAX;
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
                -1 
            );
        }
    }

    
    _applyLookAtFallback() {
        if (!this._lookAtFallback || !this.vrm?.humanoid || !this._saccadeTarget) return;

        const head = this.vrm.humanoid.getNormalizedBoneNode('head');
        if (!head) return;

        
        const animatedQuat = head.quaternion.clone();

        
        const targetPos = new THREE.Vector3();
        this._saccadeTarget.getWorldPosition(targetPos);

        
        head.lookAt(targetPos);
        const lookAtQuat = head.quaternion.clone();

        
        head.quaternion.copy(animatedQuat).slerp(lookAtQuat, 0.25);
    }

    setEmotion(emotion) {
        this.currentEmotion = emotion;
        const em = this.vrm?.expressionManager;

        
        
        const lipSyncExprs = ['aa', 'ih', 'ou', 'ee', 'oh'];
        for (const expr of EXPRESSION_NAMES) {
            if (this._frequencyAnalyzerActive && lipSyncExprs.includes(expr)) continue;
            this._targetExpressions[expr] = 0;
            if (em) em.setValue(expr, 0);
        }

        if (emotion === 'neutral') {
            
            this._setBlinkEnabled(true);
            return;
        }

        
        
        let blinkDelay = 0;
        if (!this._frequencyAnalyzerActive) {
            blinkDelay = this._setBlinkEnabled(false);
        }
        const target = EMOTION_TO_EXPRESSION[emotion];
        console.log(`[Avatar] setEmotion: ${emotion} → target=${target}, blinkDelay=${blinkDelay.toFixed(2)}s, hasEM=${!!em}, names=${(this._allExpressionNames || EXPRESSION_NAMES).join(',')}`);
        if (target && em) {
            const value = emotion === 'surprised' ? 0.5 : 1.0;
            const apply = () => {
                if (this.currentEmotion !== emotion) return;
                this._targetExpressions[target] = value;
                
                em.setValue(target, value);
                console.log(`[Avatar] Expression set: ${target}=${value}, getValue=${em.getValue(target)}`);
            };
            if (blinkDelay > 0) {
                setTimeout(apply, blinkDelay * 1000);
            } else {
                apply();
            }
        }
    }

    setMouthOpen(value) {
        this.mouthValue = Math.min(1, Math.max(0, value));
    }

    
    setupFrequencyAnalyzer(audioContext, analyserNode) {
        this._audioContext = audioContext;
        this._frequencyAnalyzer = new FrequencyAnalyzer(analyserNode, audioContext.sampleRate);
        this._frequencyAnalyzerActive = true;
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
        if (!this._frequencyAnalyzer) return null;
        return this._frequencyAnalyzer.analyze();
    }

    destroy() {
        if (this._rafId) cancelAnimationFrame(this._rafId);
        if (this._resizeObserver) this._resizeObserver.disconnect();
        if (this.renderer) this.renderer.dispose();
        if (this.container) this.container.innerHTML = '';
    }
}

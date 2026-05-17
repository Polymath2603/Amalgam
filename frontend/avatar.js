

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { loadVRMAnimation } from '/static/vrm-animation.js';

const EMOTION_TO_EXPRESSION = {
    neutral:    null,
    happy:      'happy',
    angry:      'angry',
    sad:        'sad',
    relaxed:    'relaxed',
    surprised:  'surprised',
    thinking:   null,
    speaking:   'happy',
    listening:  null,
    confused:   'sad',
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

        
        this.currentEmotion = 'neutral';
        this.mouthValue = 0;
        this._targetExpressions = {};
        for (const expr of EXPRESSION_NAMES) this._targetExpressions[expr] = 0;

        
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

        
        this._lookAtTarget = new THREE.Object3D();
        this._lookAtTarget.position.set(0, 1.4, 2); 

        
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
            this.camera.position.set(0, 1.55, 1.4);
            this.camera.lookAt(0, 1.5, 0);
        } else {
            this.camera.position.set(0, 1.3, 3.2);
            this.camera.lookAt(0, 1.2, 0);
        }

        
        this.scene = new THREE.Scene();

        
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

        loader.load(
            this.vrmPath,
            async (gltf) => {
                const vrm = gltf.userData.vrm;
                if (!vrm) {
                    console.warn('No VRM data in loaded file');
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

                
                this._mixer = new THREE.AnimationMixer(vrm.scene);

                
                const lookAtTarget = new THREE.Object3D();
                this.camera.add(lookAtTarget);
                if (vrm.lookAt) vrm.lookAt.target = lookAtTarget;

                
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
                    
                    if (!this.preview) {
                        this.playAnimation('/static/animations/greeting.vrma');
                    }
                } catch(e) {
                    console.warn('VRMA animations not available, using procedural idle:', e);
                }

                console.log('VRM loaded:', vrm.meta?.title || 'Unknown');
            },
            () => {},
            (error) => {
                console.warn('VRM load error:', error?.message || error);
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
        if (box.isEmpty()) return;

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
            const previewTargetY = box.max.y - size.y * 0.15;
            const previewHeight = Math.max(size.y * 0.3, 0.15);
            const camZ = (previewHeight / 2) / Math.tan(fov / 2) * 1.3;
            this.camera.position.set(center.x, previewTargetY, center.z + Math.max(camZ, 0.5));
            this.camera.lookAt(center.x, previewTargetY, center.z);
        } else {
            const camZ = (upperHeight / 2) / Math.tan(fov / 2) * 1.3;
            const finalZ = Math.min(Math.max(camZ, 1.5), 10);
            this.camera.position.set(center.x, targetY, center.z + finalZ);
            this.camera.lookAt(center.x, targetY, center.z);
        }

        this.camera.updateProjectionMatrix();
    }

    _animate() {
        this._rafId = requestAnimationFrame(() => this._animate());
        const delta = this.clock.getDelta();

        if (this.vrm) {
            
            const lipSyncScale = this.currentEmotion === 'neutral' ? 0.5 : 0.25;
            this.vrm.expressionManager?.setValue('aa', this.mouthValue * lipSyncScale);

            
            this._updateBlink(delta);

            
            for (const expr of EXPRESSION_NAMES) {
                const em = this.vrm.expressionManager;
                if (!em) break;
                const current = em.getValue(expr) || 0;
                const target = this._targetExpressions[expr] || 0;
                const blended = current + (target - current) * Math.min(1, delta * 5);
                em.setValue(expr, blended);
            }

            
            this._updateSaccade(delta);

            
            if (this._mixer) {
                this._mixer.update(delta);
            }

            
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

    _updateSaccade(delta) {
        if (!this.vrm?.lookAt) return;

        this._saccadeTimer += delta;

        
        if (this._saccadeTimer > SACCADE_MIN_INTERVAL && Math.random() < SACCADE_PROC) {
            this._saccadeYaw = (Math.random() - 0.5) * 2 * SACCADE_RADIUS;
            this._saccadePitch = (Math.random() - 0.5) * 2 * SACCADE_RADIUS;
            this._saccadeTimer = 0;
        }

        
        const smoothFactor = 1 - Math.exp(-4 * delta);
        this._yawDamped += (this._saccadeYaw - this._yawDamped) * smoothFactor;
        this._pitchDamped += (this._saccadePitch - this._pitchDamped) * smoothFactor;

        
        const lookAt = this.vrm.lookAt;
        if (lookAt) {
            
            
            
            
            const fpBone = this.vrm.humanoid?.getNormalizedBoneNode('head');
            if (fpBone) {
                
                const headQuat = fpBone.quaternion.clone();
                
                const yawDeg = this._yawDamped * (180 / Math.PI);
                const pitchDeg = this._pitchDamped * (180 / Math.PI);
                
                if (lookAt.applier && typeof lookAt.applier.apply === 'function') {
                    lookAt.applier.apply(new THREE.Euler(pitchDeg, yawDeg, 0));
                }
            }
        }
    }

    setEmotion(emotion) {
        this.currentEmotion = emotion;

        
        this._blinkEnabled = (emotion === 'neutral');
        if (this._blinkEnabled && !this._blinkIsOpen) {
            
            this.vrm?.expressionManager?.setValue('blink', 0);
            this._blinkIsOpen = true;
            this._blinkTimer = BLINK_OPEN_MAX;
        }

        
        for (const expr of EXPRESSION_NAMES) {
            this._targetExpressions[expr] = 0;
        }
        const target = EMOTION_TO_EXPRESSION[emotion];
        if (target) {
            this._targetExpressions[target] = emotion === 'surprised' ? 0.5 : 1.0;
        }
    }

    setMouthOpen(value) {
        this.mouthValue = Math.min(1, Math.max(0, value));
    }

    destroy() {
        if (this._rafId) cancelAnimationFrame(this._rafId);
        if (this._resizeObserver) this._resizeObserver.disconnect();
        if (this.renderer) this.renderer.dispose();
        if (this.container) this.container.innerHTML = '';
    }
}

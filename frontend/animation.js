import * as THREE from 'three';
import { loadVRMAnimation } from '/static/vrm-animation.js';

export class AnimationManager {
    constructor(avatarRenderer) {
        this.avatar = avatarRenderer;
        this.state = 'idle'; 
        this.currentUrl = null;
        this.idleTimer = null;
        this.idlePool = [
            '/static/animations/idle_loop.vrma',
            '/static/animations/modelPose.vrma'
        ];
        
        this._currentAction = null;
        this._restoreIdleBound = this._restoreIdle.bind(this);
    }

    async play(url, isIdle = false) {
        if (!this.avatar.vrm || !this.avatar._mixer) return;
        
        this.stopIdleTimer();
        
        try {
            const vrmAnim = await loadVRMAnimation(url);
            if (!vrmAnim) return;
            
            
            if (!this.avatar.vrm || !this.avatar._mixer) return;

            const clip = vrmAnim.createAnimationClip(this.avatar.vrm);
            const action = this.avatar._mixer.clipAction(clip);
            
            if (isIdle) {
                action.loop = THREE.LoopRepeat;
                this.state = 'idle';
            } else {
                action.clampWhenFinished = true;
                action.loop = THREE.LoopOnce;
                this.state = 'playing';
            }
            
            this.currentUrl = url;
            this._fadeToAction(action, 0.5);
            
            
            this.avatar._mixer.removeEventListener('finished', this._restoreIdleBound);
            
            if (!isIdle) {
                this.avatar._mixer.addEventListener('finished', this._restoreIdleBound);
            } else {
                this.resetIdleTimer();
            }
        } catch (e) {
            console.warn('[AnimationManager] Play failed:', url, e);
            this._restoreIdle();
        }
    }

    _restoreIdle() {
        if (this.avatar._mixer) {
            this.avatar._mixer.removeEventListener('finished', this._restoreIdleBound);
        }
        this.play('/static/animations/idle_loop.vrma', true);
    }

    _fadeToAction(destAction, duration) {
        const prev = this._currentAction;
        this._currentAction = destAction;

        if (prev && prev !== destAction) {
            prev.fadeOut(duration);
        }
        destAction.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).fadeIn(duration).play();
    }

    onEmotion(emotion) {
        if (!emotion) return;
        const lowerEmotion = emotion.toLowerCase();
        
        if (lowerEmotion === 'surprised' || lowerEmotion === 'confused') {
            this.play('/static/animations/peaceSign.vrma');
        } else if (lowerEmotion === 'love') {
            this.play('/static/animations/peaceSign.vrma');
        } else if (lowerEmotion === 'victory') {
            this.play('/static/animations/dance.vrma');
        } else if (lowerEmotion === 'happy') {
            if (Math.random() < 0.3) {
                this.play('/static/animations/greeting.vrma');
            } else {
                this._restoreIdle();
            }
        } else if (lowerEmotion === 'sad' || lowerEmotion === 'angry') {
            
            this._restoreIdle();
        } else {
            this._restoreIdle();
        }
    }

    resetIdleTimer() {
        this.stopIdleTimer();
        this.idleTimer = setTimeout(() => {
            this.playRandomIdle();
        }, 30000);
    }

    stopIdleTimer() {
        if (this.idleTimer) {
            clearTimeout(this.idleTimer);
            this.idleTimer = null;
        }
    }

    playRandomIdle() {
        if (this.idlePool.length === 0) return;
        const randomAnim = this.idlePool[Math.floor(Math.random() * this.idlePool.length)];
        this.play(randomAnim, true);
    }

    startIdle() {
        this.play('/static/animations/idle_loop.vrma', true);
    }

    stopIdle() {
        this.stopIdleTimer();
        if (this._currentAction) {
            this._currentAction.stop();
            this._currentAction = null;
        }
        this.state = 'idle';
    }

    dispose() {
        this.stopIdle();
        if (this.avatar._mixer) {
            this.avatar._mixer.removeEventListener('finished', this._restoreIdleBound);
        }
    }
}

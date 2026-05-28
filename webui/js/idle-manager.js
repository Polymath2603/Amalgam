

const MICRO_ANIMS = ['curiosity', 'amusement', 'admiration', 'optimism', 'relief', 'realization', 'confusion'];

const DEFAULTS = {
    timeBeforeIdleSec: 30,
    timeToSleepSec: 120,
    minIntervalSec: 8,
    maxIntervalSec: 15,
    sleepBlinkOpenSec: 8,
};

export class IdleManager {
    
    constructor(avatar, options = {}) {
        this._avatar = avatar;
        this._enabled = options.enabled !== false;
        this._timeBeforeIdle = (options.timeBeforeIdleSec || DEFAULTS.timeBeforeIdleSec) * 1000;
        this._timeToSleep = (options.timeToSleepSec || DEFAULTS.timeToSleepSec) * 1000;
        this._minInterval = (options.minIntervalSec || DEFAULTS.minIntervalSec) * 1000;
        this._maxInterval = (options.maxIntervalSec || DEFAULTS.maxIntervalSec) * 1000;
        this._sleepBlinkOpenSec = options.sleepBlinkOpenSec || DEFAULTS.sleepBlinkOpenSec;
        this._baseUrl = options.baseUrl || '';

        this._onRequestIdlePrompt = options.onRequestIdlePrompt || (() => {});
        this._onSleep = options.onSleep || (() => {});
        this._onWake = options.onWake || (() => {});

        
        this.state = 'ACTIVE';

        this._idleTimer = null;
        this._sleepTimer = null;
        this._eventTimer = null;
    }

    

    
    activate() {
        if (!this._enabled) return;
        this._clearAllTimers();
        const prev = this.state;
        this.state = 'ACTIVE';
        if (prev === 'SLEEPING') {
            this._exitSleep();
        }
    }

    
    deactivate() {
        if (!this._enabled) return;
        if (this.state !== 'ACTIVE') return;
        this._clearAllTimers();
        this._idleTimer = setTimeout(() => this._enterIdle(), this._timeBeforeIdle);
    }

    
    wake() {
        if (!this._enabled) return;
        if (this.state === 'ACTIVE') return;
        this._clearAllTimers();
        const prev = this.state;
        this.state = 'ACTIVE';
        if (prev === 'SLEEPING') {
            this._exitSleep();
        }
    }

    
    configure(options = {}) {
        if (options.timeBeforeIdleSec !== undefined) this._timeBeforeIdle = options.timeBeforeIdleSec * 1000;
        if (options.timeToSleepSec !== undefined) this._timeToSleep = options.timeToSleepSec * 1000;
        if (options.minIntervalSec !== undefined) this._minInterval = options.minIntervalSec * 1000;
        if (options.maxIntervalSec !== undefined) this._maxInterval = options.maxIntervalSec * 1000;
        if (options.enabled !== undefined) this._enabled = options.enabled;
    }

    destroy() {
        this._clearAllTimers();
        this._restoreBlink();
    }

    

    _enterIdle() {
        this.state = 'IDLE';
        this._scheduleNextEvent();
        this._sleepTimer = setTimeout(() => this._enterSleep(), this._timeToSleep);
    }

    _enterSleep() {
        this.state = 'SLEEPING';
        this._clearEventTimer();
        
        if (this._avatar) {
            this._avatar._sleepBlinkOpenSec = this._sleepBlinkOpenSec;
        }
        this._onSleep();
        
        this._scheduleNextEvent();
    }

    _exitSleep() {
        this._restoreBlink();
        this._onWake();
        
        if (this._avatar) {
            this._avatar.setEmotion('relaxed');
            setTimeout(() => {
                if (this.state === 'ACTIVE' && this._avatar) {
                    this._avatar.setEmotion('neutral');
                }
            }, 2000);
        }
    }

    _restoreBlink() {
        if (this._avatar) {
            this._avatar._sleepBlinkOpenSec = null;
        }
    }

    

    _scheduleNextEvent() {
        this._clearEventTimer();
        const jitter = Math.random() * (this._maxInterval - this._minInterval);
        const delay = this._minInterval + jitter;
        
        const multiplier = this.state === 'SLEEPING' ? 2 : 1;
        this._eventTimer = setTimeout(() => this._processQueue(), delay * multiplier);
    }

    _processQueue() {
        if (this.state === 'ACTIVE') return;
        if (!this._avatar || !this._avatar.ready) {
            this._scheduleNextEvent();
            return;
        }
        
        if (this._avatar._frequencyAnalyzerActive) {
            this._scheduleNextEvent();
            return;
        }
        
        if (this._avatar.currentEmotion && this._avatar.currentEmotion !== 'neutral') {
            this._scheduleNextEvent();
            return;
        }

        
        if (Math.random() < 0.25) {
            this._scheduleNextEvent();
            return;
        }

        if (this.state === 'SLEEPING') {
            
            if (Math.random() < 0.05) {
                this._requestIdlePrompt();
            }
        } else {
            
            const roll = Math.random();
            if (roll < 0.75) {
                this._playMicroAnimation();
            } else {
                this._requestIdlePrompt();
            }
        }

        this._scheduleNextEvent();
    }

    

    _playMicroAnimation() {
        if (!this._avatar) return;
        const anim = MICRO_ANIMS[Math.floor(Math.random() * MICRO_ANIMS.length)];
        const url = `${this._baseUrl}/characters/default/anim/${anim}.vrma`;
        this._avatar.playAnimation(url);
    }

    _requestIdlePrompt() {
        this._onRequestIdlePrompt();
    }

    

    _clearEventTimer() {
        if (this._eventTimer) {
            clearTimeout(this._eventTimer);
            this._eventTimer = null;
        }
    }

    _clearAllTimers() {
        if (this._idleTimer) { clearTimeout(this._idleTimer); this._idleTimer = null; }
        if (this._sleepTimer) { clearTimeout(this._sleepTimer); this._sleepTimer = null; }
        this._clearEventTimer();
    }
}

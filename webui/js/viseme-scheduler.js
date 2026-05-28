

import {
    VISEME_SHAPES,
    EXTENDED_TO_SIMPLE,
    getTransitionWeight,
    interpolateShapes,
} from './visemes.js';

const TRANSITION_DURATION = 0.06; 

export class VisemeScheduler {
    
    constructor(audioContext) {
        this._audioContext = audioContext;
        this._schedule = [];
        this._startTime = 0;
        this._activeIndex = -1;
        this._prevViseme = 'sil';
        this._transitionStart = 0;
        this._frame = 0;
    }

    
    setSchedule(schedule) {
        this._schedule = schedule || [];
        this._startTime = this._audioContext.currentTime;
        this._activeIndex = -1;
        this._prevViseme = 'sil';
        this._transitionStart = 0;
        this._frame = 0;
    }

    
    analyze() {
        if (!this._schedule.length) return null;

        const elapsed = this._audioContext.currentTime - this._startTime;
        this._frame++;

        
        let active = null;
        let activeIdx = -1;
        for (let i = 0; i < this._schedule.length; i++) {
            const entry = this._schedule[i];
            if (elapsed >= entry.start && elapsed < entry.start + entry.duration) {
                active = entry;
                activeIdx = i;
                break;
            }
        }

        
        if (!active) {
            
            const last = this._schedule[this._schedule.length - 1];
            if (elapsed >= last.start + last.duration) {
                return this._makeFrame('sil', 0);
            }
            
            if (elapsed < this._schedule[0].start) {
                return this._makeFrame('sil', 0);
            }
            
            return this._makeFrame('sil', 0.1);
        }

        
        if (activeIdx !== this._activeIndex) {
            if (this._activeIndex >= 0) {
                this._prevViseme = this._schedule[this._activeIndex].viseme;
                this._transitionStart = elapsed;
            }
            this._activeIndex = activeIdx;
        }

        const currentViseme = active.viseme;

        
        const transitionElapsed = elapsed - this._transitionStart;
        const weight = getTransitionWeight(this._prevViseme, currentViseme);
        const transitionDuration = TRANSITION_DURATION * (1 + weight);
        const t = Math.min(transitionElapsed / transitionDuration, 1);

        
        const shape = interpolateShapes(this._prevViseme, currentViseme, t);
        const shapeDef = VISEME_SHAPES[currentViseme] || VISEME_SHAPES.sil;
        const intensity = shapeDef.open > 0 ? 0.7 + shapeDef.open * 0.3 : 0.1;

        return {
            viseme: currentViseme,
            simpleViseme: EXTENDED_TO_SIMPLE[currentViseme] || 'A',
            intensity,
            confidence: 1.0,
            amplitude: shape.open,
            bands: null,
            shape,
            transition: {
                from: this._prevViseme,
                to: currentViseme,
                progress: t,
            },
            frame: this._frame,
        };
    }

    
    reset() {
        this._schedule = [];
        this._startTime = 0;
        this._activeIndex = -1;
        this._prevViseme = 'sil';
        this._transitionStart = 0;
        this._frame = 0;
    }

    
    _makeFrame(viseme, intensity) {
        const shape = VISEME_SHAPES[viseme] || VISEME_SHAPES.sil;
        return {
            viseme,
            simpleViseme: EXTENDED_TO_SIMPLE[viseme] || 'A',
            intensity,
            confidence: 1.0,
            amplitude: shape.open,
            bands: null,
            shape: { ...shape },
            transition: { from: viseme, to: viseme, progress: 1 },
            frame: this._frame,
        };
    }
}

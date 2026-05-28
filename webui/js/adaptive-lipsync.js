

import { FrequencyAnalyzer } from './frequency-analyzer.js';
import { VisemeScheduler } from './viseme-scheduler.js';

export class AdaptiveLipsyncManager {
    
    constructor(audioContext, analyserNode) {
        this._audioContext = audioContext;
        this._analyserNode = analyserNode;
        this._scheduler = new VisemeScheduler(audioContext);
        this._analyzer = new FrequencyAnalyzer(analyserNode, audioContext.sampleRate);
        this._useScheduler = false;
    }

    
    setSchedule(schedule) {
        if (schedule && schedule.length > 0) {
            this._scheduler.setSchedule(schedule);
            this._useScheduler = true;
        } else {
            this._useScheduler = false;
        }
    }

    
    analyze() {
        if (this._useScheduler) {
            return this._scheduler.analyze();
        }
        return this._analyzer.analyze();
    }

    
    reset() {
        this._scheduler.reset();
        this._analyzer.reset();
        this._useScheduler = false;
    }
}

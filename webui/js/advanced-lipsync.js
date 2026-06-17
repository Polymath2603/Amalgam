/*
 * AdvancedLipSync — formant-estimating lipsync with coarticulation smoothing.
 * Extends AdaptiveLipsyncManager with formant tracking, viseme interpolation,
 * and phoneme-to-viseme mapping for more natural mouth movement.
 *
 * Source: ULTIMATE_AI_AVATAR Part 2 — AdvancedLipSync.
 */
import { FrequencyAnalyzer } from './frequency-analyzer.js';
import { VisemeScheduler } from './viseme-scheduler.js';

/* Phoneme-to-viseme mapping — maps ARPAbet phonemes to mouth shapes */
const PHONEME_TO_VISEME = {
    'AA': 'A', 'AE': 'A', 'AH': 'A', 'AO': 'O',
    'AW': 'O', 'AY': 'I', 'B': 'M', 'CH': 'C',
    'D': 'D', 'DH': 'D', 'EH': 'E', 'ER': 'R',
    'EY': 'I', 'F': 'F', 'G': 'C', 'HH': 'H',
    'IH': 'I', 'IY': 'I', 'JH': 'C', 'K': 'C',
    'L': 'L', 'M': 'M', 'N': 'N', 'NG': 'N',
    'OW': 'O', 'OY': 'O', 'P': 'M', 'R': 'R',
    'S': 'C', 'SH': 'C', 'T': 'D', 'TH': 'C',
    'UH': 'U', 'UW': 'U', 'V': 'F', 'W': 'U',
    'Y': 'I', 'Z': 'C', 'ZH': 'C',
};

/* Viseme → mouth openness (0 = closed, 1 = wide open) */
const VISEME_OPENNESS = {
    'A': 0.9, 'I': 0.7, 'U': 0.4, 'E': 0.6, 'O': 0.5,
    'M': 0.0, 'F': 0.1, 'C': 0.2, 'D': 0.1, 'N': 0.1,
    'L': 0.2, 'R': 0.15, 'H': 0.3,
};

/* 4-formant frequency ranges in Hz (for vowel estimation) */
const FORMANTS = {
    F1: { min: 200, max: 900 },
    F2: { min: 600, max: 2800 },
    F3: { min: 1400, max: 3400 },
    F4: { min: 2500, max: 4500 },
};

export class AdvancedLipSync {
    constructor(audioContext, analyserNode, options = {}) {
        this._audioContext = audioContext;
        this._analyserNode = analyserNode;
        this._scheduler = new VisemeScheduler(audioContext);
        this._analyzer = new FrequencyAnalyzer(analyserNode, audioContext.sampleRate);
        this._useScheduler = false;

        // Coarticulation smoothing
        this._smoothingFrames = options.smoothingFrames || 3;
        this._history = [];
        this._lastViseme = 'M';

        // Formant estimation state
        this._fftSize = options.fftSize || 1024;
        this._formantHistory = [];

        console.log('[AdvancedLipSync] Initialized with formant estimation + coarticulation smoothing');
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

        const base = this._analyzer.analyze();
        const formantViseme = this._estimateFormants();
        const blended = this._blendVisemes(base?.viseme || 'M', formantViseme);

        return {
            viseme: blended,
            mouthOpen: VISEME_OPENNESS[blended] ?? 0.3,
            intensity: base?.intensity || 0.3,
        };
    }

    /* ── Formant estimation ───────────────────────────────────── */
    _estimateFormants() {
        const bufferLength = this._analyserNode.frequencyBinCount;
        const data = new Float32Array(bufferLength);
        this._analyserNode.getFloatFrequencyData(data);
        const sampleRate = this._audioContext.sampleRate;

        // Convert to magnitude
        const magnitudes = new Float32Array(bufferLength);
        for (let i = 0; i < bufferLength; i++) {
            magnitudes[i] = Math.pow(10, data[i] / 20);
        }

        // Detect formant peaks across the 4 formant ranges
        const formants = {};
        for (const [name, range] of Object.entries(FORMANTS)) {
            const startBin = Math.floor(range.min / (sampleRate / 2) * bufferLength);
            const endBin = Math.ceil(range.max / (sampleRate / 2) * bufferLength);
            let peakFreq = 0, peakMag = 0;
            for (let i = startBin; i < endBin && i < bufferLength; i++) {
                if (magnitudes[i] > peakMag) {
                    peakMag = magnitudes[i];
                    peakFreq = i / bufferLength * sampleRate / 2;
                }
            }
            formants[name] = peakFreq;
        }

        this._formantHistory.push(formants);
        if (this._formantHistory.length > 5) {
            this._formantHistory.shift();
        }

        return this._formantToViseme(formants);
    }

    _formantToViseme(formants) {
        const f1 = formants.F1 || 500;
        const f2 = formants.F2 || 1500;

        // Vowel triangle classification
        if (f1 > 600 && f2 > 1800) return 'A';   // [æ] as in "cat"
        if (f1 > 500 && f2 < 1200) return 'O';    // [ɔ] as in "thought"
        if (f1 > 400 && f1 < 600 && f2 > 2000) return 'I'; // [i] as in "see"
        if (f1 > 350 && f1 < 550 && f2 < 1000) return 'U'; // [u] as in "blue"
        if (f1 > 500 && f2 > 1500) return 'E';     // [ɛ] as in "bed"
        return this._lastViseme;  // Consonant or silence — stick with last
    }

    /* ── Coarticulation smoothing ─────────────────────────────── */
    _blendVisemes(freqViseme, formantViseme) {
        const now = formantViseme || freqViseme || 'M';

        this._history.push(now);
        if (this._history.length > this._smoothingFrames) {
            this._history.shift();
        }

        // Majority vote with recency bias
        const counts = {};
        for (let i = 0; i < this._history.length; i++) {
            const v = this._history[i];
            counts[v] = (counts[v] || 0) + 1 + (i === this._history.length - 1 ? 1 : 0);
        }

        let best = now;
        let bestCount = 0;
        for (const [v, c] of Object.entries(counts)) {
            if (c > bestCount) {
                bestCount = c;
                best = v;
            }
        }

        this._lastViseme = best;
        return best;
    }

    reset() {
        this._scheduler.reset();
        this._analyzer.reset();
        this._history = [];
        this._formantHistory = [];
        this._useScheduler = false;
        this._lastViseme = 'M';
    }

    destroy() {
        this.reset();
    }
}

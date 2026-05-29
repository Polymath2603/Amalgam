

import {
  calculateRMS,
  extractBandEnergies,
  smoothValue,
  clamp,
} from './audio-utils.js';

import { VISEME_SHAPES, EXTENDED_TO_SIMPLE, getTransitionWeight } from './visemes.js';


const DEFAULTS = {
  fftSize: 256,
  silenceThreshold: 0.015,
  silenceHysteresis: 0.03,    
  smoothingFactor: 0.35,
  holdFrames: 3,               
  intensitySmoothing: 0.15,    
  transitionRate: 0.25,        
  energySmoothing: 0.5,
};

export class FrequencyAnalyzer {
  
  constructor(analyserNode, sampleRate, options = {}) {
    this.analyser = analyserNode;
    this.sampleRate = sampleRate;
    this.opts = { ...DEFAULTS, ...options };

    
    this.analyser.fftSize = this.opts.fftSize;
    this.analyser.smoothingTimeConstant = this.opts.energySmoothing;

    
    this.timeDomainData = new Uint8Array(this.analyser.fftSize);
    this.frequencyData = new Uint8Array(this.analyser.frequencyBinCount);

    
    this._currentViseme = 'sil';
    this._currentIntensity = 0;
    this._holdCounter = 0;
    this._smoothedAmplitude = 0;
    this._smoothedBands = { sub: 0, low: 0, mid: 0, high: 0, veryHigh: 0 };
    this._previousViseme = 'sil';
    this._transitionProgress = 1; 
    this._frameCount = 0;
    this._silenceRelease = 0; 
  }

  
  analyze() {
    this._frameCount++;

    
    this.analyser.getByteTimeDomainData(this.timeDomainData);
    this.analyser.getByteFrequencyData(this.frequencyData);

    const rawAmplitude = calculateRMS(this.timeDomainData, true);
    this._smoothedAmplitude = smoothValue(
      this._smoothedAmplitude,
      rawAmplitude,
      this.opts.smoothingFactor
    );

    
    const rawBands = extractBandEnergies(this.frequencyData, this.sampleRate);
    for (const key of Object.keys(rawBands)) {
      this._smoothedBands[key] = smoothValue(
        this._smoothedBands[key] || 0,
        rawBands[key],
        this.opts.smoothingFactor
      );
    }
    const bands = this._smoothedBands;

    
    const wasSilent = this._currentViseme === 'sil';
    const threshold = wasSilent ? this.opts.silenceHysteresis : this.opts.silenceThreshold;
    if (this._smoothedAmplitude < threshold) {
      this._silenceRelease = Math.min(this._silenceRelease + 1, 10);
      if (this._silenceRelease >= 3) {
        return this._emitViseme('sil', 0, bands);
      }
    } else {
      this._silenceRelease = 0;
    }

    
    const nyquist = this.sampleRate / 2;
    const emphasis = new Uint8Array(this.frequencyData.length);
    for (let i = 0; i < this.frequencyData.length; i++) {
      const freq = (i / this.frequencyData.length) * nyquist;
      const gain = 1 + 0.4 * (freq / nyquist);
      emphasis[i] = Math.min(255, Math.round(this.frequencyData[i] * gain));
    }
    const emphasisBands = extractBandEnergies(emphasis, this.sampleRate);
    for (const key of Object.keys(emphasisBands)) {
      if (key === 'high' || key === 'veryHigh') {
        bands[key] = smoothValue(bands[key], emphasisBands[key], 0.3);
      }
    }

    
    const intensity = clamp(this._smoothedAmplitude * 3, 0, 1);
    const { viseme, confidence } = this._classifyViseme(bands, intensity);

    
    if (viseme !== this._currentViseme) {
      this._holdCounter++;
      if (this._holdCounter < this.opts.holdFrames) {
        
        return this._emitViseme(this._currentViseme, intensity, bands);
      }
      this._holdCounter = 0;
    } else {
      this._holdCounter = 0;
    }

    return this._emitViseme(viseme, intensity, bands, confidence);
  }

  
  _classifyViseme(bands, intensity) {
    const { sub, low, mid, high, veryHigh } = bands;
    const totalEnergy = sub + low + mid + high + veryHigh;

    if (totalEnergy < 0.01) {
      return { viseme: 'sil', confidence: 0.9 };
    }

    
    const sibilantScore = (high + veryHigh) / (totalEnergy + 0.001);
    if (sibilantScore > 0.55 && high > 0.15) {
      if (veryHigh > high * 0.8) {
        return { viseme: 'SS', confidence: sibilantScore };
      }
      return { viseme: 'CH', confidence: sibilantScore * 0.85 };
    }

    
    const fricativeScore = (mid + high) / (totalEnergy + 0.001);
    if (fricativeScore > 0.5 && high > 0.1 && low < 0.15) {
      return { viseme: 'FF', confidence: fricativeScore * 0.8 };
    }

    
    
    const flatness = 1 - Math.abs(high - low) / (totalEnergy + 0.001);
    if (intensity > 0.6 && flatness > 0.7 && this._smoothedAmplitude > 0.08) {
      if (low > mid) {
        return { viseme: 'PP', confidence: 0.6 };
      }
      return { viseme: 'DD', confidence: 0.6 };
    }

    
    if (sub > 0.2 && low > 0.15 && high < 0.08 && mid < low * 0.7) {
      return { viseme: 'nn', confidence: 0.65 };
    }

    
    

    
    if (low > 0.2 && mid > 0.15 && intensity > 0.5) {
      return { viseme: 'aa', confidence: 0.7 };
    }

    
    if (mid > low && mid > 0.15 && intensity > 0.3) {
      return { viseme: 'E', confidence: 0.65 };
    }

    
    if (sub > mid && low > mid && intensity > 0.3) {
      return { viseme: 'O', confidence: 0.6 };
    }

    
    if (mid > 0.1 && high > low * 0.5 && intensity > 0.2) {
      return { viseme: 'I', confidence: 0.55 };
    }

    
    if (sub > 0.15 && high < 0.05) {
      return { viseme: 'U', confidence: 0.5 };
    }

    
    if (intensity > 0.5) return { viseme: 'aa', confidence: 0.4 };
    if (intensity > 0.3) return { viseme: 'E', confidence: 0.35 };
    if (intensity > 0.15) return { viseme: 'I', confidence: 0.3 };
    return { viseme: 'sil', confidence: 0.5 };
  }

  
  _emitViseme(viseme, intensity, bands, confidence = 0.5) {
    
    if (viseme !== this._currentViseme) {
      this._previousViseme = this._currentViseme;
      this._currentViseme = viseme;
      this._transitionProgress = 0;
    } else {
      
      const weight = getTransitionWeight(this._previousViseme, this._currentViseme);
      this._transitionProgress = Math.min(1, this._transitionProgress + this.opts.transitionRate * (1 - weight * 0.5));
    }

    
    this._currentIntensity = smoothValue(
      this._currentIntensity,
      intensity,
      this.opts.intensitySmoothing
    );

    
    const prevShape = VISEME_SHAPES[this._previousViseme] || VISEME_SHAPES.sil;
    const currShape = VISEME_SHAPES[this._currentViseme] || VISEME_SHAPES.sil;
    const t = this._transitionProgress;

    return {
      viseme: this._currentViseme,
      simpleViseme: EXTENDED_TO_SIMPLE[this._currentViseme] || 'A',
      intensity: this._currentIntensity,
      confidence,
      amplitude: this._smoothedAmplitude,
      bands: { ...this._smoothedBands },
      shape: {
        open:  prevShape.open  + (currShape.open  - prevShape.open)  * t,
        width: prevShape.width + (currShape.width - prevShape.width) * t,
        round: prevShape.round + (currShape.round - prevShape.round) * t,
      },
      transition: {
        from: this._previousViseme,
        to: this._currentViseme,
        progress: this._transitionProgress,
      },
      frame: this._frameCount,
    };
  }

  
  reset() {
    this._currentViseme = 'sil';
    this._currentIntensity = 0;
    this._holdCounter = 0;
    this._smoothedAmplitude = 0;
    this._smoothedBands = { sub: 0, low: 0, mid: 0, high: 0, veryHigh: 0 };
    this._previousViseme = 'sil';
    this._transitionProgress = 1;
    this._frameCount = 0;
  }
}



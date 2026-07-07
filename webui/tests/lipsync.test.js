/**
 * Real tests for the lipsync stack: visemes.js, audio-utils.js,
 * frequency-analyzer.js, viseme-scheduler.js, adaptive-lipsync.js, and
 * advanced-lipsync.js. Every test below imports and exercises the actual
 * production module — none of this redefines the logic locally.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  EXTENDED_VISEMES, SIMPLE_VISEMES, EXTENDED_TO_SIMPLE, PHONEME_TO_VISEME,
  VISEME_SHAPES, getTransitionWeight, interpolateShapes,
} from '../js/visemes.js';
import {
  int16ToFloat32, float32ToInt16, calculateRMS, zeroCrossingRate,
  extractBandEnergies, smoothValue, lerp, clamp, resample,
} from '../js/audio-utils.js';
import { FrequencyAnalyzer } from '../js/frequency-analyzer.js';
import { VisemeScheduler } from '../js/viseme-scheduler.js';
import { AdaptiveLipsyncManager } from '../js/adaptive-lipsync.js';
import { AdvancedLipSync } from '../js/advanced-lipsync.js';

function makeFakeAnalyser({ time = 128, freq = 0 } = {}) {
  return {
    fftSize: 1024,
    frequencyBinCount: 512,
    smoothingTimeConstant: 0,
    getByteTimeDomainData(arr) {
      arr.fill(time);
    },
    getByteFrequencyData(arr) {
      arr.fill(freq);
    },
    getFloatFrequencyData(arr) {
      arr.fill(-100);
    },
  };
}
const fakeAudioContext = (t = 0) => ({ sampleRate: 44100, currentTime: t });

describe('visemes.js', () => {
  it('every SIMPLE_VISEMES extendedMap entry points at a real EXTENDED_VISEMES key', () => {
    for (const def of Object.values(SIMPLE_VISEMES)) {
      for (const ext of def.extendedMap) {
        expect(EXTENDED_VISEMES[ext]).toBeDefined();
      }
    }
  });

  it('EXTENDED_TO_SIMPLE covers every extended viseme via the simple map', () => {
    for (const ext of Object.keys(EXTENDED_VISEMES)) {
      if (ext === 'sil') continue; // sil intentionally maps via SIMPLE_VISEMES.A's extendedMap
      expect(EXTENDED_TO_SIMPLE[ext]).toBeDefined();
    }
  });

  it('every PHONEME_TO_VISEME target is a real viseme with a shape', () => {
    for (const viseme of Object.values(PHONEME_TO_VISEME)) {
      expect(VISEME_SHAPES[viseme]).toBeDefined();
    }
  });

  it('getTransitionWeight returns the configured weight for known pairs', () => {
    expect(getTransitionWeight('sil', 'aa')).toBe(0.3);
    expect(getTransitionWeight('aa', 'sil')).toBe(0.4);
  });

  it('getTransitionWeight falls back to the default for unknown pairs', () => {
    expect(getTransitionWeight('kk', 'RR')).toBe(0.35);
    expect(getTransitionWeight('nonexistent', 'also-nonexistent')).toBe(0.35);
  });

  it('interpolateShapes at t=0 equals the from-shape', () => {
    const r = interpolateShapes('sil', 'aa', 0);
    expect(r.open).toBeCloseTo(VISEME_SHAPES.sil.open, 5);
  });

  it('interpolateShapes at t=1 equals the to-shape', () => {
    const r = interpolateShapes('sil', 'aa', 1);
    expect(r.open).toBeCloseTo(VISEME_SHAPES.aa.open, 5);
  });

  it('interpolateShapes clamps t outside [0,1]', () => {
    const over = interpolateShapes('sil', 'aa', 5);
    const under = interpolateShapes('sil', 'aa', -5);
    expect(over.open).toBeCloseTo(VISEME_SHAPES.aa.open, 5);
    expect(under.open).toBeCloseTo(VISEME_SHAPES.sil.open, 5);
  });

  it('interpolateShapes falls back to sil for an unknown viseme name', () => {
    const r = interpolateShapes('totally-unknown', 'aa', 0);
    expect(r.open).toBeCloseTo(VISEME_SHAPES.sil.open, 5);
  });
});

describe('audio-utils.js', () => {
  it('int16ToFloat32 / float32ToInt16 round-trip within rounding tolerance', () => {
    const original = new Int16Array([0, 16384, -16384, 32767, -32768]);
    const floats = int16ToFloat32(original);
    const back = float32ToInt16(floats);
    for (let i = 0; i < original.length; i++) {
      expect(Math.abs(back[i] - original[i])).toBeLessThan(2);
    }
  });

  it('calculateRMS of a constant byte signal centered at 128 is 0', () => {
    const data = new Uint8Array(100).fill(128);
    expect(calculateRMS(data, true)).toBeCloseTo(0, 5);
  });

  it('calculateRMS of full-amplitude alternating signal is close to 1', () => {
    const data = new Uint8Array(100);
    for (let i = 0; i < data.length; i++) data[i] = i % 2 === 0 ? 0 : 255;
    expect(calculateRMS(data, true)).toBeGreaterThan(0.9);
  });

  it('calculateRMS of empty data is 0 (no crash)', () => {
    expect(calculateRMS(new Uint8Array(0), true)).toBe(0);
  });

  it('zeroCrossingRate of a DC signal is 0', () => {
    const data = new Float32Array(50).fill(0.5);
    expect(zeroCrossingRate(data)).toBe(0);
  });

  it('zeroCrossingRate of a perfectly alternating signal is 1', () => {
    const data = new Float32Array(10);
    for (let i = 0; i < data.length; i++) data[i] = i % 2 === 0 ? 1 : -1;
    expect(zeroCrossingRate(data)).toBe(1);
  });

  it('extractBandEnergies returns all five expected bands', () => {
    const freqData = new Uint8Array(512).fill(128);
    const bands = extractBandEnergies(freqData, 44100);
    for (const name of ['sub', 'low', 'mid', 'high', 'veryHigh']) {
      expect(bands[name]).toBeGreaterThanOrEqual(0);
      expect(bands[name]).toBeLessThanOrEqual(1);
    }
  });

  it('extractBandEnergies of silence (all zero bins) is all zero bands', () => {
    const freqData = new Uint8Array(512).fill(0);
    const bands = extractBandEnergies(freqData, 44100);
    for (const v of Object.values(bands)) expect(v).toBe(0);
  });

  it('smoothValue moves toward target proportionally to (1 - factor)', () => {
    expect(smoothValue(0, 1, 0)).toBe(1);     // factor 0 = jump immediately
    expect(smoothValue(0, 1, 1)).toBe(0);     // factor 1 = never move
    expect(smoothValue(0, 1, 0.5)).toBeCloseTo(0.5, 5);
  });

  it('lerp clamps t to [0,1]', () => {
    expect(lerp(0, 10, -1)).toBe(0);
    expect(lerp(0, 10, 2)).toBe(10);
    expect(lerp(0, 10, 0.5)).toBe(5);
  });

  it('clamp restricts values to the given range', () => {
    expect(clamp(5, 0, 1)).toBe(1);
    expect(clamp(-5, 0, 1)).toBe(0);
    expect(clamp(0.5, 0, 1)).toBe(0.5);
  });

  it('resample is a no-op when rates match', () => {
    const input = new Float32Array([1, 2, 3]);
    expect(resample(input, 44100, 44100)).toBe(input);
  });

  it('resample halves the length when downsampling by 2x', () => {
    const input = new Float32Array(100).fill(1);
    const out = resample(input, 44100, 22050);
    expect(out.length).toBe(50);
  });
});

describe('FrequencyAnalyzer', () => {
  it('classifies silence (near-zero amplitude) as sil after the hold window', () => {
    const analyser = makeFakeAnalyser({ time: 128, freq: 0 });
    const fa = new FrequencyAnalyzer(analyser, 44100);
    let last;
    for (let i = 0; i < 5; i++) last = fa.analyze();
    expect(last.viseme).toBe('sil');
  });

  it('returns a consistent frame shape with shape.open/.width/.round', () => {
    const analyser = makeFakeAnalyser({ time: 200, freq: 150 });
    const fa = new FrequencyAnalyzer(analyser, 44100);
    const frame = fa.analyze();
    expect(frame.shape).toBeDefined();
    expect(typeof frame.shape.open).toBe('number');
    expect(typeof frame.shape.width).toBe('number');
    expect(typeof frame.shape.round).toBe('number');
  });

  it('reset() returns state to silence', () => {
    const analyser = makeFakeAnalyser({ time: 200, freq: 150 });
    const fa = new FrequencyAnalyzer(analyser, 44100);
    fa.analyze();
    fa.reset();
    expect(fa._currentViseme).toBe('sil');
    expect(fa._frameCount).toBe(0);
  });

  it('frame counter increments on every analyze() call', () => {
    const analyser = makeFakeAnalyser();
    const fa = new FrequencyAnalyzer(analyser, 44100);
    fa.analyze();
    fa.analyze();
    const frame = fa.analyze();
    expect(frame.frame).toBe(3);
  });
});

describe('VisemeScheduler', () => {
  let scheduler;
  beforeEach(() => {
    scheduler = new VisemeScheduler(fakeAudioContext(0));
  });

  it('returns null when no schedule has been set', () => {
    expect(scheduler.analyze()).toBeNull();
  });

  it('returns sil before the schedule starts', () => {
    const ctx = fakeAudioContext(10); // setSchedule() will record startTime=10
    scheduler = new VisemeScheduler(ctx);
    scheduler.setSchedule([{ start: 5, duration: 0.5, viseme: 'aa' }]); // relative start = 5s after startTime
    // currentTime hasn't advanced past startTime yet, let alone +5s
    expect(scheduler.analyze().viseme).toBe('sil');
  });

  it('returns the active viseme during its time window', () => {
    const ctx = fakeAudioContext(0);
    scheduler = new VisemeScheduler(ctx);
    scheduler.setSchedule([
      { start: 0, duration: 0.2, viseme: 'aa' },
      { start: 0.2, duration: 0.2, viseme: 'ih' },
    ]);
    ctx.currentTime = 0.25;
    const frame = scheduler.analyze();
    expect(frame.viseme).toBe('ih');
  });

  it('returns sil after the schedule ends', () => {
    const ctx = fakeAudioContext(0);
    scheduler = new VisemeScheduler(ctx);
    scheduler.setSchedule([{ start: 0, duration: 0.2, viseme: 'aa' }]);
    ctx.currentTime = 5.0;
    expect(scheduler.analyze().viseme).toBe('sil');
  });

  it('transition.progress reaches 1 once a viseme has been active long enough', () => {
    const ctx = fakeAudioContext(0);
    scheduler = new VisemeScheduler(ctx);
    scheduler.setSchedule([{ start: 0, duration: 1.0, viseme: 'aa' }]);
    ctx.currentTime = 0.5; // well past the ~0.06-0.08s transition window
    const frame = scheduler.analyze();
    expect(frame.transition.progress).toBe(1);
  });

  it('reset() clears the schedule so analyze() returns null again', () => {
    scheduler.setSchedule([{ start: 0, duration: 0.2, viseme: 'aa' }]);
    scheduler.reset();
    expect(scheduler.analyze()).toBeNull();
  });
});

describe('AdaptiveLipsyncManager', () => {
  it('uses the scheduler path once a non-empty schedule is set', () => {
    const ctx = fakeAudioContext(0);
    const mgr = new AdaptiveLipsyncManager(ctx, makeFakeAnalyser());
    mgr.setSchedule([{ start: 0, duration: 0.2, viseme: 'aa' }]);
    expect(mgr._useScheduler).toBe(true);
  });

  it('falls back to the frequency analyzer when given an empty schedule', () => {
    const ctx = fakeAudioContext(0);
    const mgr = new AdaptiveLipsyncManager(ctx, makeFakeAnalyser());
    mgr.setSchedule([]);
    expect(mgr._useScheduler).toBe(false);
    const frame = mgr.analyze();
    expect(frame.shape).toBeDefined();
  });

  it('reset() turns scheduler mode back off', () => {
    const ctx = fakeAudioContext(0);
    const mgr = new AdaptiveLipsyncManager(ctx, makeFakeAnalyser());
    mgr.setSchedule([{ start: 0, duration: 0.2, viseme: 'aa' }]);
    mgr.reset();
    expect(mgr._useScheduler).toBe(false);
  });
});

describe('AdvancedLipSync', () => {
  // Regression test for a real bug found during audit: in FFT/formant mode
  // (no schedule set — the live-microphone path), analyze() used to return
  // {viseme, mouthOpen, intensity} while avatar.js::setViseme() reads
  // frame.shape.open/.width/.round — guaranteed TypeError on every frame.
  it('FFT/formant-mode frames have the same .shape shape the scheduler path uses (regression)', () => {
    const ctx = fakeAudioContext(0);
    const lip = new AdvancedLipSync(ctx, makeFakeAnalyser({ time: 180, freq: 100 }), { fftSize: 1024 });
    const frame = lip.analyze();
    expect(frame.shape).toBeDefined();
    expect(typeof frame.shape.open).toBe('number');
    expect(typeof frame.shape.width).toBe('number');
    expect(typeof frame.shape.round).toBe('number');
    // The exact line that used to throw in production:
    expect(() => frame.shape.open * frame.intensity).not.toThrow();
  });

  it('scheduler-mode and FFT-mode frames are structurally identical (regression)', () => {
    const ctx = fakeAudioContext(0);
    const lip = new AdvancedLipSync(ctx, makeFakeAnalyser(), { fftSize: 1024 });
    const fftFrame = lip.analyze();
    lip.setSchedule([{ start: 0, duration: 1.0, viseme: 'aa' }]);
    const schedFrame = lip.analyze();
    const fields = ['viseme', 'simpleViseme', 'intensity', 'shape', 'transition', 'frame'];
    for (const f of fields) {
      expect(f in fftFrame).toBe(true);
      expect(f in schedFrame).toBe(true);
    }
  });

  it('formant classification emits a viseme that exists in the shared VISEME_SHAPES table (regression)', () => {
    // Before the fix, formant classification returned 'A'/'O'/'I'/'U'/'E'/'M'
    // — a separate taxonomy where 'A' and 'M' don't exist in VISEME_SHAPES.
    const ctx = fakeAudioContext(0);
    const lip = new AdvancedLipSync(ctx, makeFakeAnalyser({ time: 200, freq: 120 }), { fftSize: 1024 });
    const formants = { F1: 700, F2: 2000, F3: 0, F4: 0 }; // tuned to hit the 'A'-like branch
    const viseme = lip._formantToViseme(formants);
    expect(VISEME_SHAPES[viseme]).toBeDefined();
  });

  it('setSchedule(null) falls back to FFT/formant mode', () => {
    const ctx = fakeAudioContext(0);
    const lip = new AdvancedLipSync(ctx, makeFakeAnalyser(), { fftSize: 1024 });
    lip.setSchedule(null);
    expect(lip._useScheduler).toBe(false);
  });

  it('reset() clears coarticulation history and scheduler mode', () => {
    const ctx = fakeAudioContext(0);
    const lip = new AdvancedLipSync(ctx, makeFakeAnalyser(), { fftSize: 1024 });
    lip.analyze();
    lip.setSchedule([{ start: 0, duration: 1, viseme: 'aa' }]);
    lip.reset();
    expect(lip._useScheduler).toBe(false);
    expect(lip._history.length).toBe(0);
  });

  it('destroy() does not throw', () => {
    const ctx = fakeAudioContext(0);
    const lip = new AdvancedLipSync(ctx, makeFakeAnalyser(), { fftSize: 1024 });
    expect(() => lip.destroy()).not.toThrow();
  });
});

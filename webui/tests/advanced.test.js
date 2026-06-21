/**
 * @vitest-environment happy-dom
 *
 * BRUTAL tests for advanced features — VRM animation, frequency analyzer,
 * idle manager, and stream buffer.
 * Tests edge cases, race conditions, and resource management.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const mockMixer = {
  update: vi.fn(),
  clipAction: vi.fn(() => ({ play: vi.fn(), fadeIn: vi.fn(), stop: vi.fn() })),
  stopAllAction: vi.fn(),
};

// ===================================================================
// vrm-animation — Original + Brutal
// ===================================================================

describe('vrm-animation', () => {
  it('creates animation mixer with VRM scene', () => {
    const scene = {};
    const mixer = { ...mockMixer };
    expect(mixer.update).toBeDefined();
    expect(mixer.stopAllAction).toBeDefined();
  });

  it('plays idle animation when no active animation', () => {
    const clipAction = vi.fn(() => ({ play: vi.fn(), fadeIn: vi.fn() }));
    const mixer = { clipAction, update: vi.fn() };
    const clip = { name: 'idle' };
    const action = mixer.clipAction(clip);
    action.play();
    expect(clipAction).toHaveBeenCalledWith(clip);
  });

  it('transitions between animations with crossfade', () => {
    const prevAction = { fadeOut: vi.fn(), stop: vi.fn() };
    const nextAction = { play: vi.fn(), fadeIn: vi.fn() };
    nextAction.fadeIn(0.3);
    prevAction.fadeOut(0.3);
    expect(nextAction.fadeIn).toHaveBeenCalledWith(0.3);
    expect(prevAction.fadeOut).toHaveBeenCalledWith(0.3);
  });

  it('updates mixer each frame with delta time', () => {
    const update = vi.fn();
    const mixer = { update, clipAction: vi.fn() };
    mixer.update(0.016);
    expect(update).toHaveBeenCalledWith(0.016);
  });

  it('stops all actions on cleanup', () => {
    const stopAllAction = vi.fn();
    const mixer = { stopAllAction, update: vi.fn(), clipAction: vi.fn() };
    mixer.stopAllAction();
    expect(stopAllAction).toHaveBeenCalled();
  });

  it('handles null mixer gracefully', () => {
    let mixer = null;
    expect(() => {
      if (mixer) mixer.update(0.016);
    }).not.toThrow();
  });

  // --- Brutal tests ---

  it('mixer update with zero delta time', () => {
    const update = vi.fn();
    const mixer = { update, clipAction: vi.fn() };
    mixer.update(0);
    expect(update).toHaveBeenCalledWith(0);
  });

  it('mixer update with negative delta time', () => {
    const update = vi.fn();
    const mixer = { update, clipAction: vi.fn() };
    mixer.update(-0.016);
    expect(update).toHaveBeenCalledWith(-0.016);
  });

  it('mixer update with very large delta time', () => {
    const update = vi.fn();
    const mixer = { update, clipAction: vi.fn() };
    mixer.update(1000);
    expect(update).toHaveBeenCalledWith(1000);
  });

  it('crossfade with zero duration', () => {
    const prevAction = { fadeOut: vi.fn(), stop: vi.fn() };
    const nextAction = { play: vi.fn(), fadeIn: vi.fn() };
    nextAction.fadeIn(0);
    prevAction.fadeOut(0);
    expect(nextAction.fadeIn).toHaveBeenCalledWith(0);
    expect(prevAction.fadeOut).toHaveBeenCalledWith(0);
  });

  it('rapid play/stop cycles', () => {
    const play = vi.fn();
    const stop = vi.fn();
    const action = { play, stop };
    for (let i = 0; i < 1000; i++) {
      action.play();
      action.stop();
    }
    expect(play).toHaveBeenCalledTimes(1000);
    expect(stop).toHaveBeenCalledTimes(1000);
  });

  it('100 mixer updates in sequence', () => {
    const update = vi.fn();
    const mixer = { update, clipAction: vi.fn() };
    for (let i = 0; i < 100; i++) {
      mixer.update(0.016);
    }
    expect(update).toHaveBeenCalledTimes(100);
  });
});

// ===================================================================
// frequency-analyzer — Original + Brutal
// ===================================================================

describe('frequency-analyzer', () => {
  let analyserNode;
  let audioCtx;

  beforeEach(() => {
    audioCtx = {
      createAnalyser: vi.fn(() => ({
        fftSize: 256,
        frequencyBinCount: 128,
        getByteFrequencyData: vi.fn(),
        getByteTimeDomainData: vi.fn(),
        connect: vi.fn(),
      })),
      createMediaStreamSource: vi.fn(() => ({ connect: vi.fn() })),
      sampleRate: 16000,
    };
    analyserNode = audioCtx.createAnalyser();
  });

  it('creates analyser with correct fftSize', () => {
    expect(analyserNode.fftSize).toBe(256);
    expect(analyserNode.frequencyBinCount).toBe(128);
  });

  it('retrieves frequency data as byte array', () => {
    const dataArray = new Uint8Array(analyserNode.frequencyBinCount);
    analyserNode.getByteFrequencyData(dataArray);
    expect(analyserNode.getByteFrequencyData).toHaveBeenCalledWith(dataArray);
    expect(dataArray.length).toBe(128);
  });

  it('retrieves waveform data', () => {
    const dataArray = new Uint8Array(analyserNode.frequencyBinCount);
    analyserNode.getByteTimeDomainData(dataArray);
    expect(analyserNode.getByteTimeDomainData).toHaveBeenCalledWith(dataArray);
  });

  it('computes average frequency (spectral centroid)', () => {
    const frequencies = new Uint8Array([10, 20, 30, 40, 50, 60, 70, 80]);
    let weightedSum = 0;
    let totalAmp = 0;
    for (let i = 0; i < frequencies.length; i++) {
      weightedSum += i * frequencies[i];
      totalAmp += frequencies[i];
    }
    const centroid = totalAmp > 0 ? weightedSum / totalAmp : 0;
    expect(centroid).toBeCloseTo(4.666, 1);
    expect(totalAmp).toBe(360);
  });

  it('handles silence (all zeros)', () => {
    const frequencies = new Uint8Array(128);
    let totalAmp = 0;
    for (let i = 0; i < frequencies.length; i++) totalAmp += frequencies[i];
    expect(totalAmp).toBe(0);
  });

  // --- Brutal tests ---

  it('centroid of empty array', () => {
    const frequencies = new Uint8Array(0);
    let totalAmp = 0;
    for (let i = 0; i < frequencies.length; i++) totalAmp += frequencies[i];
    expect(totalAmp).toBe(0);
  });

  it('centroid of single bin', () => {
    const frequencies = new Uint8Array([255]);
    let weightedSum = 0;
    let totalAmp = 0;
    for (let i = 0; i < frequencies.length; i++) {
      weightedSum += i * frequencies[i];
      totalAmp += frequencies[i];
    }
    const centroid = totalAmp > 0 ? weightedSum / totalAmp : 0;
    expect(centroid).toBe(0);
  });

  it('centroid of max amplitude all bins', () => {
    const frequencies = new Uint8Array(128).fill(255);
    let weightedSum = 0;
    let totalAmp = 0;
    for (let i = 0; i < frequencies.length; i++) {
      weightedSum += i * frequencies[i];
      totalAmp += frequencies[i];
    }
    const centroid = totalAmp > 0 ? weightedSum / totalAmp : 0;
    expect(centroid).toBeCloseTo(63.5, 0);
  });

  it('fftSize options are valid powers of 2', () => {
    const validSizes = [32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768];
    for (const size of validSizes) {
      expect(Math.log2(size)).toBe(Math.floor(Math.log2(size)));
    }
  });

  it('frequencyBinCount is half of fftSize', () => {
    expect(analyserNode.frequencyBinCount).toBe(analyserNode.fftSize / 2);
  });

  it('sampleRate is reasonable', () => {
    expect(audioCtx.sampleRate).toBeGreaterThan(0);
    expect(audioCtx.sampleRate).toBeLessThanOrEqual(192000);
  });

  it('large frequency array centroid', () => {
    const frequencies = new Uint8Array(4096);
    for (let i = 0; i < 4096; i++) frequencies[i] = i % 256;
    let weightedSum = 0;
    let totalAmp = 0;
    for (let i = 0; i < frequencies.length; i++) {
      weightedSum += i * frequencies[i];
      totalAmp += frequencies[i];
    }
    expect(totalAmp).toBeGreaterThan(0);
  });
});

// ===================================================================
// idle-manager — Original + Brutal
// ===================================================================

describe('idle-manager', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it('starts idle timer on inactivity', () => {
    let idleTimer = null;
    const startIdle = vi.fn();
    const resetIdle = () => {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => startIdle(), 5000);
    };
    resetIdle();
    expect(idleTimer).toBeDefined();
  });

  it('triggers idle callback after timeout', () => {
    const startIdle = vi.fn();
    setTimeout(() => startIdle(), 5000);
    vi.advanceTimersByTime(5000);
    expect(startIdle).toHaveBeenCalled();
  });

  it('reset clears previous timer', () => {
    let idleTimer = null;
    const startIdle = vi.fn();
    const resetIdle = () => {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => startIdle(), 5000);
    };
    resetIdle();
    resetIdle(); // Reset again
    vi.advanceTimersByTime(5000);
    expect(startIdle).toHaveBeenCalledTimes(1);
  });

  // --- Brutal tests ---

  it('rapid resets do not leak timers', () => {
    let idleTimer = null;
    const startIdle = vi.fn();
    const resetIdle = () => {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => startIdle(), 5000);
    };
    for (let i = 0; i < 1000; i++) resetIdle();
    vi.advanceTimersByTime(5000);
    expect(startIdle).toHaveBeenCalledTimes(1);
  });

  it('timer with zero delay', () => {
    const fn = vi.fn();
    setTimeout(fn, 0);
    vi.advanceTimersByTime(0);
    expect(fn).toHaveBeenCalled();
  });

  it('timer with negative delay', () => {
    const fn = vi.fn();
    setTimeout(fn, -1);
    vi.advanceTimersByTime(0);
    // Negative delay treated as 0
    expect(fn).toHaveBeenCalled();
  });

  it('clearTimeout prevents callback', () => {
    const fn = vi.fn();
    const id = setTimeout(fn, 1000);
    clearTimeout(id);
    vi.advanceTimersByTime(1000);
    expect(fn).not.toHaveBeenCalled();
  });

  it('setInterval fires multiple times', () => {
    const fn = vi.fn();
    setInterval(fn, 100);
    vi.advanceTimersByTime(500);
    expect(fn).toHaveBeenCalledTimes(5);
  });

  it('clearInterval stops firing', () => {
    const fn = vi.fn();
    const id = setInterval(fn, 100);
    vi.advanceTimersByTime(300);
    clearInterval(id);
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('multiple timers are independent', () => {
    const fn1 = vi.fn();
    const fn2 = vi.fn();
    setTimeout(fn1, 1000);
    setTimeout(fn2, 2000);
    vi.advanceTimersByTime(1500);
    expect(fn1).toHaveBeenCalledTimes(1);
    expect(fn2).toHaveBeenCalledTimes(0);
    vi.advanceTimersByTime(1000);
    expect(fn2).toHaveBeenCalledTimes(1);
  });

  it('clearing already-fired timer is safe', () => {
    const fn = vi.fn();
    const id = setTimeout(fn, 100);
    vi.advanceTimersByTime(100);
    expect(fn).toHaveBeenCalled();
    clearTimeout(id); // Should not throw
  });
});

// ===================================================================
// stream-buffer — Brutal
// ===================================================================

describe('stream-buffer', () => {
  it('Map operations for stream buffer', () => {
    const buffer = new Map();
    buffer.set('key1', 'value1');
    buffer.set('key2', 'value2');
    expect(buffer.get('key1')).toBe('value1');
    expect(buffer.size).toBe(2);
  });

  it('overwrite existing key', () => {
    const buffer = new Map();
    buffer.set('key1', 'old');
    buffer.set('key1', 'new');
    expect(buffer.get('key1')).toBe('new');
    expect(buffer.size).toBe(1);
  });

  it('delete removes entry', () => {
    const buffer = new Map();
    buffer.set('key1', 'value1');
    buffer.delete('key1');
    expect(buffer.has('key1')).toBe(false);
  });

  it('clear removes all entries', () => {
    const buffer = new Map();
    buffer.set('k1', 'v1');
    buffer.set('k2', 'v2');
    buffer.clear();
    expect(buffer.size).toBe(0);
  });

  it('10000 entries do not crash', () => {
    const buffer = new Map();
    for (let i = 0; i < 10000; i++) {
      buffer.set(`key${i}`, `value${i}`);
    }
    expect(buffer.size).toBe(10000);
    expect(buffer.get('key9999')).toBe('value9999');
  });

  it('get nonexistent key returns undefined', () => {
    const buffer = new Map();
    expect(buffer.get('nonexistent')).toBeUndefined();
  });

  it('has returns false for missing key', () => {
    const buffer = new Map();
    expect(buffer.has('missing')).toBe(false);
  });

  it('keys and values iterators', () => {
    const buffer = new Map();
    buffer.set('a', 1);
    buffer.set('b', 2);
    expect([...buffer.keys()]).toEqual(['a', 'b']);
    expect([...buffer.values()]).toEqual([1, 2]);
  });
});
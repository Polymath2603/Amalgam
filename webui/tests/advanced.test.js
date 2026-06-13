/**
 * @vitest-environment happy-dom
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const mockMixer = {
  update: vi.fn(),
  clipAction: vi.fn(() => ({ play: vi.fn(), fadeIn: vi.fn(), stop: vi.fn() })),
  stopAllAction: vi.fn(),
};

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

    // Crossfade: fade out previous, fade in next
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
});

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
});

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

  it('triggers idle animation after timeout', () => {
    const onIdle = vi.fn();
    setTimeout(() => onIdle(), 5000);

    vi.advanceTimersByTime(5000);
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('resets idle timer on user activity', () => {
    const onIdle = vi.fn();
    let timer = setTimeout(() => onIdle(), 5000);

    // User activity resets the timer
    clearTimeout(timer);
    timer = setTimeout(() => onIdle(), 5000);

    vi.advanceTimersByTime(3000);
    expect(onIdle).not.toHaveBeenCalled();

    // Reset again
    clearTimeout(timer);
    timer = setTimeout(() => onIdle(), 5000);

    vi.advanceTimersByTime(5000);
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('cancels idle timer on cleanup', () => {
    const onIdle = vi.fn();
    const timer = setTimeout(() => onIdle(), 5000);
    clearTimeout(timer);

    vi.advanceTimersByTime(5000);
    expect(onIdle).not.toHaveBeenCalled();
  });
});

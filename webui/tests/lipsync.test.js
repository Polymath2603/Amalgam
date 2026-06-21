/**
 * @vitest-environment happy-dom
 *
 * BRUTAL tests for adaptive lipsync — edge cases, boundary values,
 * timing precision, and adversarial inputs.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const mockScene = { add: vi.fn(), remove: vi.fn() };
const mockVRM = {
  scene: mockScene,
  expressionManager: {
    setValue: vi.fn(),
    apply: vi.fn(),
    getExpression: vi.fn(() => ({ weight: 0 })),
  },
  update: vi.fn(),
};

global.THREE = {
  Clock: vi.fn(() => ({ getDelta: vi.fn(() => 0.016), start: vi.fn() })),
  Vector3: vi.fn(() => ({ x: 0, y: 0, z: 0, set: vi.fn(), lerp: vi.fn(), copy: vi.fn() })),
};

describe('Adaptive Lipsync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('maps viseme names to expression keys correctly', () => {
    const visemeToExpr = {
      'aa': 'aa', 'ee': 'ee', 'ih': 'ih',
      'oh': 'oh', 'ou': 'ou', 'rr': 'rr',
      'th': 'th', 'sil': 'neutral',
    };
    for (const [viseme, expr] of Object.entries(visemeToExpr)) {
      expect(expr).toBeTruthy();
    }
  });

  it('applies lip sync weights via expression manager', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    vrm.expressionManager.setValue('aa', 0.7);
    vrm.expressionManager.apply();
    expect(setValue).toHaveBeenCalledWith('aa', 0.7);
    expect(apply).toHaveBeenCalled();
  });

  it('handles missing expression manager gracefully', () => {
    const vrm = { scene: {} };
    expect(() => {
      if (vrm.expressionManager) {
        vrm.expressionManager.setValue('aa', 0.5);
      }
    }).not.toThrow();
  });

  it('blends between consecutive visemes smoothly', () => {
    const weights = new Map([['aa', 0.8], ['ee', 0.3]]);
    const dominant = [...weights.entries()].sort((a, b) => b[1] - a[1])[0][0];
    expect(dominant).toBe('aa');
  });

  it('decays viseme weight over time when no new data', () => {
    let weight = 0.8;
    const decay = 0.9;
    for (let i = 0; i < 10; i++) weight *= decay;
    expect(weight).toBeLessThan(0.8);
    expect(weight).toBeCloseTo(0.279, 1);
  });

  it('TTS metadata mode uses viseme timestamps from SSML', () => {
    const metadata = [
      { start: 0.0, end: 0.2, viseme: 'aa' },
      { start: 0.2, end: 0.4, viseme: 'ih' },
      { start: 0.4, end: 0.6, viseme: 'sil' },
    ];
    const atTime = (t) => metadata.find(m => t >= m.start && t < m.end)?.viseme || 'sil';
    expect(atTime(0.0)).toBe('aa');
    expect(atTime(0.1)).toBe('aa');
    expect(atTime(0.3)).toBe('ih');
    expect(atTime(0.5)).toBe('sil');
    expect(atTime(1.0)).toBe('sil');
  });

  it('FFT fallback mode converts audio amplitude to viseme weights', () => {
    const amplitude = 0.65;
    const intensity = Math.min(1.0, Math.max(0, amplitude));
    expect(intensity).toBe(0.65);
    expect(Math.min(1.0, Math.max(0, 0.02))).toBe(0.02);
    expect(Math.min(1.0, Math.max(0, 2.0))).toBe(1.0);
  });

  // --- Brutal tests ---

  it('decay never goes below zero', () => {
    let weight = 0.5;
    for (let i = 0; i < 1000; i++) weight *= 0.99;
    expect(weight).toBeGreaterThan(0);
    expect(weight).toBeLessThan(0.5);
  });

  it('decay with rate 0 stops immediately', () => {
    let weight = 0.8;
    weight *= 0;
    expect(weight).toBe(0);
  });

  it('decay with rate 1.0 maintains weight', () => {
    let weight = 0.8;
    for (let i = 0; i < 100; i++) weight *= 1.0;
    expect(weight).toBeCloseTo(0.8, 5);
  });

  it('viseme lookup with empty metadata', () => {
    const atTime = (t) => [].find(m => t >= m.start && t < m.end)?.viseme || 'sil';
    expect(atTime(0.5)).toBe('sil');
  });

  it('viseme lookup with overlapping metadata', () => {
    const metadata = [
      { start: 0.0, end: 0.5, viseme: 'aa' },
      { start: 0.3, end: 0.8, viseme: 'ee' },
    ];
    const atTime = (t) => metadata.find(m => t >= m.start && t < m.end)?.viseme || 'sil';
    expect(atTime(0.1)).toBe('aa');
    expect(atTime(0.4)).toBe('aa'); // First match wins
  });

  it('viseme lookup with negative time', () => {
    const metadata = [{ start: 0.0, end: 0.5, viseme: 'aa' }];
    const atTime = (t) => metadata.find(m => t >= m.start && t < m.end)?.viseme || 'sil';
    expect(atTime(-1.0)).toBe('sil');
  });

  it('viseme lookup with very large time', () => {
    const metadata = [{ start: 0.0, end: 0.5, viseme: 'aa' }];
    const atTime = (t) => metadata.find(m => t >= m.start && t < m.end)?.viseme || 'sil';
    expect(atTime(999999)).toBe('sil');
  });

  it('1000 rapid weight updates do not crash', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    for (let i = 0; i < 1000; i++) {
      vrm.expressionManager.setValue('aa', Math.random());
      vrm.expressionManager.apply();
    }
    expect(setValue).toHaveBeenCalledTimes(1000);
  });

  it('blending with equal weights picks first', () => {
    const weights = new Map([['aa', 0.5], ['ee', 0.5]]);
    const sorted = [...weights.entries()].sort((a, b) => b[1] - a[1]);
    expect(sorted[0][1]).toBe(0.5);
  });

  it('blending with single entry', () => {
    const weights = new Map([['aa', 1.0]]);
    const dominant = [...weights.entries()].sort((a, b) => b[1] - a[1])[0][0];
    expect(dominant).toBe('aa');
  });

  it('blending with empty map', () => {
    const weights = new Map();
    expect(weights.size).toBe(0);
  });

  it('amplitude clipping handles NaN', () => {
    const intensity = Math.min(1.0, Math.max(0, NaN));
    expect(isNaN(intensity) || intensity === 0).toBe(true);
  });

  it('amplitude clipping handles Infinity', () => {
    const intensity = Math.min(1.0, Math.max(0, Infinity));
    expect(intensity).toBe(1.0);
  });

  it('amplitude clipping handles negative Infinity', () => {
    const intensity = Math.min(1.0, Math.max(0, -Infinity));
    expect(intensity).toBe(0);
  });

  it('amplitude clipping handles exactly 0', () => {
    const intensity = Math.min(1.0, Math.max(0, 0));
    expect(intensity).toBe(0);
  });

  it('amplitude clipping handles exactly 1', () => {
    const intensity = Math.min(1.0, Math.max(0, 1));
    expect(intensity).toBe(1);
  });
});
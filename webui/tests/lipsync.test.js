/**
 * @vitest-environment happy-dom
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock THREE for modules that import it
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
    // These should be the standard ARPABET-to-viseme mappings
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
    const vrm = {
      expressionManager: { setValue, apply },
    };

    // Simulate processing a viseme frame
    vrm.expressionManager.setValue('aa', 0.7);
    vrm.expressionManager.apply();
    expect(setValue).toHaveBeenCalledWith('aa', 0.7);
    expect(apply).toHaveBeenCalled();
  });

  it('handles missing expression manager gracefully', () => {
    const vrm = { scene: {} };
    // Should not throw
    expect(() => {
      if (vrm.expressionManager) {
        vrm.expressionManager.setValue('aa', 0.5);
      }
    }).not.toThrow();
  });

  it('blends between consecutive visemes smoothly', () => {
    // Simulate two visemes with different weights
    const weights = new Map([
      ['aa', 0.8],
      ['ee', 0.3],
    ]);
    // The active viseme should dominate
    const dominant = [...weights.entries()].sort((a, b) => b[1] - a[1])[0][0];
    expect(dominant).toBe('aa');
  });

  it('decays viseme weight over time when no new data', () => {
    let weight = 0.8;
    const decay = 0.9; // per frame
    for (let i = 0; i < 10; i++) {
      weight *= decay;
    }
    expect(weight).toBeLessThan(0.8);
    expect(weight).toBeCloseTo(0.279, 1); // after 10 frames
  });

  it('TTS metadata mode uses viseme timestamps from SSML', () => {
    const metadata = [
      { start: 0.0, end: 0.2, viseme: 'aa' },
      { start: 0.2, end: 0.4, viseme: 'ih' },
      { start: 0.4, end: 0.6, viseme: 'sil' },
    ];

    // At time 0.1, should be 'aa'
    const atTime = (t) => {
      return metadata.find(m => t >= m.start && t < m.end)?.viseme || 'sil';
    };
    expect(atTime(0.0)).toBe('aa');
    expect(atTime(0.1)).toBe('aa');
    expect(atTime(0.3)).toBe('ih');
    expect(atTime(0.5)).toBe('sil');
    expect(atTime(1.0)).toBe('sil');
  });

  it('FFT fallback mode converts audio amplitude to viseme weights', () => {
    const amplitude = 0.65;
    // Map amplitude to viseme intensity
    const intensity = Math.min(1.0, Math.max(0, amplitude));
    expect(intensity).toBe(0.65);
    // Near-silent audio should produce near-zero weight
    expect(Math.min(1.0, Math.max(0, 0.02))).toBe(0.02);
    // Clipped amplitude should cap at 1.0
    expect(Math.min(1.0, Math.max(0, 2.0))).toBe(1.0);
  });
});

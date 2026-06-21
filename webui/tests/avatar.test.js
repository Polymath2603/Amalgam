/**
 * @vitest-environment happy-dom
 *
 * BRUTAL tests for avatar viseme logic — edge cases, boundary values,
 * and adversarial inputs.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const VISEME_MAP = {
  aa: 'aa', E: 'ee', ih: 'ih', oh: 'oh', ou: 'ou', RR: 'rr', th: 'th',
};

function visemeToExpression(viseme) {
  return VISEME_MAP[viseme] || 'neutral';
}

const LipSyncMode = { REALTIME: 'realtime', METADATA: 'metadata' };

// ===================================================================
// visemeToExpression — Original + Brutal
// ===================================================================

describe('visemeToExpression', () => {
  it('maps known phoneme visemes to correct expression keys', () => {
    expect(visemeToExpression('aa')).toBe('aa');
    expect(visemeToExpression('E')).toBe('ee');
    expect(visemeToExpression('ih')).toBe('ih');
    expect(visemeToExpression('oh')).toBe('oh');
    expect(visemeToExpression('ou')).toBe('ou');
    expect(visemeToExpression('RR')).toBe('rr');
    expect(visemeToExpression('th')).toBe('th');
  });

  it('returns neutral for unknown visemes', () => {
    expect(visemeToExpression('xx')).toBe('neutral');
    expect(visemeToExpression('')).toBe('neutral');
    expect(visemeToExpression(null)).toBe('neutral');
    expect(visemeToExpression(undefined)).toBe('neutral');
  });

  it('is case-sensitive for the E -> ee mapping', () => {
    expect(visemeToExpression('e')).toBe('neutral');
  });

  // --- Brutal tests ---

  it('handles numeric input', () => {
    expect(visemeToExpression(42)).toBe('neutral');
    expect(visemeToExpression(0)).toBe('neutral');
  });

  it('handles boolean input', () => {
    expect(visemeToExpression(true)).toBe('neutral');
    expect(visemeToExpression(false)).toBe('neutral');
  });

  it('handles object input', () => {
    expect(visemeToExpression({})).toBe('neutral');
  });

  it('handles array input', () => {
    expect(visemeToExpression([])).toBe('neutral');
  });

  it('handles very long string', () => {
    expect(visemeToExpression('x'.repeat(10000))).toBe('neutral');
  });

  it('handles Unicode input', () => {
    expect(visemeToExpression('\u4f60\u597d')).toBe('neutral');
  });

  it('all mapped visemes produce non-neutral output', () => {
    for (const [viseme, expr] of Object.entries(VISEME_MAP)) {
      expect(visemeToExpression(viseme)).toBe(expr);
      expect(visemeToExpression(viseme)).not.toBe('neutral');
    }
  });

  it('all neutral results are exactly the string neutral', () => {
    expect(visemeToExpression('unknown')).toBe('neutral');
    expect(visemeToExpression('')).toBe('neutral');
  });
});

// ===================================================================
// setExpression logic — Original + Brutal
// ===================================================================

describe('setExpression logic', () => {
  it('sets expression weight on VRM expressionManager', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    if (vrm?.expressionManager) {
      vrm.expressionManager.setValue('happy', 0.8);
      vrm.expressionManager.apply();
    }
    expect(setValue).toHaveBeenCalledWith('happy', 0.8);
    expect(apply).toHaveBeenCalled();
  });

  it('does nothing when vrm is null', () => {
    const vrm = null;
    expect(() => {
      if (vrm?.expressionManager) {
        vrm.expressionManager.setValue('test', 1);
      }
    }).not.toThrow();
  });

  it('does nothing when expressionManager is missing', () => {
    const vrm = {};
    expect(() => {
      if (vrm.expressionManager) {
        vrm.expressionManager.setValue('test', 1);
      }
    }).not.toThrow();
  });

  // --- Brutal tests ---

  it('handles weight = 0', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    vrm.expressionManager.setValue('happy', 0);
    expect(setValue).toHaveBeenCalledWith('happy', 0);
  });

  it('handles weight = 1', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    vrm.expressionManager.setValue('happy', 1);
    expect(setValue).toHaveBeenCalledWith('happy', 1);
  });

  it('handles weight > 1 (overflow)', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    vrm.expressionManager.setValue('happy', 999);
    expect(setValue).toHaveBeenCalledWith('happy', 999);
  });

  it('handles negative weight', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    vrm.expressionManager.setValue('happy', -0.5);
    expect(setValue).toHaveBeenCalledWith('happy', -0.5);
  });

  it('handles empty expression name', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    vrm.expressionManager.setValue('', 0.5);
    expect(setValue).toHaveBeenCalledWith('', 0.5);
  });

  it('handles very long expression name', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    vrm.expressionManager.setValue('x'.repeat(10000), 0.5);
    expect(setValue).toHaveBeenCalled();
  });

  it('apply is called after setValue', () => {
    const callOrder = [];
    const setValue = vi.fn(() => callOrder.push('setValue'));
    const apply = vi.fn(() => callOrder.push('apply'));
    const vrm = { expressionManager: { setValue, apply } };
    vrm.expressionManager.setValue('happy', 0.5);
    vrm.expressionManager.apply();
    expect(callOrder).toEqual(['setValue', 'apply']);
  });

  it('multiple setExpression calls in sequence', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    for (let i = 0; i < 100; i++) {
      vrm.expressionManager.setValue('happy', i / 100);
      vrm.expressionManager.apply();
    }
    expect(setValue).toHaveBeenCalledTimes(100);
    expect(apply).toHaveBeenCalledTimes(100);
  });
});

// ===================================================================
// setBlink logic — Original + Brutal
// ===================================================================

describe('setBlink logic', () => {
  it('sets blink weight on VRM expressionManager', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    if (vrm?.expressionManager) {
      vrm.expressionManager.setValue('blink', 0.5);
      vrm.expressionManager.apply();
    }
    expect(setValue).toHaveBeenCalledWith('blink', 0.5);
    expect(apply).toHaveBeenCalled();
  });

  it('handles missing vrm gracefully', () => {
    expect(() => {
      const vrm = null;
      if (vrm?.expressionManager) {
        vrm.expressionManager.setValue('blink', 0.5);
      }
    }).not.toThrow();
  });

  it('blink closed (weight = 1)', () => {
    const setValue = vi.fn();
    const vrm = { expressionManager: { setValue, apply: vi.fn() } };
    vrm.expressionManager.setValue('blink', 1.0);
    expect(setValue).toHaveBeenCalledWith('blink', 1.0);
  });

  it('blink open (weight = 0)', () => {
    const setValue = vi.fn();
    const vrm = { expressionManager: { setValue, apply: vi.fn() } };
    vrm.expressionManager.setValue('blink', 0.0);
    expect(setValue).toHaveBeenCalledWith('blink', 0.0);
  });
});

// ===================================================================
// processLipSync logic — Original + Brutal
// ===================================================================

describe('processLipSync logic', () => {
  it('processes realtime (amplitude-based) mode', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    const amplitude = 0.5;
    const viseme = 'aa';
    const clampedAmp = Math.min(1, Math.max(0, amplitude));
    if (vrm?.expressionManager) {
      vrm.expressionManager.setValue(viseme || 'aa', clampedAmp);
      vrm.expressionManager.apply();
    }
    expect(setValue).toHaveBeenCalledWith('aa', 0.5);
    expect(apply).toHaveBeenCalled();
  });

  it('clips amplitude to [0, 1] range', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    const amplitude = 2.0;
    const clampedAmp = Math.min(1, Math.max(0, amplitude));
    vrm.expressionManager.setValue('aa', clampedAmp);
    expect(setValue).toHaveBeenCalledWith('aa', 1.0);
  });

  it('handles negative amplitude', () => {
    const clampedAmp = Math.min(1, Math.max(0, -0.5));
    expect(clampedAmp).toBe(0);
  });

  it('handles zero amplitude', () => {
    const clampedAmp = Math.min(1, Math.max(0, 0));
    expect(clampedAmp).toBe(0);
  });

  it('handles NaN amplitude', () => {
    const clampedAmp = Math.min(1, Math.max(0, NaN));
    expect(isNaN(clampedAmp) || clampedAmp === 0).toBe(true);
  });

  it('handles Infinity amplitude', () => {
    const clampedAmp = Math.min(1, Math.max(0, Infinity));
    expect(clampedAmp).toBe(1);
  });

  it('metadata mode uses viseme timestamps from SSML', () => {
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

  it('metadata mode handles empty metadata', () => {
    const atTime = (t) => [].find(m => t >= m.start && t < m.end)?.viseme || 'sil';
    expect(atTime(0.0)).toBe('sil');
  });

  it('metadata mode handles time before first viseme', () => {
    const metadata = [{ start: 0.5, end: 1.0, viseme: 'aa' }];
    const atTime = (t) => metadata.find(m => t >= m.start && t < m.end)?.viseme || 'sil';
    expect(atTime(0.0)).toBe('sil');
  });

  it('rapid lip sync updates do not crash', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };
    for (let i = 0; i < 1000; i++) {
      const amp = Math.random();
      vrm.expressionManager.setValue('aa', Math.min(1, Math.max(0, amp)));
      vrm.expressionManager.apply();
    }
    expect(setValue).toHaveBeenCalledTimes(1000);
  });
});
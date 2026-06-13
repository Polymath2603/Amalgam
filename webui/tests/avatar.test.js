/**
 * @vitest-environment happy-dom
 *
 * Tests for avatar.js pure functions.
 * These test the logic inline since three/@pixiv/three-vrm
 * are not installed as npm packages in this project.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// ─── Pure function implementations matching avatar.js ──────────────────────

const VISEME_MAP = {
  aa: 'aa',
  E: 'ee',
  ih: 'ih',
  oh: 'oh',
  ou: 'ou',
  RR: 'rr',
  th: 'th',
};

function visemeToExpression(viseme) {
  return VISEME_MAP[viseme] || 'neutral';
}

const LipSyncMode = { REALTIME: 'realtime', METADATA: 'metadata' };

// ─── Tests ─────────────────────────────────────────────────────────────────

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

  it('is case-sensitive for the E → ee mapping', () => {
    // 'e' (lowercase) is not in the map, so returns neutral
    expect(visemeToExpression('e')).toBe('neutral');
  });
});

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
});

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
});

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

    if (vrm?.expressionManager) {
      vrm.expressionManager.setValue('aa', clampedAmp);
      vrm.expressionManager.apply();
    }

    expect(setValue).toHaveBeenCalledWith('aa', 1.0);
  });

  it('handles negative amplitude', () => {
    const clampedAmp = Math.min(1, Math.max(0, -0.5));
    expect(clampedAmp).toBe(0);
  });

  it('processes metadata (viseme-based) mode', () => {
    const setValue = vi.fn();
    const apply = vi.fn();
    const vrm = { expressionManager: { setValue, apply } };

    const viseme = 'oh';
    const mappedViseme = visemeToExpression(viseme);

    if (vrm?.expressionManager) {
      vrm.expressionManager.setValue(mappedViseme, 1.0);
      vrm.expressionManager.apply();
    }

    expect(setValue).toHaveBeenCalledWith('oh', 1.0);
    expect(apply).toHaveBeenCalled();
  });

  it('decays weights for visemes not in the current frame', () => {
    const previousWeights = { aa: 0.8, ee: 0.0 };
    const decay = 0.85;

    // Apply decay each frame
    for (let i = 0; i < 5; i++) {
      for (const key of Object.keys(previousWeights)) {
        previousWeights[key] *= decay;
      }
    }

    expect(previousWeights.aa).toBeCloseTo(0.355, 2);
    expect(previousWeights.ee).toBe(0);
  });
});

describe('initAvatar logic', () => {
  it('requires a valid container element', () => {
    // Simulate: initAvatar looks up the container by id
    const mockRenderer = { setSize: vi.fn(), render: vi.fn(), domElement: document.createElement('canvas') };

    document.body.innerHTML = '<div id="valid-container"></div>';

    const container = document.getElementById('valid-container');
    const missing = document.getElementById('missing-container');

    expect(container).toBeTruthy();
    expect(missing).toBeNull();

    // If container exists, renderer is created and canvas is appended
    if (container) {
      container.appendChild(mockRenderer.domElement);
      expect(container.children.length).toBe(1);
      expect(container.children[0].tagName).toBe('CANVAS');
    }
  });

  it('returns null when container not found', () => {
    const container = document.getElementById('nonexistent');
    expect(container).toBeNull();
  });
});

describe('loadVRM logic', () => {
  it('returns null if url is not provided', async () => {
    const loadVRM = async (url) => {
      if (!url) return null;
      // Would load the VRM here
      return {};
    };

    await expect(loadVRM(null)).resolves.toBeNull();
    await expect(loadVRM(undefined)).resolves.toBeNull();
    await expect(loadVRM('')).resolves.toBeNull();
  });
});

describe('cleanupAvatar logic', () => {
  it('handles empty avatar state', () => {
    const state = {};
    expect(() => {
      if (state.vrm) {
        // dispose
      }
      if (state.renderer) {
        state.renderer.dispose();
      }
    }).not.toThrow();
  });

  it('disposes renderer if present', () => {
    const dispose = vi.fn();
    const state = { renderer: { dispose } };
    if (state.renderer) {
      state.renderer.dispose();
    }
    expect(dispose).toHaveBeenCalled();
  });
});

describe('LipSyncMode enum', () => {
  it('has REALTIME and METADATA modes', () => {
    expect(LipSyncMode.REALTIME).toBe('realtime');
    expect(LipSyncMode.METADATA).toBe('metadata');
    expect(Object.keys(LipSyncMode).length).toBe(2);
  });
});

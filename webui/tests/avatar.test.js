/**
 * @vitest-environment happy-dom
 *
 * Real tests for AvatarRenderer (webui/js/avatar.js) — setEmotion's VRM
 * expression-candidate fallback, the idle/bored/sleeping life-state
 * machine, and setViseme's consumption of a lipsync frame. These
 * construct the actual class (with three.js/VRM swapped for a minimal
 * offline shim — see node_modules/three — since real WebGL rendering
 * can't be verified in Node either way) and call its real methods.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { installMinimalDOM } from './_dom-shim.js';

// Only install the offline DOM shim if a real DOM isn't already present —
// real vitest + happy-dom (after `npm install`) provides document/window
// itself, and this must not clobber it.
if (typeof document === 'undefined') installMinimalDOM();
const { AvatarRenderer } = await import('../js/avatar.js');

function makeContainer() {
  const el = document.createElement('div');
  el.clientWidth = 800;
  el.clientHeight = 600;
  return el;
}

function makeFakeVRM(availableExpressions) {
  const calls = [];
  return {
    update() {},
    expressionManager: {
      _values: {},
      setValue(name, v) {
        calls.push(['set', name, v]);
        this._values[name] = v;
      },
      getValue(name) {
        if (!availableExpressions.includes(name)) throw new Error(`no such expression: ${name}`);
        return this._values[name] ?? 0;
      },
      apply() {},
    },
    _calls: calls,
  };
}

describe('AvatarRenderer.setEmotion', () => {
  let av;
  beforeEach(() => {
    av = new AvatarRenderer(makeContainer(), '/fake.vrm', {});
  });
  afterEach(() => {
    av.destroy();
  });

  it('queues the emotion when no VRM is loaded yet', () => {
    av.vrm = null;
    av.setEmotion('happy');
    expect(av._pendingEmotion).toBe('happy');
    expect(av.currentEmotion).toBe('neutral'); // unchanged — not applied yet
  });

  it('applies the emotion directly when its exact name exists on the VRM', () => {
    av.vrm = makeFakeVRM(['happy', 'angry', 'sad', 'relaxed', 'surprised']);
    av.setEmotion('happy');
    expect(av.currentEmotion).toBe('happy');
    expect(av._targetExpressions.happy).toBe(1.0);
    expect(av.vrm.expressionManager.getValue('happy')).toBe(1.0);
  });

  it('falls back to the next candidate name when the first is missing from this VRM', () => {
    // EMOTION_CANDIDATES.happy = ['happy', 'joy', 'smile', 'pleasant'] — this
    // VRM only exposes 'joy', so setEmotion must fall through to it.
    av.vrm = makeFakeVRM(['joy', 'angry', 'sad', 'relaxed', 'surprised']);
    av.setEmotion('happy');
    expect(av.vrm.expressionManager.getValue('joy')).toBe(1.0);
  });

  it('resets all five base expressions to 0 before applying the new one', () => {
    av.vrm = makeFakeVRM(['happy', 'angry', 'sad', 'relaxed', 'surprised']);
    av.setEmotion('happy');
    av.vrm._calls.length = 0;
    av.setEmotion('sad');
    const resetCalls = av.vrm._calls.filter((c) => c[2] === 0);
    const resetNames = resetCalls.map((c) => c[1]);
    expect(resetNames).toContain('happy');
    expect(resetNames).toContain('angry');
  });

  it('silently leaves currentEmotion set even when no candidate exists on this VRM', () => {
    av.vrm = makeFakeVRM([]); // no expressions at all
    expect(() => av.setEmotion('happy')).not.toThrow();
    expect(av.currentEmotion).toBe('happy');
  });

  it('neutral does not try to apply any expression (it is the all-zero state)', () => {
    av.vrm = makeFakeVRM(['happy', 'angry', 'sad', 'relaxed', 'surprised']);
    av.setEmotion('happy');
    av.setEmotion('neutral');
    expect(av.currentEmotion).toBe('neutral');
    expect(av.vrm.expressionManager.getValue('happy')).toBe(0);
  });

  it('schedules an auto-reset-to-neutral timer for non-neutral emotions', () => {
    vi.useFakeTimers();
    av.vrm = makeFakeVRM(['happy', 'angry', 'sad', 'relaxed', 'surprised']);
    av.setEmotion('happy');
    expect(av.currentEmotion).toBe('happy');
    vi.advanceTimersByTime(av._emotionDuration + 100);
    expect(av.currentEmotion).toBe('neutral');
    vi.useRealTimers();
  });

  it('setExpression() is an alias for setEmotion()', () => {
    av.vrm = makeFakeVRM(['happy', 'angry', 'sad', 'relaxed', 'surprised']);
    av.setExpression('happy');
    expect(av.currentEmotion).toBe('happy');
  });
});

describe('AvatarRenderer life-state machine', () => {
  let av;
  beforeEach(() => {
    av = new AvatarRenderer(makeContainer(), '/fake.vrm', {});
    av.vrm = makeFakeVRM(['happy', 'angry', 'sad', 'relaxed', 'surprised']);
    av.initLifeStateMachine();
  });
  afterEach(() => {
    av.destroy();
  });

  it('starts idle with a zeroed bored timer', () => {
    expect(av.lifeState).toBe('idle');
    expect(av._boredTimer).toBe(0);
  });

  it('transitions idle -> bored once the inactivity threshold is reached', () => {
    av._boredTimer = av._inactivityThreshold;
    av._updateLifeState();
    expect(av.lifeState).toBe('bored');
  });

  it('does not transition to bored before the threshold', () => {
    av._boredTimer = av._inactivityThreshold - 1000;
    av._updateLifeState();
    expect(av.lifeState).toBe('idle');
  });

  it('transitions bored -> sleeping once the sleep threshold is reached', () => {
    av.lifeState = 'bored';
    av._boredTimer = av._sleepThreshold;
    av._updateLifeState();
    expect(av.lifeState).toBe('sleeping');
  });

  it('never leaves sleeping on its own (stays asleep until interact())', () => {
    av.lifeState = 'sleeping';
    av._boredTimer = av._sleepThreshold + 999999;
    av._updateLifeState();
    expect(av.lifeState).toBe('sleeping');
  });

  it('interact() resets the timer, returns to idle, and clears the emotion', () => {
    av.lifeState = 'sleeping';
    av._boredTimer = 999999;
    av.setEmotion('happy');
    av.interact();
    expect(av.lifeState).toBe('idle');
    expect(av._boredTimer).toBe(0);
    expect(av.currentEmotion).toBe('neutral');
  });

  it('_updateLifeState advances the bored timer by the poll interval each call', () => {
    const before = av._boredTimer;
    av._updateLifeState();
    expect(av._boredTimer).toBe(before + 5000);
  });
});

describe('AvatarRenderer.setViseme', () => {
  let av;
  beforeEach(() => {
    av = new AvatarRenderer(makeContainer(), '/fake.vrm', {});
  });
  afterEach(() => {
    av.destroy();
  });

  it('does nothing (no throw) when there is no VRM loaded', () => {
    av.vrm = null;
    expect(() => av.setViseme({ shape: { open: 1, width: 1, round: 1 }, intensity: 1 })).not.toThrow();
  });

  it('does nothing (no throw) when visemeFrame is null', () => {
    av.vrm = makeFakeVRM(['aa', 'ih', 'ou', 'ee', 'oh']);
    expect(() => av.setViseme(null)).not.toThrow();
  });

  it('applies a real lipsync frame (from AdaptiveLipsyncManager) without throwing', async () => {
    // Integration check: feed setViseme a frame shaped exactly like what
    // the real lipsync stack produces, not a hand-rolled approximation.
    const { AdaptiveLipsyncManager } = await import('../js/adaptive-lipsync.js');
    const fakeAnalyser = {
      fftSize: 1024, frequencyBinCount: 512, smoothingTimeConstant: 0,
      getByteTimeDomainData(arr) { arr.fill(200); },
      getByteFrequencyData(arr) { arr.fill(150); },
    };
    const mgr = new AdaptiveLipsyncManager({ sampleRate: 44100 }, fakeAnalyser);
    const frame = mgr.analyze();
    av.vrm = makeFakeVRM(['aa', 'ih', 'ou', 'ee', 'oh']);
    expect(() => av.setViseme(frame)).not.toThrow();
  });
});

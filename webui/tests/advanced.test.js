/**
 * Real tests for VRMAnimation (webui/js/vrm-animation.js) and IdleManager
 * (webui/js/idle-manager.js). The frequency-analyzer is already covered
 * thoroughly in lipsync.test.js, so it isn't duplicated here. (A previous
 * version of this file also had a "stream-buffer" suite that tested
 * nothing but JavaScript's built-in Map — removed, since it covered zero
 * lines of this project's own code.)
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import * as THREE from 'three';
import { VRMAnimation } from '../js/vrm-animation.js';
import { IdleManager } from '../js/idle-manager.js';

describe('VRMAnimation', () => {
  it('createHumanoidTracks renames rotation tracks to "<bone>.quaternion" via getNormalizedBoneNode', () => {
    const anim = new VRMAnimation();
    const origTrack = new THREE.QuaternionKeyframeTrack(
      'orig', [0, 1], new Float32Array([0, 0, 0, 1, 0, 0, 0, 1])
    );
    anim.humanoidTracks.rotation.set('head', origTrack);

    const vrm = {
      meta: { metaVersion: '1' },
      humanoid: {
        getNormalizedBoneNode: (name) => (name === 'head' ? { name: 'Head_Node' } : null),
        getNormalizedAbsolutePose: () => ({ hips: { position: [0, 1, 0] } }),
      },
    };
    const tracks = anim.createHumanoidTracks(vrm);
    expect(tracks).toHaveLength(1);
    expect(tracks[0].name).toBe('Head_Node.quaternion');
  });

  it('createHumanoidTracks skips bones the VRM does not have a node for', () => {
    const anim = new VRMAnimation();
    const origTrack = new THREE.QuaternionKeyframeTrack('orig', [0], new Float32Array([0, 0, 0, 1]));
    anim.humanoidTracks.rotation.set('leftUpperArm', origTrack);
    const vrm = {
      meta: { metaVersion: '1' },
      humanoid: { getNormalizedBoneNode: () => null, getNormalizedAbsolutePose: () => ({ hips: { position: [0, 1, 0] } }) },
    };
    expect(anim.createHumanoidTracks(vrm)).toHaveLength(0);
  });

  it('createHumanoidTracks scales hip translation by the rest-pose height ratio', () => {
    const anim = new VRMAnimation();
    anim.restHipsPosition = new THREE.Vector3(0, 1.0, 0); // recorded at load time
    const origTrack = new THREE.VectorKeyframeTrack('orig', [0], [0, 1, 0]);
    anim.humanoidTracks.translation.set('hips', origTrack);

    const vrm = {
      meta: { metaVersion: '1' },
      humanoid: {
        getNormalizedBoneNode: (name) => (name === 'hips' ? { name: 'Hips_Node' } : null),
        getNormalizedAbsolutePose: () => ({ hips: { position: [0, 2.0, 0] } }), // VRM is 2x taller
      },
    };
    const tracks = anim.createHumanoidTracks(vrm);
    expect(tracks).toHaveLength(1);
    expect(tracks[0].name).toBe('Hips_Node.position');
    // scale = humanoidY / animationY = 2.0 / 1.0 = 2
    expect(tracks[0].values[1]).toBeCloseTo(2, 5);
  });

  it('createExpressionTracks only includes expressions present on this VRM (via getExpressionTrackName)', () => {
    const anim = new VRMAnimation();
    anim.expressionTracks.set('happy', new THREE.NumberKeyframeTrack('orig', [0], [1]));
    anim.expressionTracks.set('unknownExpr', new THREE.NumberKeyframeTrack('orig2', [0], [1]));

    const expressionManager = {
      getExpressionTrackName: (name) => (name === 'happy' ? 'happyMesh.morphTargetInfluences[0]' : null),
    };
    const tracks = anim.createExpressionTracks(expressionManager);
    expect(tracks).toHaveLength(1);
    expect(tracks[0].name).toBe('happyMesh.morphTargetInfluences[0]');
  });

  it('createLookAtTrack returns null when there is no lookAt track', () => {
    const anim = new VRMAnimation();
    expect(anim.createLookAtTrack('x')).toBeNull();
  });

  it('createLookAtTrack renames the track when present', () => {
    const anim = new VRMAnimation();
    anim.lookAtTrack = new THREE.QuaternionKeyframeTrack('orig', [0], [0, 0, 0, 1]);
    const track = anim.createLookAtTrack('lookAtTargetParent.quaternion');
    expect(track.name).toBe('lookAtTargetParent.quaternion');
  });

  it('createAnimationClip assembles humanoid + expression + lookAt tracks into one clip', () => {
    const anim = new VRMAnimation();
    anim.duration = 1.5;
    anim.humanoidTracks.rotation.set('head', new THREE.QuaternionKeyframeTrack('orig', [0], [0, 0, 0, 1]));
    anim.expressionTracks.set('happy', new THREE.NumberKeyframeTrack('orig2', [0], [1]));
    anim.lookAtTrack = new THREE.QuaternionKeyframeTrack('orig3', [0], [0, 0, 0, 1]);

    const vrm = {
      meta: { metaVersion: '1' },
      humanoid: {
        getNormalizedBoneNode: (name) => (name === 'head' ? { name: 'Head_Node' } : null),
        getNormalizedAbsolutePose: () => ({ hips: { position: [0, 1, 0] } }),
      },
      expressionManager: { getExpressionTrackName: () => 'happyMesh.morphTargetInfluences[0]' },
      lookAt: {},
    };
    const clip = anim.createAnimationClip(vrm);
    expect(clip.duration).toBe(1.5);
    expect(clip.tracks.length).toBe(3);
  });

  it('createAnimationClip omits expression/lookAt tracks when the VRM lacks those features', () => {
    const anim = new VRMAnimation();
    anim.humanoidTracks.rotation.set('head', new THREE.QuaternionKeyframeTrack('orig', [0], [0, 0, 0, 1]));
    anim.expressionTracks.set('happy', new THREE.NumberKeyframeTrack('orig2', [0], [1]));
    const vrm = {
      meta: { metaVersion: '1' },
      humanoid: {
        getNormalizedBoneNode: (name) => (name === 'head' ? { name: 'Head_Node' } : null),
        getNormalizedAbsolutePose: () => ({ hips: { position: [0, 1, 0] } }),
      },
      expressionManager: null,
      lookAt: null,
    };
    const clip = anim.createAnimationClip(vrm);
    expect(clip.tracks.length).toBe(1); // only the head rotation track
  });
});

describe('IdleManager', () => {
  let avatar, mgr;
  beforeEach(() => {
    vi.useFakeTimers();
    avatar = {
      ready: true,
      currentEmotion: 'neutral',
      _frequencyAnalyzerActive: false,
      _sleepBlinkOpenSec: null,
      setEmotion: vi.fn(),
      playAnimation: vi.fn(),
    };
  });

  it('starts ACTIVE', () => {
    mgr = new IdleManager(avatar, { timeBeforeIdleSec: 30, timeToSleepSec: 120 });
    expect(mgr.state).toBe('ACTIVE');
  });

  it('deactivate() schedules a transition to IDLE after timeBeforeIdleSec', () => {
    mgr = new IdleManager(avatar, { timeBeforeIdleSec: 30 });
    mgr.deactivate();
    expect(mgr.state).toBe('ACTIVE'); // not yet
    vi.advanceTimersByTime(30000);
    expect(mgr.state).toBe('IDLE');
  });

  it('IDLE transitions to SLEEPING after timeToSleepSec and calls onSleep', () => {
    const onSleep = vi.fn();
    mgr = new IdleManager(avatar, { timeBeforeIdleSec: 1, timeToSleepSec: 5, onSleep });
    mgr.deactivate();
    vi.advanceTimersByTime(1000); // -> IDLE
    expect(mgr.state).toBe('IDLE');
    vi.advanceTimersByTime(5000); // -> SLEEPING
    expect(mgr.state).toBe('SLEEPING');
    expect(onSleep).toHaveBeenCalled();
  });

  it('wake() from SLEEPING calls onWake and sets the avatar to relaxed then neutral', () => {
    const onWake = vi.fn();
    mgr = new IdleManager(avatar, { timeBeforeIdleSec: 1, timeToSleepSec: 1, onWake });
    mgr.deactivate();
    vi.advanceTimersByTime(2000); // -> SLEEPING
    expect(mgr.state).toBe('SLEEPING');
    mgr.wake();
    expect(mgr.state).toBe('ACTIVE');
    expect(onWake).toHaveBeenCalled();
    expect(avatar.setEmotion).toHaveBeenCalledWith('relaxed');
    vi.advanceTimersByTime(2000);
    expect(avatar.setEmotion).toHaveBeenCalledWith('neutral');
  });

  it('activate() while already ACTIVE is a harmless no-op', () => {
    mgr = new IdleManager(avatar, {});
    expect(() => mgr.activate()).not.toThrow();
    expect(mgr.state).toBe('ACTIVE');
  });

  it('disabled (enabled: false) ignores deactivate() entirely', () => {
    mgr = new IdleManager(avatar, { enabled: false, timeBeforeIdleSec: 1 });
    mgr.deactivate();
    vi.advanceTimersByTime(5000);
    expect(mgr.state).toBe('ACTIVE');
  });

  it('does not idle-prompt while the avatar is mid-emotion', () => {
    const onRequestIdlePrompt = vi.fn();
    avatar.currentEmotion = 'happy'; // non-neutral -> _processQueue must reschedule, not fire
    mgr = new IdleManager(avatar, { timeBeforeIdleSec: 1, timeToSleepSec: 100000, minIntervalSec: 1, maxIntervalSec: 1, onRequestIdlePrompt });
    mgr.deactivate();
    vi.advanceTimersByTime(1000); // -> IDLE, schedules first event in ~1s
    vi.advanceTimersByTime(1000); // event fires, but currentEmotion != neutral -> reschedule only
    expect(onRequestIdlePrompt).not.toHaveBeenCalled();
  });

  it('configure() updates intervals in milliseconds from the seconds-based options', () => {
    mgr = new IdleManager(avatar, { timeBeforeIdleSec: 30 });
    mgr.configure({ timeBeforeIdleSec: 5 });
    expect(mgr._timeBeforeIdle).toBe(5000);
  });

  it('destroy() clears all pending timers and restores blink state', () => {
    mgr = new IdleManager(avatar, { timeBeforeIdleSec: 1, sleepBlinkOpenSec: 8 });
    mgr.deactivate();
    avatar._sleepBlinkOpenSec = 8;
    mgr.destroy();
    expect(avatar._sleepBlinkOpenSec).toBeNull();
    // No further state changes should occur even if time advances after destroy()
    vi.advanceTimersByTime(60000);
    expect(mgr.state).toBe('ACTIVE');
  });
});

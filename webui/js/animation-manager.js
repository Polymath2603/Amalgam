/**
 * animation-manager.js — Procedural VRM bone animations with priority queue
 *
 * Generates AnimationClip instances targeting VRM humanoid bones and plays
 * them through THREE.AnimationMixer.  Provides a priority-based queue so
 * animations don't stomp on each other.
 *
 * Animations available as procedural fallback:
 *   greeting  — wave right hand
 *   nod       — head pitch down-and-back
 *   thinking  — head tilt + slight lean
 *   excited   — bounce + torso rock
 *
 * The clips are registered once after the VRM is loaded (humanoid bone
 * nodes are available).  If a VRM model lacks a required bone the clip
 * is silently skipped.
 *
 * Usage:
 *   const mgr = new AnimationManager(avatarRenderer);
 *   mgr.init(vrm, mixer);
 *   mgr.play('greeting', { priority: ANIM_PRIORITY.HIGH });
 *   mgr.update(delta);  // called from _animate()
 */

import * as THREE from 'three';

/* ── Priority levels ─────────────────────────────────────────────── */

export const ANIM_PRIORITY = {
    /** Yields to any queued animation; suitable for subtle idle motion. */
    LOW: 0,
    /** Plays after the current animation finishes. */
    NORMAL: 1,
    /** Interrupts any current LOW / NORMAL animation immediately. */
    HIGH: 2,
};

/* ── Quaternion helper ───────────────────────────────────────────── */

/**
 * Build a QuaternionKeyframeTrack from an array of keyframe descriptors.
 * Each descriptor: { time: number, euler: [x, y, z] }  (radians).
 */
function makeQuatTrack(boneName, keyframes) {
    const times = keyframes.map(kf => kf.time);
    const values = [];
    const euler = new THREE.Euler();
    const quat = new THREE.Quaternion();
    for (const kf of keyframes) {
        euler.set(kf.euler[0], kf.euler[1], kf.euler[2]);
        quat.setFromEuler(euler);
        values.push(quat.x, quat.y, quat.z, quat.w);
    }
    return new THREE.QuaternionKeyframeTrack(`${boneName}.quaternion`, times, values);
}

/* ── AnimationManager ────────────────────────────────────────────── */

export class AnimationManager {
    /**
     * @param {import('./avatar.js').AvatarRenderer} avatar  parent renderer
     */
    constructor(avatar) {
        this._avatar = avatar;
        this._vrm = null;
        this._mixer = null;
        this._clips = {};         // name → AnimationClip
        this._queue = [];         // pending items, sorted by priority desc
        this._current = null;     // { name, clip, action, priority, loop, crossFade }
        this._processing = false;
        this._defaultCrossFade = 0.25;

        /**
         * Called when a non-looping animation finishes and the queue is empty.
         * AvatarRenderer sets this to fade back to the idle loop.
         * @type {function|undefined}
         */
        this.onFinish = undefined;
    }

    /* ── Lifecycle ────────────────────────────────────────────────── */

    /**
     * Call after the VRM model and AnimationMixer are created.
     * Registers all procedural animation clips.
     */
    init(vrm, mixer) {
        this._vrm = vrm;
        this._mixer = mixer;
        this._registerProceduralAnimations();
    }

    /** Remove all animation state. */
    destroy() {
        this._queue = [];
        if (this._current) {
            this._current.action.stop();
            this._current = null;
        }
        this._clips = {};
        this._vrm = null;
        this._mixer = null;
        this._avatar = null;
    }

    /* ── Public API ───────────────────────────────────────────────── */

    /**
     * Queue (or immediately play) a registered procedural animation.
     *
     * @param {string}  name           One of 'greeting', 'nod', 'thinking', 'excited'
     * @param {object}  [opts]
     * @param {number}  [opts.priority=ANIM_PRIORITY.NORMAL]
     * @param {boolean} [opts.loop=false]
     * @param {number}  [opts.crossFade]  Cross-fade duration in seconds
     * @returns {boolean}  true if the clip was found and queued
     */
    play(name, opts = {}) {
        const clip = this._clips[name];
        if (!clip || !this._mixer) return false;

        const priority = opts.priority ?? ANIM_PRIORITY.NORMAL;
        const loop = opts.loop ?? false;
        const crossFade = opts.crossFade ?? this._defaultCrossFade;

        this._queue.push({ name, clip, priority, loop, crossFade });
        this._sortQueue();
        this._processQueue();
        return true;
    }

    /**
     * True if an animation is currently playing (not counting idle).
     */
    get isActive() {
        return this._current !== null;
    }

    /**
     * Name of the currently playing animation, or null.
     */
    get currentName() {
        return this._current?.name ?? null;
    }

    /**
     * Stop the named animation, or all if name omitted.
     */
    stop(name) {
        if (name) {
            // Remove from queue
            this._queue = this._queue.filter(item => item.name !== name);
            // Stop if currently playing
            if (this._current?.name === name) {
                this._current.action.stop();
                this._current = null;
                this._processQueue();
            }
        } else {
            this._queue = [];
            if (this._current) {
                this._current.action.stop();
                this._current = null;
            }
        }
    }

    /**
     * True if the animation is currently playing (queued or active).
     */
    isQueuedOrPlaying(name) {
        if (this._current?.name === name) return true;
        return this._queue.some(item => item.name === name);
    }

    /**
     * Called every frame from AvatarRenderer._animate() after mixer.update().
     * Detects end of non-looping animations and advances the queue.
     */
    update(delta) {
        if (!this._current || this._current.loop) return;

        const { action } = this._current;
        const clip = action.getClip();
        const remaining = clip.duration - action.time;

        // When the action is very close to its end, stop it cleanly and
        // advance the queue.  The 0.05 s margin prevents missed frames.
        if (remaining <= 0.05 || action.time >= clip.duration) {
            action.stop();

            // Keep a ref to the callback before nulling _current
            const cb = this._current.name === 'greeting' || this._current.name === 'excited'
                ? () => {
                    // After greeting/excited, auto-reset emotion to neutral
                    // if it was set by playGreeting/playExcited
                    if (this._avatar && this._avatar.currentEmotion !== 'neutral') {
                        this._avatar.setEmotion('neutral');
                    }
                  }
                : null;

            this._current = null;

            if (cb) cb();

            if (this._queue.length > 0) {
                this._processQueue();
            } else {
                this._processing = false;
                if (typeof this.onFinish === 'function') {
                    this.onFinish();
                }
            }
        }
    }

    /* ── Internal ─────────────────────────────────────────────────── */

    _sortQueue() {
        this._queue.sort((a, b) => b.priority - a.priority);
    }

    _processQueue() {
        if (this._queue.length === 0) {
            this._processing = false;
            return;
            }

        // Peek at the highest-priority item
        const next = this._queue[0];

        // If something is already playing, decide whether to interrupt
        if (this._current) {
            // HIGH priority always interrupts.  NORMAL interrupts LOW.
            // Otherwise the new item waits.
            if (next.priority >= ANIM_PRIORITY.HIGH ||
                (next.priority > this._current.priority)) {
                this._queue.shift();       // consume
                this._interrupt(next);
            }
            // else: wait for current to finish
            return;
        }

        // Nothing playing — start immediately
        this._queue.shift();
        this._startClip(next);
    }

    /** Interrupt current animation and start `item` immediately. */
    _interrupt(item) {
        if (this._current) {
            this._current.action.stop();
            this._current = null;
        }
        this._startClip(item);
    }

    /** Create (or reuse) an AnimationAction and fade it in. */
    _startClip(item) {
        if (!this._mixer) return;

        const { clip, loop, crossFade } = item;

        // Caching: THREE.AnimationMixer.clipAction returns the same
        // AnimationAction instance when called with the same clip object.
        const action = this._mixer.clipAction(clip);
        action.reset();
        action.loop = loop ? THREE.LoopRepeat : THREE.LoopOnce;
        action.clampWhenFinished = !loop;

        // Fade out idle/previous action
        // We don't use AvatarRenderer._fadeToAction here because the
        // AnimationManager manages its own lifecycle and notifies the
        // avatar via onFinish when done.
        const prev = this._current?.action;
        if (prev && prev !== action && prev.isRunning()) {
            prev.fadeOut(crossFade);
        }

        action.fadeIn(crossFade).play();

        this._current = { ...item, action };
        this._processing = false;
    }

    /* ── Procedural clip registration ─────────────────────────────── */

    /**
     * Build AnimationClip instances for each built-in gesture using the
     * VRM humanoid bone system.  If a model lacks a specific bone the
     * corresponding clip is not registered (silently skipped).
     */
    _registerProceduralAnimations() {
        if (!this._vrm?.humanoid) return;

        const g = this._createGreetingClip();
        if (g) this._clips.greeting = g;

        const n = this._createNodClip();
        if (n) this._clips.nod = n;

        const t = this._createThinkingClip();
        if (t) this._clips.thinking = t;

        const e = this._createExcitedClip();
        if (e) this._clips.excited = e;
    }

    /* ── Greeting: hand wave ──────────────────────────────────────── */

    _createGreetingClip() {
        // Right-hand oscillation (Z rotation) to produce a wave motion
        const handNode = this._vrm.humanoid.getNormalizedBoneNode('rightHand');
        if (!handNode) return null;

        const track = makeQuatTrack(handNode.name, [
            { time: 0.0,  euler: [0, 0, 0] },
            { time: 0.15, euler: [-0.04, 0, 0.17] },   // slight raise + roll
            { time: 0.35, euler: [-0.04, 0, -0.17] },  // wave left
            { time: 0.55, euler: [-0.04, 0, 0.17] },   // wave right
            { time: 0.75, euler: [-0.04, 0, -0.17] },  // wave left
            { time: 1.0,  euler: [-0.04, 0, 0.17] },   // wave right
            { time: 1.25, euler: [0, 0, 0] },           // return
            { time: 1.4,  euler: [0, 0, 0] },           // settle
        ]);

        return new THREE.AnimationClip('greeting', 1.4, [track]);
    }

    /* ── Nod: head pitch ──────────────────────────────────────────── */

    _createNodClip() {
        const headNode = this._vrm.humanoid.getNormalizedBoneNode('head');
        if (!headNode) return null;

        const track = makeQuatTrack(headNode.name, [
            { time: 0.0,  euler: [0, 0, 0] },
            { time: 0.12, euler: [0.22, 0, 0] },    // nod down  (~12.6°)
            { time: 0.30, euler: [0.22, 0, 0] },    // hold
            { time: 0.45, euler: [0.05, 0, 0] },    // slight overshoot up
            { time: 0.60, euler: [0, 0, 0] },        // return
        ]);

        return new THREE.AnimationClip('nod', 0.6, [track]);
    }

    /* ── Thinking: head tilt + lean ───────────────────────────────── */

    _createThinkingClip() {
        const headNode = this._vrm.humanoid.getNormalizedBoneNode('head');
        if (!headNode) return null;

        const headName = headNode.name;
        const tracks = [];

        // Head tilt slightly to the right + small upward pitch
        tracks.push(makeQuatTrack(headName, [
            { time: 0.0,  euler: [0, 0, 0] },
            { time: 0.6,  euler: [-0.06, 0.1, 0.12] },   // tilt right, look up
            { time: 2.0,  euler: [-0.06, 0.1, 0.12] },   // hold
            { time: 2.8,  euler: [0, 0, 0] },             // return
        ]));

        // Upper chest subtle lean forward
        const chestNode = this._vrm.humanoid.getNormalizedBoneNode('upperChest');
        if (chestNode) {
            tracks.push(makeQuatTrack(chestNode.name, [
                { time: 0.0,  euler: [0, 0, 0] },
                { time: 0.8,  euler: [0.04, 0, 0] },      // lean forward
                { time: 2.0,  euler: [0.04, 0, 0] },      // hold
                { time: 2.8,  euler: [0, 0, 0] },          // return
            ]));
        }

        return new THREE.AnimationClip('thinking', 2.8, tracks);
    }

    /* ── Excited: bounce + torso rock ─────────────────────────────── */

    _createExcitedClip() {
        const tracks = [];

        // Hips gentle side sway
        const hipsNode = this._vrm.humanoid.getNormalizedBoneNode('hips');
        if (hipsNode) {
            tracks.push(makeQuatTrack(hipsNode.name, [
                { time: 0.0,  euler: [0, 0, 0] },
                { time: 0.15, euler: [0, 0, 0.04] },
                { time: 0.35, euler: [0, 0, -0.04] },
                { time: 0.55, euler: [0, 0, 0.04] },
                { time: 0.75, euler: [0, 0, -0.04] },
                { time: 1.0,  euler: [0, 0, 0] },
                { time: 1.2,  euler: [0, 0, 0] },
            ]));
        }

        // Upper chest bounce (forward-back rock)
        const chestNode = this._vrm.humanoid.getNormalizedBoneNode('upperChest');
        if (chestNode) {
            tracks.push(makeQuatTrack(chestNode.name, [
                { time: 0.0,  euler: [0, 0, 0] },
                { time: 0.15, euler: [0.06, 0, 0] },
                { time: 0.35, euler: [-0.04, 0, 0] },
                { time: 0.55, euler: [0.06, 0, 0] },
                { time: 0.75, euler: [-0.04, 0, 0] },
                { time: 1.0,  euler: [0.02, 0, 0] },
                { time: 1.2,  euler: [0, 0, 0] },
            ]));
        }

        if (tracks.length === 0) return null;
        return new THREE.AnimationClip('excited', 1.2, tracks);
    }
}

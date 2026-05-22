const ANIM = (name) => `/static/animations/${name}.vrma`;

const EMOTION_ANIM_MAP = {
    happy:       [ANIM('dance'), ANIM('hello'), ANIM('greeting')],
    sad:         [ANIM('squat'), ANIM('idle_loop')],
    angry:       [ANIM('shoot'), ANIM('peaceSign')],
    surprised:   [ANIM('showFullBody'), ANIM('peaceSign')],
    thinking:    [ANIM('modelPose'), ANIM('idle_loop')],
    relaxed:     [ANIM('idle_loop'), ANIM('modelPose')],
    confused:    [ANIM('peaceSign'), ANIM('showFullBody')],
    shy:         [ANIM('modelPose')],
    jealous:     [ANIM('shoot'), ANIM('peaceSign')],
    bored:       [ANIM('squat'), ANIM('idle_loop')],
    suspicious:  [ANIM('modelPose')],
    victory:     [ANIM('dance'), ANIM('spin')],
    sleep:       [ANIM('squat')],
    love:        [ANIM('hello'), ANIM('peaceSign')],
    excited:     [ANIM('dance'), ANIM('spin')],
};

export function getAnimationForEmotion(emotion) {
    if (!emotion) return null;
    const e = emotion.toLowerCase();
    const pool = EMOTION_ANIM_MAP[e];
    if (!pool || pool.length === 0) return null;
    return pool[Math.floor(Math.random() * pool.length)];
}

export function animUrl(name) {
    return ANIM(name);
}

export { EMOTION_ANIM_MAP, ANIM };

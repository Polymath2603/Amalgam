# Amalgam Feature Plan — Next 5 Most Impactful Features

**Date:** 2026-06-22
**Author:** Jcode Product Research Agent
**Basis:** Competitive analysis of Open-LLM-VTuber and amica vs Amalgam

---

## Key Finding: Critical Bug Discovered

During analysis, I discovered a **broken emotion pipeline** that undermines Amalgam's strongest differentiator (26-emotion system + VRMA animations). The WebSocket handler calls `setExpression()` instead of `setEmotion()` for emotion messages, which:

- Only maps 5 base VRM expressions (happy, angry, sad, relaxed, surprised)
- Loses all 21 extended emotions (shy, jealous, bored, suspicious, etc.)
- Never triggers VRMA animations tied to emotions
- Wastes the entire emotion candidate fallback system

This is the #1 priority fix.

---

## Feature 1: Fix Emotion Pipeline + Extended Emotion Mapping

**Name:** Fix Emotion Pipeline Bug
**Complexity:** Small (~1 hour)
**Impact:** Critical — unlocks the full 26-emotion system that's already built but broken

### Description

The WebSocket message handler in `ws.js` calls `setExpression()` for `emotion` messages (line 347), but `setExpression()` only supports 5 base expressions. It should call `setEmotion()` which handles all 26 emotions with VRM expression candidate fallbacks.

Additionally, `setExpression()` should be enhanced to forward to `setEmotion()` for the full emotion pipeline, and the procedural animation triggers (thinking, excited) should be extended to cover more emotions.

### Why It Matters

- The backend already generates 26 distinct emotions via `EMOTION_TAG_RE` in `core/agent/core.py`
- The avatar already has `setEmotion()` with 26-emotion candidate mapping in `EMOTION_CANDIDATES`
- But the frontend WS handler bypasses all of this with `setExpression()`
- Users see flat expressions when the avatar should be expressive

### Files to Change

| File | Change |
|------|--------|
| `webui/js/modules/ws.js` | Change `setExpression` → `setEmotion` for emotion messages (line 347-348) |
| `webui/js/avatar.js` | Extend `setExpression()` to forward to `setEmotion()` for backward compat |
| `webui/js/modules/ws.js` | Add procedural animation triggers for extended emotions (sad→nod, angry→nod, etc.) |

### Implementation Plan

**Step 1: Fix WS emotion handler (ws.js ~line 346-355)**

Change:
```javascript
} else if (data.type === 'emotion') {
    if (avatarRenderer) avatarRenderer.setExpression?.(data.emotion);
    if (avatarPreviewRenderer) avatarPreviewRenderer.setExpression?.(data.emotion);
    if (data.emotion === 'thinking' || data.emotion === 'think') {
        if (avatarRenderer) avatarRenderer.playThinking?.();
        ...
    }
}
```

To:
```javascript
} else if (data.type === 'emotion') {
    // Use setEmotion (not setExpression) to leverage full 26-emotion
    // candidate mapping and auto-neutral timer
    if (avatarRenderer) avatarRenderer.setEmotion?.(data.emotion);
    if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion?.(data.emotion);
    // Trigger procedural animations for specific emotions
    if (data.emotion === 'thinking' || data.emotion === 'think') {
        if (avatarRenderer) avatarRenderer.playThinking?.();
        if (avatarPreviewRenderer) avatarPreviewRenderer.playThinking?.();
    } else if (data.emotion === 'excited') {
        if (avatarRenderer) avatarRenderer.playExcited?.();
        if (avatarPreviewRenderer) avatarPreviewRenderer.playExcited?.();
    } else if (data.emotion === 'happy' || data.emotion === 'amused') {
        if (avatarRenderer) avatarRenderer.playGreeting?.();
        if (avatarPreviewRenderer) avatarPreviewRenderer.playGreeting?.();
    } else if (data.emotion === 'confused' || data.emotion === 'surprised') {
        if (avatarRenderer) avatarRenderer.playNod?.();
        if (avatarPreviewRenderer) avatarPreviewRenderer.playNod?.();
    }
}
```

**Step 2: Make setExpression delegate to setEmotion (avatar.js ~line 860)**

```javascript
setExpression(name) {
    // Delegate to setEmotion for full 26-emotion support with candidate fallback
    this.setEmotion(name);
}
```

**Step 3: Extend emotion tags in backend (core.py ~line 67-71)**

Add missing emotions to the recognized set:
```python
if emotion in {'neutral','joy','angry','sad','relaxed','surprised',
               'thinking','shy','excited','confident','tired','scared',
               'bored','loving', 'jealous', 'suspicious', 'worried',
               'victory', 'love', 'curious', 'amused', 'disgusted',
               'smug', 'concerned', 'embarrassed'}:
```

### Can Be Done in One Session: Yes

---

## Feature 2: Emotion-to-VRMA Auto-Animation

**Name:** Emotion-Triggered VRMA Animations
**Complexity:** Small (~2 hours)
**Impact:** High — avatar physically expresses emotions through body movement, not just face

### Description

When the backend sends an emotion signal, the frontend should automatically play the corresponding VRMA file if one exists. The character already has 15 VRMA files (anger, amusement, curiosity, confusion, dance, desire, annoyance, approval, nervousness, grief, etc.) but they're only used for hit-area interactions and micro-anims.

This feature creates an automatic mapping: emotion received → check for matching VRMA file → play it.

### Why It Matters

- VRMA files exist but are underutilized — only `idle_loop.vrma` plays automatically
- Other projects (amica) have 9+ VRMA animations triggered by events
- Physical expression + facial expression = much more believable avatar
- Dance.vrma could be triggered by "victory" or "excited" emotions

### Files to Change

| File | Change |
|------|--------|
| `webui/js/avatar.js` | Add `EMOTION_TO_VRMA` mapping constant and `playEmotionAnimation()` method |
| `webui/js/modules/ws.js` | Call `playEmotionAnimation()` when emotion messages arrive |
| `webui/js/avatar.js` | Integrate with `setEmotion()` to auto-play VRMA |

### Implementation Plan

**Step 1: Add emotion-to-VRMA mapping (avatar.js, near EMOTION_CANDIDATES)**

```javascript
/**
 * Emotion → VRMA animation file name mapping.
 * If an emotion has a matching VRMA, it plays automatically.
 */
const EMOTION_TO_VRMA = {
    angry:          'anger',
    annoyed:        'annoyance',
    amused:         'amusement',
    curious:        'curiosity',
    confused:       'confusion',
    happy:          'approval',      // happy → approval nod
    excited:        'dance',         // excited → dance
    sad:            'grief',
    bored:          null,            // no VRMA, just expression
    worried:        'nervousness',
    love:           'desire',
    shy:            'nervousness',
    jealous:        'annoyance',
    suspicious:     'nervousness',
};
```

**Step 2: Add playEmotionAnimation method (avatar.js)**

```javascript
/**
 * Play a VRMA animation matching the given emotion, if one exists.
 * Skipped if an animation is already playing or if no VRMA mapping exists.
 */
playEmotionAnimation(emotion) {
    const vrmaName = EMOTION_TO_VRMA[emotion];
    if (!vrmaName || this._animManager?.isActive) return;
    const url = `${BASE_URL}/characters/default/anim/${vrmaName}.vrma`;
    this.playAnimation(url);
}
```

**Step 3: Wire into setEmotion (avatar.js, at end of setEmotion method)**

```javascript
// After setting the VRM expression, also trigger a VRMA body animation
this.playEmotionAnimation(emotion);
```

### Can Be Done in One Session: Yes

---

## Feature 3: Bark TTS Provider

**Name:** Bark TTS Integration
**Complexity:** Medium (~3-4 hours)
**Impact:** High — adds offline multilingual TTS with expressive voice generation

### Description

Integrate Bark (by Suno AI) as a new TTS provider. Bark is a transformer-based text-to-audio model that can generate highly expressive speech including laughing, crying, music, and non-verbal sounds. It runs locally via the `bark` Python package.

### Why It Matters

- Open-LLM-VTuber supports 20+ TTS providers; Amalgam has ~12
- Bark is unique: it generates non-speech sounds (laughter, sighs) natively
- Fully offline with no API key required
- Supports 13 languages
- Popular in the VRM/VTuber community

### Files to Change

| File | Change |
|------|--------|
| `backend/core/voice/tts/bark_provider.py` | **NEW** — Bark TTS provider |
| `backend/core/voice/tts/router.py` | Register `bark` in `_get_provider_classes()` |
| `webui/js/modules/settings-schema.js` | Add `bark` to TTS engine options + config fields |
| `backend/core/config/settings.py` | Add Bark defaults to profile presets |

### Implementation Plan

**Step 1: Create `backend/core/voice/tts/bark_provider.py`**

```python
"""Bark TTS provider (Suno AI). Runs locally, supports 13 languages."""
import asyncio
import logging
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


class BarkProvider:
    """TTS via the Bark model (suno/bark)."""
    name = "bark"

    def __init__(self, voice_config: dict):
        self._config = voice_config or {}
        self._model = None
        self._speaker = self._config.get("speaker", "v2/en_speaker_0")
        self._sample_rate = self._config.get("sample_rate", 24000)
        self._temperature = self._config.get("temperature", 0.7)

    def _ensure_model(self):
        if self._model is not None:
            return
        from bark import SAMPLE_RATE, generate_audio, preload_models
        preload_models()
        self._model = generate_audio  # store the function
        self._sample_rate = SAMPLE_RATE

    async def synthesize(self, text: str, ref_audio=None, emotion="neutral",
                         **kwargs) -> np.ndarray:
        """Generate audio from text using Bark."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._generate, text)

    def _generate(self, text: str) -> np.ndarray:
        self._ensure_model()
        from bark import generate_audio
        audio = generate_audio(
            text,
            history_prompt=self._speaker,
            text_temp=self._temperature,
        )
        return (audio * 32767).astype(np.int16)

    async def close(self):
        pass
```

**Step 2: Register in TTS router (`router.py`)**

```python
elif name == "bark":
    from .bark_provider import BarkProvider
    return BarkProvider(voice or {})
```

**Step 3: Add to settings schema (`settings-schema.js`)**

Add `"bark"` to the `tts_engine` options array:
```javascript
options: ["edge-tts", "openvoice", "elevenlabs", "openai-tts", "speecht5",
          "alltalk", "piper", "coqui-local", "kokoro", "bark"],
```

Add conditional fields for Bark:
```javascript
bark_speaker: {
    label: "Bark Speaker",
    type: "select",
    key: "voice.bark.speaker",
    options: [
        "v2/en_speaker_0", "v2/en_speaker_1", "v2/en_speaker_2",
        "v2/en_speaker_3", "v2/en_speaker_4", "v2/en_speaker_5",
        "v2/zh_speaker_0", "v2/ja_speaker_0", "v2/ko_speaker_0",
    ],
    show_if: { field: "tts_engine", equals: "bark" },
    description: "Bark voice preset",
},
bark_temperature: {
    label: "Temperature",
    type: "range",
    key: "voice.bark.temperature",
    min: 0.1, max: 1.5, step: 0.1,
    show_if: { field: "tts_engine", equals: "bark" },
    description: "Lower = more stable, higher = more expressive",
},
```

**Step 4: Add dependency**
```
pip install git+https://github.com/suno-ai/bark.git
```

### Can Be Done in One Session: Yes

---

## Feature 4: Vision/Camera Integration

**Name:** Camera Vision for Avatar
**Complexity:** Large (~6-8 hours)
**Impact:** High — avatar can "see" the user and respond to visual context

### Description

Allow the avatar to see the user through their webcam and respond to visual input. This pipeline captures a webcam frame, sends it as base64 to a vision-capable LLM (GPT-4V, LLaVA, Gemini Vision), and integrates the description into the conversation context.

Both Open-LLM-VTuber and amica have this feature. It's a key differentiator for companion-mode use cases.

### Why It Matters

- "My AI can see me" is a wow-factor feature
- Enables photo description, makeup feedback, sign language
- Complements companion mode (AI notices what you're wearing, etc.)
- Both competitor projects have it

### Files to Change

| File | Change |
|------|--------|
| `webui/js/vision.js` | **NEW** — Camera capture, frame extraction, WebSocket send |
| `webui/js/app.js` | Initialize vision module, wire to UI toggle |
| `webui/js/modules/settings-schema.js` | Add vision settings (capture interval, enabled) |
| `backend/api/ws/handler.py` | Handle `vision_frame` messages, integrate into agent context |
| `backend/core/agent/core.py` | Support image context in `handle_user_input()` |

### Implementation Plan

**Step 1: Create `webui/js/vision.js`**

```javascript
/**
 * vision.js — Camera capture for avatar vision
 * Captures webcam frames and sends them to the backend for vision analysis.
 */
import { getWs } from './modules/state.js';
import { getSettings } from './modules/state.js';

let _stream = null;
let _intervalId = null;
let _canvas = null;
let _ctx = null;
let _enabled = false;

export async function startVision() {
    if (_enabled) return;
    try {
        _stream = await navigator.mediaDevices.getUserMedia({
            video: { width: 320, height: 240, facingMode: 'user' }
        });
        const video = document.createElement('video');
        video.srcObject = _stream;
        video.setAttribute('playsinline', '');
        await video.play();
        _canvas = document.createElement('canvas');
        _canvas.width = 320;
        _canvas.height = 240;
        _ctx = _canvas.getContext('2d');
        _enabled = true;
        const interval = getSettings()?.vision?.interval || 10000; // every 10s
        _intervalId = setInterval(() => captureFrame(video), interval);
    } catch (e) {
        console.warn('[Vision] Camera access denied:', e);
    }
}

function captureFrame(video) {
    if (!_enabled || !video || !video.videoWidth) return;
    _ctx.drawImage(video, 0, 0, 320, 240);
    const dataUrl = _canvas.toDataURL('image/jpeg', 0.6);
    const base64 = dataUrl.split(',')[1];
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'vision_frame', image: base64 }));
    }
}

export function stopVision() {
    _enabled = false;
    if (_intervalId) { clearInterval(_intervalId); _intervalId = null; }
    if (_stream) { _stream.getTracks().forEach(t => t.stop()); _stream = null; }
}
```

**Step 2: Handle vision_frame in backend handler**

In `handler.py`, add handling:
```python
elif data.get("type") == "vision_frame":
    import base64
    img_data = base64.b64decode(data["image"])
    # Store as pending image context for next user message
    self._pending_images = getattr(self, '_pending_images', [])
    self._pending_images.append(img_data)
```

Then pass `images=self._pending_images` to `agent().handle_user_input()` in the main handler and clear after use.

**Step 3: Add to settings schema**

```javascript
vision_enabled: {
    label: "Camera Vision",
    type: "toggle",
    key: "vision.enabled",
    description: "Allow avatar to see through webcam",
},
vision_interval: {
    label: "Capture Interval (ms)",
    type: "number",
    key: "vision.interval",
    min: 5000, max: 60000, step: 5000,
    description: "How often to capture a frame",
},
```

### Can Be Done in One Session: Tight, but yes with focus

---

## Feature 5: Group Conversation (Multi-AI)

**Name:** Group Conversation Support
**Complexity:** Large (~8-10 hours)
**Impact:** Medium-High — unique feature only Open-LLM-VTuber has among VRM projects

### Description

Allow multiple AI characters to participate in a single conversation, each with their own VRM model, personality, and voice. Users can chat with a group of AI companions who interact with each other and the user.

### Why It Matters

- Only Open-LLM-VTuber has this feature among the three projects
- Enables creative use cases: AI study groups, roleplay scenarios, debate partners
- Each character could have different LLM providers/models for variety
- Leverages Amalgam's existing character system (multiple characters in `/characters/`)

### Files to Change

| File | Change |
|------|--------|
| `backend/api/ws/handler.py` | Add group message routing |
| `backend/core/agent/group_agent.py` | **NEW** — Orchestrates multiple agents |
| `webui/js/app.js` | Multi-avatar layout, group chat UI |
| `webui/js/avatar.js` | Support multiple avatar instances |
| `webui/js/modules/settings-schema.js` | Group conversation settings |
| `webui/css/style.css` | Multi-avatar layout styles |

### Implementation Plan (High-Level)

**Step 1: Group Agent (`group_agent.py`)**

```python
class GroupAgent:
    """Orchestrates a conversation between multiple AI characters."""
    
    def __init__(self, characters: list[dict]):
        self.agents = {}
        self.speaking_order = []
        self.turn_index = 0
        for char in characters:
            self.agents[char['id']] = AgentFactory.create(
                char.get('agent_type', 'basic'), ...
            )
    
    async def handle_user_input(self, text, **kwargs):
        """Each character responds in turn, or the most relevant one."""
        # Strategy: all characters see the message, each responds
        # with a short delay between them
        for char_id in self.speaking_order:
            agent = self.agents[char_id]
            # yield emotion + text for each character
            async for chunk in agent.handle_user_input(text, **kwargs):
                yield (char_id, chunk)
```

**Step 2: Multi-avatar layout**

Split the avatar canvas into a grid, each cell hosting its own `AvatarRenderer` instance. On emotion/volume messages, route to the correct avatar by character ID.

**Step 3: Group chat settings**

```javascript
group_enabled: {
    label: "Group Mode",
    type: "toggle",
    key: "group.enabled",
    description: "Enable multi-character conversations",
},
group_characters: {
    label: "Active Characters",
    type: "multiselect",
    key: "group.characters",
    dynamic_characters: true,
    description: "Characters to include in group chat",
},
```

### Can Be Done in One Session: No — requires 2-3 sessions

---

## Implementation Priority Summary

| # | Feature | Complexity | Impact | One Session? |
|---|---------|-----------|--------|-------------|
| 1 | Fix Emotion Pipeline Bug | Small | Critical | Yes |
| 2 | Emotion-to-VRMA Auto-Animation | Small | High | Yes |
| 3 | Bark TTS Provider | Medium | High | Yes |
| 4 | Vision/Camera Integration | Large | High | Tight |
| 5 | Group Conversation | Large | Medium-High | No (2-3 sessions) |

### Recommended Session Order

**Session 1:** Features 1 + 2 (Fix emotion pipeline + VRMA auto-animation)
**Session 2:** Feature 3 (Bark TTS)
**Session 3:** Feature 4 (Vision/Camera)
**Session 4-5:** Feature 5 (Group Conversation)

---

## Appendix: Already-Implemented Features (Discovered During Analysis)

The comparison report recommended many features that are **already implemented** in the current codebase:

| Report Recommendation | Status | Location |
|----------------------|--------|----------|
| Procedural breathing animation | ✅ Done | `avatar.js` → `_applyBreathing()` |
| VRM drag-and-drop loading | ✅ Done | `avatar.js` → `_setupDragAndDrop()` |
| Translation (DeepLX) | ✅ Done | `backend/core/translation/deeplx.py` |
| Parallel TTS with ordered delivery | ✅ Done | `OrderedTTSScheduler` in `tts_service.py` |
| Silero VAD | ✅ Done | `backend/voice/vad.py` |
| Memory graph visualization | ✅ Done | `webui/js/modules/memory-graph.js` |
| VRM animation files (15 files) | ✅ Done | `data/characters/default/anim/*.vrma` |
| Procedural animations (greeting, nod, thinking, excited) | ✅ Done | `animation-manager.js` |
| Emotion tags in agent output | ✅ Done | `core/agent/core.py` → `_process_tags()` |
| 26-emotion system | ✅ Done | `avatar.js` → `EMOTION_CANDIDATES` |
| Life state machine (idle→bored→sleeping) | ✅ Done | `avatar.js` → `initLifeStateMachine()` |
| Companion mode | ✅ Done | `companion.js` + `companion.py` |

The competitive gap is smaller than the report suggests. The real opportunities are in **fixing the emotion pipeline bug** and **adding the missing high-impact features** (Bark, Vision, Group Chat).

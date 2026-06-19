# TTS Providers Subsystem — Code Quality Analysis

**19 files analyzed** in `backend/core/voice/tts/`

---

## 1. ARCHITECTURAL ISSUES

### 1.1 Inconsistent Return Signature from `synthesize()`
**Files:** Nearly all providers
**Lines:** `base.py:12`, `router.py:143-180`, and every provider's `synthesize()` method

The base class defines the return signature as `tuple[np.ndarray, list[dict]|None, int]` but:
- **OpenVoiceProvider** (`openvoice_provider.py:46`) returns `(audio_np, visemes)` — only 2 elements, no sample rate
- The router (`router.py:158-171`) has special-case unpacking with `*_` wildcards and type checks (`isinstance(result, tuple) and len(result) >= 3`) to handle both 2-tuple and 3-tuple returns
- This is a fragile contract violation that silently swallows errors

**Impact:** Every call site in the router must handle both shapes, creating technical debt. If a new provider forgets the third element, there's no compile-time check.

### 1.2 No Formal Provider Interface / ABC
**File:** `base.py:6-21`

`TTSProvider` is a plain class with `raise NotImplementedError` — it should be an `abc.ABC` with `@abstractmethod`. There's no enforcement that subclasses implement `synthesize()`, `close()`, or `configure()`.

**Impact:** If a provider forgets to implement `synthesize()`, the error only manifests at runtime when the method is called.

### 1.3 Mixed Responsibilities in Router
**File:** `router.py:8-180`

`TTSRouter` does too much:
- Provider lifecycle management (lines 52-64)
- Engine-specific configuration methods (lines 86-123)
- Fallback logic for OpenVoice (lines 157-172)
- Sample-rate mapping (lines 125-141)
- Emotion→SSML parameter knowledge

Each of these should be separated. The engine-specific knowledge (emotion maps, sample rates) leaks into the router.

### 1.4 OpenVoice Fallback Logic in Router
**File:** `router.py:150-172`

The OpenVoice fallback to edge-tts is hardcoded in the router's `_do_synthesize()` method. This is a provider-specific concern that doesn't belong in the general routing layer. If other providers need fallback, this pattern doesn't scale.

### 1.5 No Retry / Circuit-Breaker Pattern
**All HTTP providers**

No provider implements retry logic for transient failures (network timeouts, 5xx errors). On failure, all immediately return silence arrays. This makes the system fragile against transient cloud API issues.

### 1.6 Lazy Import in `_get_provider_classes` is Fragile
**File:** `router.py:17-33`

All 15 provider classes are imported inside a classmethod on first access. This is fine for lazy loading, but:
- No error isolation — if one provider's module has an ImportError, all providers fail to load
- No mechanism to gracefully skip unavailable providers (e.g., optional GPU dependencies)

---

## 2. ANTI-PATTERNS

### 2.1 Stub Viseme Data Across 5 Providers
**Files:**
- `deepgram_provider.py:46` — `visemes = ["A"]*(len(text)//2)`
- `dashscope_provider.py:47` — same
- `mlx_provider.py:59` — same
- `volcengine_provider.py:72` — same
- `rvc_provider.py:86` — same
- `openvoice_provider.py:45` — same

These generate fake placeholder viseme data (`["A"]*...`) instead of `None` or an empty list. The router/consumers then receive garbage viseme data that looks legitimate but conveys no real information.

### 2.2 Duplicated WAV Decoding Logic — 5 Files
**Files:**
- `kokoro_provider.py:34-38`
- `alltalk_provider.py:77-81`
- `coqui_local_provider.py:36-41`
- `openai_tts_provider.py:49-53`
- `piper_provider.py:33-37`

All contain the identical pattern:
```python
import io
import wave
with io.BytesIO(audio_bytes) as buf:
    with wave.open(buf, "rb") as wf:
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        audio_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
```

This should be a shared utility function.

### 2.3 Duplicated FFmpeg MP3→WAV Conversion — 2 Files
**Files:**
- `edge_tts_provider.py:107-115`
- `elevenlabs_provider.py:151-154`

Both spawn `ffmpeg` to convert MP3 to WAV with nearly identical arguments. This should be a shared helper.

### 2.4 Empty Tuple / Zero-Array Noise Returned on Every Error
**All providers**

Every single error path returns `np.zeros(0, dtype=np.float32), [], 16000` (or similar). This means:
- Callers cannot distinguish "empty input" from "API error" from "network timeout" from "auth failure"
- Logging is the only diagnostics mechanism
- The caller gets valid-looking output for any failure

### 2.5 Implicit `asyncio.get_event_loop()` Calls
**Files:**
- `azure_provider.py:46`
- `openvoice_provider.py:37`
- `mlx_provider.py:47`
- `speecht5_provider.py:43`

`asyncio.get_event_loop()` is deprecated in Python 3.10+ in favor of `asyncio.get_running_loop()`. These calls will fail if called outside an event loop context.

### 2.6 Emotion Parameters Silently Ignored / **CRITICAL BUG**
**CRITICAL BUG: 7 provider classes** (`KokoroProvider`, `AllTalkProvider`, `CoquiLocalProvider`, `PiperProvider`, `OpenAITTSProvider`, `SpeechT5Provider`, `OpenVoiceProvider`) define `synthesize(self, text, ref_audio=None)` **without** an `emotion` parameter and **without** `**kwargs`.

The router at `router.py:174` calls:
```python
result = await provider.synthesize(text, ref_audio=ref_audio, emotion=emotion)
```

This will raise `TypeError: synthesize() got an unexpected keyword argument 'emotion'` for all 7 providers listed above.

### 2.7 Unused Imports
**Files:**
- `rvc_provider.py:2` — `import json` (never used)
- `dashscope_provider.py:2` — `import json` (never used)
- `volcengine_provider.py:2-8` — `hashlib`, `hmac`, `base64`, `urlencode` all imported but never used

---

## 3. CODE QUALITY PROBLEMS

### 3.1 Inconsistent Spacing Convention
**All files**

The entire codebase uses non-standard spacing: `logger .error (f"...")` instead of `logger.error(f"...")`, `self ._api_key` instead of `self._api_key`. This is consistent within the TTS tree but inconsistent with Python PEP 8 conventions.

### 3.2 Missing Type Annotations
- `router.py:156` — `_do_synthesize(self, provider, ...)` — `provider` has no type hint
- `base.py:12` — `synthesize()` return type is almost correct but `list[dict]|None` should be `Optional[list[dict]]` for broader py3.8-3.9 compatibility

### 3.3 Module-Level Imports Inside Functions
- `edge_tts_provider.py:8-11` — `import edge_tts` at module level (good, for optional dep)
- But several providers do `import torch` or other heavy imports inside methods (`speecht5_provider.py:23`, `speecht5_provider.py:42`)
- `kokoro_provider.py:32-33`, `alltalk_provider.py:75-76`, etc. — `import io; import wave` inside methods (inconsistent with each other)

### 3.4 Hardcoded Numeric Constants
- `elevenlabs_provider.py:33` — Hardcoded voice ID `"21m00Tcm4TlvDq8ikWAM"` as default
- `edge_tts_provider.py:21` — `TICKS_PER_SECOND = 10_000_000` (magic constant)
- `azure_provider.py:18` — `TICKS_PER_MS = 10_000` (magic constant)

---

## 4. MISSING ERROR HANDLING

### 4.1 No API Key Validation at Configure Time
**All API-key providers** (Azure, ElevenLabs, Deepgram, DashScope, OpenAI, Volcengine)

API keys are accepted in `configure()` but never validated until the first `synthesize()` call. The user gets no early feedback about invalid credentials.

### 4.2 Network Errors Not Distinguished from API Errors
**All HTTP providers**

All exceptions are caught with `except Exception as e:` and logged generically. There's no distinction between:
- `httpx.TimeoutException` (transient, retryable)
- `httpx.HTTPStatusError` (depends on status code)
- `httpx.ConnectError` (infrastructure failure)
- `json.JSONDecodeError` (protocol mismatch)

### 4.3 No Streaming Timeout for Long Utterances
**Files:** All HTTP streaming providers (ElevenLabs, Deepgram, etc.)

The `httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))` sets a 60s total timeout. For very long TTS inputs, this could timeout prematurely. No segmentation or length limits are enforced.

### 4.4 No Retry for Server Errors
**All HTTP providers**

A 502/503/504 from the API immediately returns silence. No exponential backoff or retry logic exists anywhere.

---

## 5. PERFORMANCE BOTTLENECKS

### 5.1 Per-Instance HTTP Clients
**All HTTP providers**

Each provider creates its own `httpx.AsyncClient` with no connection pooling across providers. If an application creates multiple router instances (or reconfigures), it creates multiple TCP connection pools to the same API endpoints.

### 5.2 No Response Streaming / Chunked Processing
**All providers**

All providers accumulate the full audio response in memory before returning. For long TTS outputs (minutes of speech), this could use significant memory. No provider supports true streaming playback.

### 5.3 Redundant `rstrip('/')` Calls
**Files:**
- `kokoro_provider.py:22` — `self._url.rstrip('/')` even though already stripped in `configure()`
- `alltalk_provider.py:32` — same
- `coqui_local_provider.py:24` — same
- `piper_provider.py:22` — same

These re-strip on every `synthesize()` call, despite being already stripped in `configure()`.

### 5.4 SpeechT5 Model Loading on First Call
**File:** `speecht5_provider.py:17-37`

The SpeechT5 model is loaded lazily on first `synthesize()` call. This is good for startup time, but:
- No progress indication for the ~2GB model download
- If it fails, the user gets no feedback until their first TTS request
- No model caching/sharing across instances

### 5.5 Synchronous Inference via run_in_executor — Correct but Heavy
**Files:** `azure_provider.py:46`, `openvoice_provider.py:37-38`, `mlx_provider.py:47`, `speecht5_provider.py:43-44`

These correctly offload blocking work to a thread pool, but each synthesize call blocks a thread for potentially seconds. For concurrent TTS requests, this could exhaust the default thread pool.

---

## 6. DUPLICATION BETWEEN PROVIDERS

### 6.1 WAV Decoding — 5× Duplicated
**Files:** `kokoro_provider.py:34-38`, `alltalk_provider.py:77-81`, `coqui_local_provider.py:36-41`, `openai_tts_provider.py:49-53`, `piper_provider.py:33-37`

Identical 7-line WAV byte decoding pattern.

### 6.2 FFmpeg MP3→WAV — 2× Duplicated
**Files:** `edge_tts_provider.py:107-115`, `elevenlabs_provider.py:151-154`

Nearly identical ffmpeg invocation.

### 6.3 HTTP Client Initialization — 7× Duplicated
**Files:** Every HTTP-based provider

All create `httpx.AsyncClient(timeout=httpx.Timeout(...))` in `__init__`. Timeout values vary: 60s (ElevenLabs, Deepgram, Coqui, Piper, Volcengine, OpenAI), 120s (DashScope, AllTalk, RVC).

### 6.4 `configure()` Pattern — 8× Duplicated
**Files:** Azure, ElevenLabs, Deepgram, DashScope, OpenAI, AllTalk, Piper, Kokoro, Coqui, Volcengine, RVC

Every provider follows `configure(self, *args)` pattern that sets `self._*` attributes. No standardized protocol.

### 6.5 Error Return Pattern — All 15 Providers
Every `synthesize()` catches `Exception` and returns `np.zeros(...), [], <sr>`. This is consistent but could be a mixin or decorator.

---

## 7. DESIGN IMPROVEMENT OPPORTUNITIES

### 7.1 Return a Result Type Instead of Tuples
**Severity: High**

Replace the fragile tuple return with a dataclass:
```python
@dataclass
class TTSResult:
    audio: np.ndarray
    sample_rate: int
    visemes: Optional[list[dict]] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
```

### 7.2 Optional Dependency Handling
Several providers (`edge_tts`, `azure`, `speecht5`, `mlx`) have optional system dependencies that are only checked at runtime. Consider:
- A `check_dependencies()` classmethod that returns missing deps
- Graceful provider registration that skips providers with missing deps at import time
- User-visible dependency reporting

Currently only `edge_tts_provider.py` has a proper `_EDGE_TTS_AVAILABLE` check. Others (Azure, SpeechT5, MLX) only check at import time inside methods or rely on try/except ImportError.

### 7.3 Standardize the `close()` Protocol
`close()` is defined only in some providers (ElevenLabs:172, Deepgram:52, Kokoro:44, AllTalk:87, Coqui:47, Piper:43, DashScope:53, Volcengine:78, RVC:92, Azure:120). Others (EdgeTTS, OpenVoice, MLX, SpeechT5) have no `close()`. The router never calls `close()`. This is a resource leak for HTTP clients.

### 7.4 Centralized Viseme Processing
Only Edge-TTS (`edge_tts_provider.py:133`) and Azure (`azure_provider.py:85-115`) produce real viseme data from API responses. ElevenLabs produces word-level timing and converts to visemes. The other 5 providers with stub visemes should return `None` rather than fake data.

**Recommendation:** Define a clear "viseme tiers":
- Tier 0: No viseme data → return `None`
- Tier 1: Word-level timing only → use `viseme_schedule_from_words()`
- Tier 2: Real phoneme-level visemes → return as-is

### 7.5 RVC Architecture Anomaly
**File:** `rvc_provider.py:12-93`

RVC is not a TTS provider — it's a voice conversion post-processor. It takes audio from another provider and applies RVC conversion. Its placement as a `TTSProvider` subclass is architecturally misleading. It should be a separate processing layer or pipeline stage.

### 7.6 Missing `__init__.py` Exports
**File:** `__init__.py:1`

Only exports `TTS` (the router alias). Individual providers are not exported, making direct `from backend.core.voice.tts import EdgeTTSProvider` unsupported. The router uses lazy imports internally to avoid this.

### 7.7 No Provider Registry
The provider-to-class mapping in `router.py:33-49` is hardcoded. Adding a new provider requires:
1. Creating the file
2. Adding the import in `_get_provider_classes()`
3. Adding the mapping
4. Adding a `configure_*` method
5. Adding the engine name to `SUPPORTED_ENGINES`
6. Adding sample rate to `_SR_MAP`

This should be a decorator-based registry (`@register_provider("my-engine")`) that auto-discovers and registers providers.

### 7.8 Word-to-Viseme Heuristic Could Be More Accurate
**File:** `word_to_viseme.py:13-104`

The grapheme-to-viseme mapping is purely heuristic with no actual phoneme database. It uses English letter patterns to guess visemes. This is acknowledged in the docstring but could be improved with a proper G2P engine (e.g., `g2p-en` or `phonemizer`).

---

## SUMMARY

| Category | Count | Key Issues |
|---|---|---|
| **Bugs** | **1 critical** | `emotion` keyword passed to 7 providers without `emotion` param → `TypeError` at router.py:174 |
| **Anti-patterns** | 8 | Stub visemes (5 providers), duplicated WAV decode (5x), duplicated ffmpeg (2x), silenced errors, deprecated asyncio API, unused imports |
| **Duplication** | 5 areas | WAV decode (5x), ffmpeg (2x), HTTP client init (7x), configure pattern (8x), error return (15x) |
| **Missing error handling** | 4 areas | No retry, no credential validation, undifferentiated exceptions, no streaming timeout |
| **Performance issues** | 5 | Per-instance HTTP clients, redundant rstrip(), no streaming, large model loading, thread pool saturation risk |
| **Design improvements** | 8 | Result type, dependency checking, close() protocol, viseme tiers, RVC architecture, provider registry, proper ABC, G2P accuracy |

### Critical Bug Detail
**7 provider classes** (`KokoroProvider`, `AllTalkProvider`, `CoquiLocalProvider`, `PiperProvider`, `OpenAITTSProvider`, `SpeechT5Provider`, `OpenVoiceProvider`) define `synthesize(self, text, ref_audio=None)` without an `emotion` parameter and without `**kwargs`. The router at **`router.py:174`** calls `await provider.synthesize(text, ref_audio=ref_audio, emotion=emotion)` which will raise **`TypeError: synthesize() got an unexpected keyword argument 'emotion'`** for all of these.

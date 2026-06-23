# Voice Layer Audit

Date: 2026-06-22

## 1. TTS Provider Discovery

**Status: ✅ Complete**

- `TTSRouter.SUPPORTED_ENGINES` lists 15 engines
- `TTSRouter._PROVIDER_CLASSES` maps all 15 (edge-tts, openvoice, elevenlabs, openai-tts, speecht5, alltalk, piper, coqui-local, kokoro, azure, dashscope, volcengine, deepgram, mlx, rvc)
- All 15 `*_provider.py` files present in `backend/core/voice/tts/`
- Perfect 1:1 match between files and registry entries

**Files found:** alltalk, azure, coqui_local, dashscope, deepgram, edge_tts, elevenlabs, kokoro, mlx, openai_tts, openvoice, piper, rvc, speecht5, volcengine

## 2. STT Provider Discovery

**Status: ✅ Complete**

- `STTRouter.SUPPORTED_ENGINES` lists 6 engines
- `STTRouter._PROVIDER_CLASSES` maps all 6 (browser, faster-whisper, openai-whisper, groq-whisper, whispercpp, deepgram)
- All 6 `*_provider.py` files present in `backend/voice/stt/`
- Perfect 1:1 match

**Files found:** browser, deepgram, faster_whisper, groq_whisper, openai_whisper, whispercpp

## 3. VoicePipeline Lifecycle

**Status: ❌ Missing methods**

Methods present:
- ✅ `__init__()` — with agent_callback, stt_engine, settings, on_speech_start, on_state_change
- ✅ `listen_loop()` — blocking loop (runs in background thread)
- ✅ `start_listening() / cancel_listening()` — async state transitions
- ✅ `start_speaking() / stop_speaking()` — async state transitions
- ✅ `interrupt()` — sync method for barge-in
- ✅ `stop_listening()` — sync stop of listen loop
- ✅ `reset()` — async forced reset
- ❌ **`start()`** — no top-level method to start pipeline lifecycle
- ❌ **`stop()`** — no top-level method for clean shutdown
- ❌ **`reconfigure()`** — no method to update settings at runtime

Settings propagation stub in `settings.py` (line ~270) imports `VoicePipeline` then logs but takes no action.

## 4. WakeWordRouter Provider Discovery

**Status: ❌ Missing provider discovery pattern**

- `WakeWordRouter` does NOT follow the `_PROVIDER_CLASSES` / `_get_provider_classes` pattern used by TTSRouter and STTRouter
- Instead uses a hardcoded if/else in `_create_provider()` that only handles `"openwakeword"`
- Only 1 provider file exists (`openwakeword_provider.py`), so nothing is missing yet, but the pattern is inconsistent and would require code changes to add new providers

## 5. stt/utils.py

**Status: ✅ Alive — NOT dead code**

- Contains `numpy_to_wav()` helper
- Imported via relative imports (`from .utils import numpy_to_wav`) by 4 STT providers:
  - `whispercpp_provider.py`
  - `deepgram_provider.py`
  - `groq_whisper_provider.py`
  - `openai_whisper_provider.py`
- The utility is actively used in their `transcribe()` methods

## 6. Browser STT (browser_provider.py)

**Status: ✅ Alive**

- `BrowserSTTProvider` is registered in `STTRouter._PROVIDER_CLASSES` under `"browser"`
- Imported and used in `STTRouter._get_provider_classes()`
- Active code path

## Fixes Applied

| Issue | Fix |
|-------|-----|
| VoicePipeline missing lifecycle methods | Added `start()`, `stop()`, `reconfigure()` |
| WakeWordRouter no discovery pattern | Added `_PROVIDER_CLASSES` / `_get_provider_classes()` |
| Settings propagation stub does nothing | Wired to call pipeline reconfigure via global registry |

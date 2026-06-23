# VOICE Subsystem — Aggressive Code Review

**Date:** 2026-06-22  
**Reviewer:** Jcode Agent  
**Scope:** Full read of every function in 30+ files of the TTS, STT, VAD, wakeword, pipeline, and WS service subsystems.

---

## Summary

| Severity | Count |
|----------|-------|
| 🔴 **CRITICAL** | 8 |
| 🟠 **HIGH** | 23 |
| 🟡 **MEDIUM** | 31 |
| 🔵 **LOW** | 19 |
| ⚪ **INFO/STYLE** | 14 |

---

## 1. `backend/core/voice/tts/base.py`

### 1.1 🔴 `retry_http` — fall-through returns `None` silently for 5xx
**File:** `base.py:54-55`  
**Issue:** When `response.status_code >= 500` and `attempt < max_retries`, the code falls through the `if`/`elif` and reaches `return None` at line 68 without logging. The `await asyncio.sleep(backoff * (2**attempt))` at line 57 runs but the function then returns `None` incorrectly.  
**Fix:** Change the logic so that only after exhausting all attempts does it return `None`:

```python
for attempt in range(1 + max_retries):
    try:
        response = await client.request(method, url, **kwargs)
        if response.status_code < 500:
            return response
        # 5xx — retry unless last attempt
        if attempt < max_retries:
            await asyncio.sleep(backoff * (2**attempt))
        else:
            return response  # return the 5xx response on last attempt
    except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
        last_exc = e
        if attempt < max_retries:
            await asyncio.sleep(backoff * (2**attempt))
        else:
            logger.error(...)
            return None
```

### 1.2 🟠 `retry_http` — unused import `Optional`
**File:** `base.py:3`  
**Issue:** `Optional` is imported but the return type annotation uses `Optional["httpx.Response"]` inside a string. The optional import is unused if the string annotation isn't resolved.  
**Fix:** Either use `from __future__ import annotations` or remove the unused import if the annotation is purely documentary.

### 1.3 🟡 `retry_http` — first attempt sleep on transient error is wrong
**File:** `base.py:63`  
**Issue:** On the first transient error (`attempt=0`), it sleeps `backoff * (2**0) = 0.5s`, but the code then falls through to `return None` at line 68 because the `if attempt < max_retries` guard only logs but doesn't `continue` the loop. The `continue` is missing.  
**Fix:** Replace `else: return None` at line 64-67 with `continue` so the loop retries.

### 1.4 🟡 `decode_wav` — no error handling for corrupt WAV
**File:** `base.py:23-28`  
**Issue:** `wave.open` can raise `wave.Error`, `EOFError`, or `struct.error` for malformed WAV data. No try/except.  
**Fix:** Wrap in try/except and return `(np.zeros(0, dtype=np.float32), 0)` on failure.

### 1.5 🔵 `decode_wav` — `target_sr` parameter unused
**File:** `base.py:12`  
**Issue:** The `target_sr` parameter is accepted but never used.  
**Fix:** Remove it or document that it's ignored.

---

## 2. `backend/core/voice/tts/router.py`

### 2.1 🟡 `synthesize_parallel` — Semaphore doesn't limit translation tasks
**File:** `router.py:167`  
**Issue:** The `sem` (Semaphore) is acquired inside `_work()` AFTER the work begins, but the translation step (lines 172-176) runs BEFORE the semaphore is acquired, meaning translation calls are unbounded.  
**Fix:** Move translation inside or restructure so translation is also bounded, or don't claim `max_concurrent` applies to translation.

### 2.2 🟠 `_do_synthesize` — OpenVoice fallback calls `synthesize()` without `ref_audio`
**File:** `router.py:229-230`  
**Issue:** When OpenVoice fails, the fallback to edge-tts calls `fallback.synthesize(text, emotion=emotion)` without `ref_audio`. This is fine for EdgeTTS (which ignores `ref_audio`), but the intent is unclear — the fallback should likely still use `ref_audio` for voice cloning engines.  
**Fix:** Pass `ref_audio` to the fallback.

### 2.3 🟠 `_do_synthesize` — fallback exception wraps the wrong try block
**File:** `router.py:218`  
**Issue:** The entire `_do_synthesize` has a single try/except (line 219-244). The OpenVoice fallback (lines 226-235) runs inside the same try block. If the fallback also fails, the inner `logger.error` is the only indication — the outer except at line 244 re-logged the same error again.  
**Fix:** Separate the fallback into its own try/except.

### 2.4 🟡 `voice.setter` — silently ignores errors setting voice on providers
**File:** `router.py:76-77`  
**Issue:** If any provider's `voice.setter` raises an exception (e.g., validation), it propagates and leaves some providers updated and others not.  
**Fix:** Wrap in try/except per provider, log individual failures.

### 2.5 🟡 `synthesize` — OpenVoice lock wraps full call but other engines don't lock
**File:** `router.py:212-214`  
**Issue:** Only OpenVoice uses the async lock. If the provider is reused across multiple `synthesize()` calls for other engines, there's no synchronization at the router level (providers handle it internally or not). This is inconsistent.  
**Fix:** Either lock all calls or document that providers must be thread-safe.

### 2.6 🟡 `configure_rvc` — sets upstream TTS on self.engine only if not "rvc"
**File:** `router.py:121-123`  
**Issue:** `rvc.set_tts_provider(upstream)` sets the **current engine's provider** as RVC's upstream. But `self.engine` might have changed between `configure_rvc()` and `synthesize()`. The upstream should be recorded by reference, not by current engine name at configure-time.  
**Fix:** Store the upstream provider reference directly.

### 2.7 🔵 `synthesize` return type annotation says `tuple` but no specific element types
**File:** `router.py:206`  
**Issue:** `->tuple` is vague. Should be `-> tuple[np.ndarray, list | None, int]`.  
**Fix:** Add proper type annotation.

---

## 3. `backend/core/voice/tts/edge_tts_provider.py`

### 3.1 🔴 ffmpeg subprocess leak potential
**File:** `edge_tts_provider.py:107-112`  
**Issue:** `asyncio.create_subprocess_exec` creates a subprocess. If `proc.wait()` is cancelled (e.g., task cancellation), the subprocess is orphaned. The temp files are cleaned up in `finally`, but the ffmpeg process may remain running.  
**Fix:** Wrap in `try/finally` with `proc.kill()` on cancellation.

### 3.2 🟠 `_ensure_valid_voice` is called on every `synthesize()`
**File:** `edge_tts_provider.py:72`  
**Issue:** `_ensure_valid_voice()` makes an HTTP API call to fetch all Edge TTS voices on first call, but this is still called on every `synthesize()` even when cached (it just does a cheap `not in` check). The issue is minor, but the `not in` check against a cached set is fine. The real problem: if `list_voices()` fails, `_valid_voices` is set to `set()`, then every voice is considered invalid and falls back to `FALLBACK_VOICE`.  
**Fix:** Only fallback if the voice was explicitly validated as missing. Consider using a TTL cache.

### 3.3 🟡 Empty text returns `[], 16000` but SR_MAP says `edge-tts: 16000`
**File:** `edge_tts_provider.py:66`  
**Issue:** Minor — consistency. The empty return uses `16000` hardcoded.  
**Fix:** Use `self._SR_MAP["edge-tts"]` or define a class constant.

### 3.4 🟡 `# no audio chunks received` returns empty with hardcoded 16000
**File:** `edge_tts_provider.py:101`  
**Issue:** Hardcoded sample rate return when no chunks. Should use `self._SR_MAP` or a constant.

### 3.5 🟡 Temporary file descriptors created before early returns
**File:** `edge_tts_provider.py:74-77`  
**Issue:** `mkstemp` creates files and file descriptors at top of `synthesize`. If `_ensure_valid_voice()` raises (it doesn't, but still pattern-smell), or if an early return happens before the try block, temp files leak.  
**Fix:** Move temp file creation inside the try block or use `tempfile.NamedTemporaryFile`.

---

## 4. `backend/core/voice/tts/elevenlabs_provider.py`

### 4.1 🔴 `aiter_lines()` and `aiter_bytes()` are both called — double iteration error
**File:** `elevenlabs_provider.py:61-79`  
**Issue:** The code iterates with `response.aiter_lines()` at line 61-73 (looking for JSON alignment data), and then iterates with `response.aiter_bytes()` at line 77-78 to collect MP3 chunks. **Once `aiter_lines()` exhausts the async iterable, `aiter_bytes()` will yield nothing** because the response body has already been consumed. The `mp3_data` at lines 76-79 will be empty.  
**Fix:** Collect raw bytes first, then parse lines from the bytes if needed, or use a streaming approach that buffers. For example:
```python
raw_bytes = await response.aread()
# parse alignment from raw_bytes, then decode
```

### 4.2 🟠 `mp3_chunks` is collected but `mp3_data = b''.join(mp3_chunks)` runs after `aiter_bytes`
**File:** `elevenlabs_provider.py:76-79`  
**Issue:** Even if `aiter_bytes` worked, `mp3_chunks` would be empty after `aiter_lines` consumption. `mp3_data` will always be `b''`.  
**Fix:** See 4.1.

### 4.3 🟠 `_decode_mp3` uses blocking subprocess in async context
**File:** `elevenlabs_provider.py:151-153`  
**Issue:** `subprocess.run(... timeout=30)` is a synchronous blocking call. It blocks the event loop for the entire ffmpeg conversion.  
**Fix:** Use `asyncio.create_subprocess_exec` with `asyncio.wait_for`.

### 4.4 🟡 `close()` method may not be called — no cleanup contract
**File:** `elevenlabs_provider.py:172-173`  
**Issue:** There is no `__aenter__`/`__aexit__` to ensure `close()` is called on the provider. The `AsyncClient` may leak connections. Same for all httpx-based providers.  
**Fix:** Add async context manager protocol or ensure cleanup at router level.

### 4.5 🟡 `_alignment_to_viseme_schedule` — `char_starts/char_ends` index safety
**File:** `elevenlabs_provider.py:112-113`  
**Issue:** `chars` may have more elements than `char_starts`/`char_ends`. The code guards with `if i < len(char_starts)` which is good, but `char_ends` is not similarly guarded.  
**Fix:** Add guard for `char_ends` too.

### 4.6 🟡 `_decode_mp3` — returns `(44100, zeros)` on exception, ignoring actual format
**File:** `elevenlabs_provider.py:170`  
**Issue:** The fallback assumes 44100 Hz. The API requests `mp3_44100_128` but should verify or make configurable.

---

## 5. `backend/core/voice/tts/openai_tts_provider.py`

### 5.1 🟡 `synthesize` — does not check `response is None` before accessing `.status_code`
**File:** `openai_tts_provider.py:43`  
**Issue:** `retry_http` can return `None` (line 67 in base.py). The code checks `response is not None` at line 43, which is correct. But at line 46, `response is not None` is checked again (redundant but safe).  
**Fix:** No bug, but consider simplifying to a single check.

### 5.2 🟡 No viseme support — returns `None` for visemes
**File:** `openai_tts_provider.py:45`  
**Issue:** OpenAI TTS doesn't support visemes, but returns `None`. The caller in `router.py` handles this, but the type hint says `list | None` which is correct.  
**Fix:** (informational) Consider documenting that viseme support is provider-dependent.

### 5.3 🟡 `close()` exists but router doesn't call it on shutdown
**File:** `openai_tts_provider.py:52-53`  
**Issue:** Same as 4.4 — `close()` exists but no guarantee of being called.

---

## 6. `backend/core/voice/tts/openvoice_provider.py`

### 6.1 🟠 `_get_engine` imports from `backend.core.voice.openvoice_engine` which may not exist
**File:** `openvoice_provider.py:19`  
**Issue:** The import is inside the method, so it will fail at runtime with `ImportError` if the module doesn't exist. The `get_openvoice_loaded()` method at line 23-26 calls `_get_engine()`, which calls `_ensure_loaded()` on the engine. If the engine module is missing, the error message will be opaque.  
**Fix:** Wrap import in try/except with a clear error message.

### 6.2 🟡 `synthesize` returns `(audio, None)` — inconsistent with base class signature
**File:** `openvoice_provider.py:45`  
**Issue:** Base class says `-> tuple[np.ndarray, list | None, int]` but OpenVoice returns `(audio, None)` — only 2 elements. The caller in `router.py` (line 222-225) handles this with `if isinstance(result, tuple) and len(result) >= 3` check, but it's fragile.  
**Fix:** Always return 3-tuple `(audio, None, 22050)`.

### 6.3 🟡 `_get_engine` creates a new engine every call if no cached
**File:** `openvoice_provider.py:17-21`  
**Issue:** The engine is cached, but if `OpenVoiceEngine` initialization is expensive, this is fine. The method is not thread-safe though — two concurrent calls could create two engines.  
**Fix:** Use a lock or `__init__`-time creation.

### 6.4 🟡 `loop.run_in_executor` without explicit executor
**File:** `openvoice_provider.py:38`  
**Issue:** Uses default executor which can be shared with other CPU-bound tasks, potentially blocking other operations.  
**Fix:** Use a dedicated ThreadPoolExecutor.

---

## 7. `backend/core/voice/tts/speecht5_provider.py`

### 7.1 🔴 `_ensure_model` downloads ~2 GB of model data synchronously on first async call
**File:** `speecht5_provider.py:21-41`  
**Issue:** `_ensure_model()` is called from `_synthesize_sync()` which runs in an executor. However, the `transformers` and `datasets` loading (lines 28-34) downloads model files with no progress indicator, timeout, or cancellation. If the network fails, the exception at line 39-41 re-raises and is caught at line 50-51 in `synthesize`. However, the download is not interruptible and holds the executor thread for potentially minutes.  
**Fix:** Add download timeout, cache check, and progress logging. Consider using `hf_hub_download` with `resume_download=True`.

### 7.2 🟡 `_synthesize_sync` imports torch twice
**File:** `speecht5_provider.py:26,45`  
**Issue:** `torch` is imported inside both `_ensure_model` (indirectly via `transformers`) and `_synthesize_sync` (line 56).  
**Fix:** Import at top of file.

### 7.3 🟡 No viseme support, returns `None` for visemes
**File:** `speecht5_provider.py:52`  
**Issue:** Returns `(audio, None, 16000)`. Visemes are not supported, which is fine.

### 7.4 🟡 No model unloading/cleanup
**File:** `speecht5_provider.py:11`  
**Issue:** The loaded model (~2 GB) is never unloaded. No `__del__` or context manager.  
**Fix:** Add cleanup mechanism.

---

## 8. `backend/core/voice/tts/alltalk_provider.py`

### 8.1 🟠 Exception handler fall-through misses return for HTTPStatusError
**File:** `alltalk_provider.py:76-77`  
**Issue:** The `except httpx.HTTPStatusError` at line 76 logs the error but does **not return** a value. Execution falls through to the end of the function, returning `None` implicitly. The caller expects a tuple. This leads to `TypeError: cannot unpack non-iterable NoneType object` at `router.py:222`.  
**Fix:** Add `return np.zeros(0, dtype=np.float32), None, 24000` inside the handler.

### 8.2 🟡 `retry_http` used without checking `response is None`
**File:** `alltalk_provider.py:56`  
**Issue:** The code checks `response is None or response.status_code != 200`, which is correct.

---

## 9. `backend/core/voice/tts/piper_provider.py`

### 9.1 🟠 Same exception handler fall-through as AllTalk
**File:** `piper_provider.py:33-34`  
**Issue:** `except httpx.HTTPStatusError` logs but does not return, causing implicit `None` return.  
**Fix:** Add `return np.zeros(0, dtype=np.float32), None, 22050`.

### 9.2 🟡 `urllib.parse.quote` imported inside async method
**File:** `piper_provider.py:23`  
**Issue:** Import inside method body, but this is a standard library import so performance impact is negligible. Style note only.

---

## 10. `backend/core/voice/tts/coqui_local_provider.py`

### 10.1 🟠 Same exception handler fall-through as Piper
**File:** `coqui_local_provider.py:37-38`  
**Issue:** `except httpx.HTTPStatusError` logs but does not return.  
**Fix:** Add `return np.zeros(0, dtype=np.float32), None, 24000`.

### 10.2 🟡 `text` passed as header, not query param or body
**File:** `coqui_local_provider.py:26`  
**Issue:** The Coqui TTS API expects `text` as a query parameter or form body, but it's sent as a header (`headers={"text": text}`). This may not work with all Coqui server implementations.  
**Fix:** Verify API contract and use proper parameter location.

---

## 11. `backend/core/voice/tts/kokoro_provider.py`

### 11.1 🟠 Same exception handler fall-through as Coqui
**File:** `kokoro_provider.py:34-36`  
**Issue:** `except httpx.HTTPStatusError` logs but does not return.  
**Fix:** Add `return np.zeros(0, dtype=np.float32), None, 24000`.

---

## 12. `backend/core/voice/tts/azure_provider.py`

### 12.1 🟠 `close()` is a no-op but `AsyncClient` isn't used
**File:** `azure_provider.py:120-121`  
**Issue:** `async def close(self): pass` — Azure doesn't use httpx, so no resource to close. But the method signature is async even though it does nothing.  
**Fix:** Either remove or document that Azure SDK handles its own cleanup.

### 12.2 🟠 `synthesize` imports `speechsdk` inside try/except for ImportError but also inside `_synthesize_sync`
**File:** `azure_provider.py:38-41, 54`  
**Issue:** `speechsdk` is imported twice — once in `synthesize` to check availability (lines 38-41), and again in `_synthesize_sync` (line 54).  
**Fix:** Import once at module level with availability flag.

### 12.3 🟡 `speak_ssml_async().get()` blocks the event loop
**File:** `azure_provider.py:99`  
**Issue:** `synthesizer.speak_ssml_async(ssml).get()` is a synchronous blocking call inside `_synthesize_sync`, which runs in an executor. But `_synthesize_sync` is called via `loop.run_in_executor()`, so it's not blocking the event loop. This is actually correct.  
**Fix:** None needed.

### 12.4 🟡 Viseme timing rounding may cause negative durations
**File:** `azure_provider.py:110-114`  
**Issue:** `max(dur, 0.01)` guards against negative durations, but `gap` could be negative. The viseme schedule uses `round(dur, 4)`, and if floats cause slight negative values, `max()` clamps to `0.01`.  
**Fix:** Verify that `viseme_schedule[i+1]['start']` can never be less than `viseme_schedule[i]['start']`. Consider sorting.

### 12.5 🟡 Azures SDK synthesizer not disposed
**File:** `azure_provider.py:83`  
**Issue:** The `speechsdk.SpeechSynthesizer` object (line 83) is not disposed after use. It holds native resources.  
**Fix:** Use context manager or `with` block if available, or call `.close()` in a finally block.

---

## 13. `backend/core/voice/tts/dashscope_provider.py`

### 13.1 🟡 `numpy.frombuffer` assumes raw PCM from API
**File:** `dashscope_provider.py:46`  
**Issue:** The response content is directly interpreted as int16 PCM. If DashScope returns WAV or other format, the audio will be garbled.  
**Fix:** Verify format or use `decode_wav` if WAV. Add format handling.

### 13.2 🟡 Same close() pattern — no cleanup guarantee
**File:** `dashscope_provider.py:58-59`  
**Issue:** Same as 4.4.

---

## 14. `backend/core/voice/tts/volcengine_provider.py`

### 14.1 🟠 `base64` imported twice
**File:** `volcengine_provider.py:6, 69`  
**Issue:** `import base64` is at the top of the file (line 6) and again inside the method (line 69).  
**Fix:** Remove the inner import.

### 14.2 🟡 `import hashlib`, `import hmac` unused
**File:** `volcengine_provider.py:4-5`  
**Issue:** `hashlib` and `hmac` are imported but never used. Probably left over from planned auth signing.  
**Fix:** Remove unused imports.

### 14.3 🟡 API response code check uses magic number `3000`
**File:** `volcengine_provider.py:65`  
**Issue:** `result.get("code") != 3000` checks for API-level success. 3000 may be specific to Volcengine TTS. Hard to understand without documentation.  
**Fix:** Add a comment explaining the 3000 magic number.

### 14.4 🟡 Same close() pattern — no cleanup guarantee
**File:** `volcengine_provider.py:83-84`  
**Issue:** Same as 4.4.

---

## 15. `backend/core/voice/tts/deepgram_provider.py`

### 15.1 🟡 Streaming API used but `aread()` reads full body anyway
**File:** `deepgram_provider.py:38, 43`  
**Issue:** Uses `async with self._client.stream(...)` but immediately calls `resp.aread()` to consume all data. This defeats streaming. The response is also consumed in two ways — the `aiter_lines` lookalike is not used, but `aread()` reads the full response body.  
**Fix:** Use a regular POST with `resp.content` or use streaming if needed.

### 15.2 🟡 No viseme support
**File:** `deepgram_provider.py:46`  
**Issue:** Returns `None` for visemes.

---

## 16. `backend/core/voice/tts/mlx_provider.py`

### 16.1 🟠 `hasattr(audio, "numpy")` — fragile type check
**File:** `mlx_provider.py:53-54`  
**Issue:** Checking `hasattr(audio, "numpy")` is fragile. The `audio` object could have a `.numpy` method that returns something other than a numpy array.  
**Fix:** Use `isinstance(audio, (np.ndarray, mx.array))` if mx is available, or try `np.asarray(audio)`.

### 16.2 🟡 `_ensure_model` raises exceptions that `synthesize` catches and logs but returns empty
**File:** `mlx_provider.py:41-45`  
**Issue:** If `_ensure_model` raises (e.g., not on macOS), the error is logged but synthesis continues to return zeros. This is correct behavior for graceful degradation, but the user may not understand why audio is silent.  
**Fix:** Consider raising a more descriptive error that the frontend can display.

### 16.3 🟡 `_ensure_model` raises `ImportError` with hardcoded package name
**File:** `mlx_provider.py:29-30`  
**Issue:** The error message says "Install with: pip install mlx-audio" but the actual import is from `mlx_audio.tts`.  
**Fix:** Verify the correct package name.

---

## 17. `backend/core/voice/tts/rvc_provider.py`

### 17.1 🟠 `source_audio` unpacking assumes specific tuple format
**File:** `rvc_provider.py:41-44`  
**Issue:** The code assumes `source_result` is a 3-tuple or 2-tuple. If the TTS provider returns a different format, `source_sr` defaults to 24000 silently, but `_` may unpack visemes into the wrong variable.  
**Fix:** More robust unpacking similar to router.py.

### 17.2 🟡 WAV encoding in `wav_bytes` uses `source_audio * 32767.0` but decode uses `/ 32767.0`
**File:** `rvc_provider.py:59`  
**Issue:** RVC encodes using `* 32767.0` on line 59, then decodes using `/ 32767.0` on line 86. This is consistent within the file but many other providers use `/ 32768.0` (e.g., edge-tts: line 119 uses `/ 32768.0`). The mismatch means a 1 LSB level shift across pipeline stages if audio passes through multiple encode/decode cycles.  
**Fix:** Standardize to `/ 32768.0` for int16 normalization (standard PCM range).

### 17.3 🟡 `set_tts_provider` called from router but RVC's `synthesize` is then called singularly
**File:** `rvc_provider.py:40`  
**Issue:** If `_tts_provider.synthesize()` returns an async generator or raises, RVC may leave the caller with no audio. The error handling at line 47 checks for empty audio, which is good.

---

## 18. `backend/core/voice/tts/word_to_viseme.py`

### 18.1 🟡 `word_to_visemes` — regex strips non-alpha chars, losing digits/symbols
**File:** `word_to_viseme.py:58`  
**Issue:** Words like "123" or "C++" become empty string after stripping non-alpha chars, resulting in `["sil"]`. This loses timing information.  
**Fix:** Map digits and common symbols to visemes (e.g., digits to "aa", symbols to "sil").

### 18.2 🟡 `viseme_schedule_from_words` — gap-filling logic may produce overlapping durations
**File:** `word_to_viseme.py:138-148`  
**Issue:** When inserting a "sil" gap, the code uses `filled[-1]["start"] + filled[-1]["duration"]` which could theoretically exceed `entry["start"]` if floats misbehave. The `gap` would be negative, and the inserted duration would be negative or zero.  
**Fix:** Check `gap > 0` before inserting, not `gap > 0.03`.

### 18.3 🟡 Syllable count viseme inflation fills with vowels from single character
**File:** `word_to_viseme.py:98-102`  
**Issue:** The syllable padding uses `next((c for c in w if c in "aeiouy"), "a")` on the original stripped word. If `w` is empty (all non-alpha stripped), this uses "a" which maps to "aa". This is fine but may produce incorrect viseme counts for short words.  
**Fix:** Add a check for `w == ""`.

---

## 19. `backend/voice/pipeline.py`

### 19.1 🔴 `start()` creates a new `ThreadPoolExecutor` every call that is never shut down
**File:** `pipeline.py:288-289`  
**Issue:** `start()` creates a `ThreadPoolExecutor` via `concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice")` and submits `listen_loop` to it. This executor is **never shut down** — there's no reference to it stored on `self`. The executor will leak threads every time `start()` is called.  
**Fix:** Store the executor as `self._voice_executor` and shut it down in `stop()`.

### 19.2 🔴 `listen_loop` captures `self._main_loop` which may be stale
**File:** `pipeline.py:403-406`  
**Issue:** `self._main_loop` is set to the running event loop at the start of `listen_loop`. But this loop reference is never cleared until `finally` at line 553. If `listen_loop` is restarted, the old loop reference persists. Meanwhile, other code may use this reference incorrectly.  
**Fix:** Clear `_main_loop` when the loop is no longer valid (e.g., after cancellation).

### 19.3 🟠 `_on_stt_done` fires `agent_callback(result)` which may be blocking
**File:** `pipeline.py:344-345`  
**Issue:** `_on_stt_done` is called from the ThreadPoolExecutor's worker thread (via `add_done_callback`). It calls `self.agent_callback(result)` which may be a slow synchronous function. If the callback blocks, it holds the STT executor thread.  
**Fix:** Document that agent_callback must be non-blocking, or dispatch to a thread.

### 19.4 🟠 `stop_listening` shuts down executor and creates a new one
**File:** `pipeline.py:614-618`  
**Issue:** Every `stop_listening()` creates a new ThreadPoolExecutor with `wait=False`, meaning running tasks are abandoned (not waited for). If an STT task is in-flight, it may be mid-transcription. The `shutdown(wait=False)` won't cancel running futures.  
**Fix:** Cancel pending futures before shutdown.

### 19.5 🟡 `_submit_stt_with_timeout` creates a timer that may fire after cleanup
**File:** `pipeline.py:379`  
**Issue:** The `threading.Timer` is daemon=True, so it won't prevent process exit. But if `stop_listening()` is called shortly after `_submit_stt_with_timeout`, the timer may still fire after the executor is shut down, trying to cancel an already-cancelled future. The `# noqa` style comment at line 382 catches the error, but the `transition_sync` call on a potentially stopped state machine is unchecked.  
**Fix:** Cancel the timer in `stop_listening()`.

### 19.6 🟡 `listen_loop` has a hardcoded max_recording_bytes of 960,000
**File:** `pipeline.py:421`  
**Issue:** `max_recording_bytes = 16000 * 2 * 30` calculates as 960,000 bytes = 30 seconds. This is hardcoded and not configurable.  
**Fix:** Add to settings.

### 19.7 🟡 `is_speaking` check in `interrupt()` is not used — transitions to INTERRUPTED regardless of state
**File:** `pipeline.py:592`  
**Issue:** `transition_sync(VoiceState.INTERRUPTED)` is called regardless of current state, and the `VoiceStateError` is caught. If the state machine is in IDLE or PROCESSING, this will raise (and be swallowed). This is intentional per the "try and ignore" pattern, but it's unusual.  
**Fix:** Check state before calling transition.

### 19.8 🟡 `sm.reset_sync()` called in `stop_listening()` after executor shutdown
**File:** `pipeline.py:619`  
**Issue:** `reset_sync()` calls `self._bus.emit(...)` which may schedule async tasks. If the event loop is not running (e.g., during shutdown), this could fail.  
**Fix:** Wrap in try/except or check event loop status.

### 19.9 🟡 `reconfigure` sets `self._vad = None` forcing re-creation
**File:** `pipeline.py:317`  
**Issue:** Setting `_vad = None` means the VAD is lazily re-created on next `listen_loop`. But `reconfigure` can be called while the pipeline is running, leaving VAD in an inconsistent state.  
**Fix:** Only force re-creation if settings actually changed, and do it safely (e.g., after stopping).

### 19.10 🟡 `_on_stt_done` — `voice.stt_timeout` settings access
**File:** `pipeline.py:352-353, 358-359`  
**Issue:** Both the empty-result and error paths call `transition_sync(VoiceState.IDLE)` but catch `VoiceStateError`. If the state machine is already in IDLE, the transition to IDLE is a no-op via forced reset. This is correct.

---

## 20. `backend/voice/stt/router.py`

### 20.1 🟡 `transcribe` is synchronous but called from threads
**File:** `stt/router.py:57`  
**Issue:** The `transcribe` method is synchronous and blocking. The caller in `pipeline.py:364` submits it to a ThreadPoolExecutor. This is correct, but the method signature doesn't indicate it's blocking.  
**Fix:** Add docstring saying "This is a synchronous, potentially long-running call."

### 20.2 🟡 `_ensure` creates new provider without any configuration
**File:** `stt/router.py:39`  
**Issue:** `cls()` is called with no args. Providers like `OpenAIWhisperProvider` accept `api_key` and `model` in `__init__`, but `_ensure` doesn't pass them. They must be set via `configure_*` later. If `transcribe` is called before `configure_*`, it will use defaults (empty API key).  
**Fix:** Either raise if not configured, or have `__init__` read from environment.

### 20.3 🟡 `transcribe` returns `str`, but type hint on `audio_np` is not enforced
**File:** `stt/router.py:57`  
**Issue:** `audio_np` parameter has no type hint.  
**Fix:** Add `audio_np: np.ndarray`.

---

## 21. `backend/voice/stt/base.py`

### 21.1 🟡 `STTProvider.listen_loop` and `stop_listening` are abstract but unused
**File:** `stt/base.py:11, 15`  
**Issue:** `listen_loop()` and `stop_listening()` are defined but never called — the pipeline's `listen_loop` is the actual audio capture, and STT providers only implement `transcribe()`. These base class methods are dead code.  
**Fix:** Remove or mark as deprecated.

---

## 22. `backend/voice/stt/browser_provider.py`

### 22.1 🟡 `transcribe` always returns empty string
**File:** `browser_provider.py:10-11`  
**Issue:** This provider does nothing — it returns `""` always. The docstring says transcription is handled client-side via Web Speech API. This is intentional but could cause confusion.  
**Fix:** Add a more explicit docstring explaining the architecture.

---

## 23. `backend/voice/stt/faster_whisper_provider.py`

### 23.1 🟠 `_ensure_model` loads model synchronously on first `transcribe()`
**File:** `faster_whisper_provider.py:18-22`  
**Issue:** Loading a Whisper model can take several seconds and download ~1-3 GB. This blocks the STT executor thread and may cause timeout in the watchdog.  
**Fix:** Load asynchronously or preload during startup.

### 23.2 🟡 No error handling for `_model.transcribe()`
**File:** `faster_whisper_provider.py:26`  
**Issue:** `self._model.transcribe(audio_np, beam_size=5)` can raise various errors (GPU OOM, corrupt audio, etc.). No try/except.  
**Fix:** Wrap in try/except and return empty string.

### 23.3 🟡 Model never unloaded
**File:** `faster_whisper_provider.py:15`  
**Issue:** The Whisper model is kept in memory forever. No cleanup mechanism.  
**Fix:** Add `unload()` method or context manager.

---

## 24. `backend/voice/stt/openai_whisper_provider.py`

### 24.1 🟠 `httpx.post` is synchronous blocking call
**File:** `openai_whisper_provider.py:32-38`  
**Issue:** `transcribe()` calls `httpx.post(...)` synchronously. When called from the ThreadPoolExecutor, this blocks a thread. This is acceptable since it runs in a thread, but `httpx` also supports async which would be more efficient.  
**Fix:** Consider using `httpx.AsyncClient` if the caller is refactored to be async.

### 24.2 🟡 No retry logic on transient API errors
**File:** `openai_whisper_provider.py:31-46`  
**Issue:** If the API returns a 5xx error, the code logs and returns empty string immediately. No retry.  
**Fix:** Add simple retry with backoff.

---

## 25. `backend/voice/stt/groq_whisper_provider.py`

### 25.1 🟡 Same issues as OpenAIWhisperProvider — no retry, synchronous httpx
**File:** `groq_whisper_provider.py:32-38`  
**Issue:** Same as 24.1 and 24.2.

---

## 26. `backend/voice/stt/whispercpp_provider.py`

### 26.1 🟡 Same issues — no retry, synchronous httpx
**File:** `whispercpp_provider.py:26-29`  
**Issue:** Same as 24.1 and 24.2.

### 26.2 🟡 JSON response parsing assumes `"text"` key exists
**File:** `whispercpp_provider.py:32`  
**Issue:** `resp.json().get("text", "")` — if the API returns a different format, `.get("text", "")` returns "". This is safe but may mask errors.  
**Fix:** Log if response format is unexpected.

---

## 27. `backend/voice/stt/deepgram_provider.py`

### 27.1 🟡 Same issues — no retry, synchronous httpx
**File:** `deepgram_provider.py:37`  
**Issue:** Same as 24.1 and 24.2.

### 27.2 🟡 Safe navigation chain is verbose but correct
**File:** `deepgram_provider.py:40`  
**Issue:** `result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "")` — this is correct but fragile if the API response structure changes.  
**Fix:** Consider using a JSONPath or typed response model.

---

## 28. `backend/voice/stt/utils.py`

### 28.1 🟡 `numpy_to_wav` assumes float32 input range [-1, 1]
**File:** `stt/utils.py:7`  
**Issue:** `pcm = (audio_np * 32767).astype("int16")` assumes float32 range [-1, 1]. If the input is already int16 or has different range, the output will be clipped or silent.  
**Fix:** Check dtype and scale appropriately. The TTS-side `numpy_to_wav_bytes` in `backend.core.utils.wav` may differ.

### 28.2 🟡 WAV header uses hardcoded 16-bit mono format
**File:** `stt/utils.py:10-13`  
**Issue:** The WAV header assumes 16-bit, 1 channel, at `sr` Hz. The `sr` parameter defaults to 16000. If the audio is multichannel or different bit depth, the header is wrong.  
**Fix:** Make parameters configurable.

---

## 29. `backend/voice/vad.py`

### 29.1 🟠 `SileroVAD._ensure_model` downloads model on every first call — no cache
**File:** `vad.py:18-23`  
**Issue:** `torch.hub.load('snakers4/silero-vad', 'silero_vad')` downloads the model each time if not cached. `force_reload=False` should use cache, but `torch.hub` cache can be brittle and the model path may change.  
**Fix:** Pre-download or use a local path with fallback.

### 29.2 🟠 `SileroVAD.process` re-imports torch every call
**File:** `vad.py:31`  
**Issue:** `import torch` inside the method (line 31) even though it's already imported in `_ensure_model`.  
**Fix:** Import at module level.

### 29.3 🟠 `VAD.__init__` creates SileroVAD unconditionally
**File:** `vad.py:44-45`  
**Issue:** `SileroVAD()` is created even if the import fails later. The constructor doesn't actually load the model (that's lazy in `_ensure_model`), so this is fine. But `except Exception` at line 46 catches any exception, including SileroVAD init failures, and falls back to webrtcvad. This is overly broad.  
**Fix:** Narrow the exception scope.

### 29.4 🟡 `VAD.process` — `self._silero = None` after Silero failure loses the reference permanently
**File:** `vad.py:57`  
**Issue:** If SileroVAD fails once, it falls back to WebRTC permanently for the instance lifetime, even if SileroVAD was a transient error (e.g., CUDA OOM recovered).  
**Fix:** Add a retry count or mark as permanently failed.

### 29.5 🟡 `VAD.process` falls back to `False` if both fail
**File:** `vad.py:63`  
**Issue:** If both Silero and WebRTC fail, returns `False` (no speech). This is a safe default but could mean speech is missed silently.  
**Fix:** Log a warning when both VAD methods fail.

---

## 30. `backend/voice/wakeword/router.py`

### 30.1 🟡 `start()` receives `on_detected` as argument but also accesses `self._callback`
**File:** `wakeword/router.py:29-36`  
**Issue:** The `on_detected` parameter shadows the `self._callback` set by `set_callback()`. The fallback at line 33 uses `getattr(self, '_callback', None)` which is a workaround for `self._callback` not being set. This is fragile.  
**Fix:** Use a single source of truth for the callback.

### 30.2 🟡 `_create_provider` accesses `on_detected or getattr(self, '_callback', None)` 
**File:** `wakeword/router.py:33`  
**Issue:** `getattr(self, '_callback', None)` is used because `_callback` might not be set if `set_callback` was never called. This is fragile.  
**Fix:** Initialize `self._callback = None` in `__init__`.

### 30.3 🟡 `is_listening` property accesses `self._provider.is_running` without checking `self._provider is not None`
**File:** `wakeword/router.py:55`  
**Issue:** The property checks `self._provider is not None and ...` so this is safe.

---

## 31. `backend/voice/wakeword/base.py`

### 31.1 🔵 `feed_audio` is abstract but the router never uses it
**File:** `wakeword/base.py:18-19`  
**Issue:** `feed_audio` is defined as abstract but the `WakeWordRouter` never calls it. It's used by `OpenWakeWordProvider._listen_loop` internally. The abstract method exists for external audio feeding (e.g., from a custom mic source).  
**Fix:** This is acceptable design, but document it.

---

## 32. `backend/voice/wakeword/openwakeword_provider.py`

### 32.1 🟠 `_listen_loop` re-reads from mic even if `feed_audio` is called externally
**File:** `openwakeword_provider.py:83-97`  
**Issue:** The provider runs its own mic loop via `sounddevice.RawInputStream`. If someone calls `feed_audio()` manually, it processes audio, but the mic loop also processes audio. This dual-path could cause double detection.  
**Fix:** Document that the provider either runs its own mic or accepts external audio, not both.

### 32.2 🟡 `feed_audio` access `self._model.prediction_data` without checking format
**File:** `openwakeword_provider.py:75-76`  
**Issue:** The `openwakeword` library's `prediction_data` format may vary. The code iterates over `scores` and checks the last element `> 0.5`. If `scores` is empty, `scores[-1]` raises `IndexError`.  
**Fix:** Check `if scores and scores[-1] > 0.5`.

### 32.3 🟡 No audio device selection
**File:** `openwakeword_provider.py:85-89`  
**Issue:** `sd.RawInputStream()` uses the default input device. There's no way to specify a non-default device for wake word detection.  
**Fix:** Add device selection parameter.

### 32.4 🟡 `_listen_loop` swallows exceptions silently for non-mic errors
**File:** `openwakeword_provider.py:95-96`  
**Issue:** The broad except at line 95 catches all exceptions and logs, setting `_running = False`. This is acceptable for a daemon thread, but the caller (`start()`) won't know the loop failed.  
**Fix:** Add a callback or event to notify the caller.

---

## 33. `backend/api/ws/tts_service.py`

### 33.1 🔴 `_do_generate` accesses `settings()` multiple times — stale data risk
**File:** `tts_service.py:165, 175, 192-195, 232`  
**Issue:** `settings()` is called multiple times throughout the function. If settings change mid-generation (e.g., user changes engine or API key), different parts of the same generation may use different settings. For example, line 175 checks `char.get("voice_ref")` and line 192 calls `tts().synthesize()` — if `tts()` was reconfigured between these calls, the ref_audio might be from the old configuration.  
**Fix:** Capture settings at the start of the method.

### 33.2 🟠 `synthesize_sentence` (standalone function) duplicates logic from OrderedTTSScheduler._do_generate
**File:** `tts_service.py:270-356`  
**Issue:** The standalone `synthesize_sentence` function and `OrderedTTSScheduler._do_generate` have nearly identical logic for translation, ref_audio lookup, synthesis, and WebSocket delivery. The only difference is that `synthesize_sentence` sends directly while `OrderedTTSScheduler` buffers for ordering. This is a maintenance burden.  
**Fix:** Refactor common logic into a shared helper.

### 33.3 🟠 `synthesize_sentence` — `orig_text` variable is assigned but never used
**File:** `tts_service.py:289, 295`  
**Issue:** `orig_text = sentence_text` at line 289, then `orig_text = sentence_text` again at line 295 (after translation). Both assignments are dead code — `orig_text` is never read.  
**Fix:** Remove dead variable.

### 33.4 🟡 `OrderedTTSScheduler.submit` — placeholder `None` in buffer before task is done
**File:** `tts_service.py:72`  
**Issue:** `self._buffer[idx] = None` sets a placeholder for ordering. If the task fails (exception in `_generate_and_deliver`), the buffer at `idx` is set to `None` (line 138), and `_deliver_ready` will skip it (line 257 `if msg is None: continue`). This is correct — the gap is left unfilled, and the ordered stream may have a "hole" (missing sentence). The frontend should handle this gracefully.  
**Fix:** (informational) Consider adding a flag in the delivered message to indicate a skipped sentence.

### 33.5 🟡 `_deliver_ready` checks `stream_ref() != stream_id` after popping but before sending
**File:** `tts_service.py:254`  
**Issue:** If the stream becomes stale between pop and send, the message is skipped. The popped item is already removed from the buffer at line 250. On a stale stream, messages for future indices that haven't been delivered yet are lost (they can't be replayed).  
**Fix:** Re-insert buffer entry if stream is stale.

### 33.6 🟡 `tts_error` message sent to WebSocket includes raw error message
**File:** `tts_service.py:354`  
**Issue:** `f"TTS failed: {tts_err}"` sends the raw exception string to the frontend. If the error contains sensitive information (e.g., API key in a connection error), it leaks to the client.  
**Fix:** Use a generic error message for the client and log the detailed error server-side.

### 33.7 🟡 `synthesize_now` — `orig_text` concept missing
**File:** `tts_service.py:359-411`  
**Issue:** This function is used for the "speak button" and duplicates more logic from the other synthesis functions. No `orig_text` is used, and translation is not performed.  
**Fix:** Reuse shared helper.

### 33.8 🟡 `cancel_all` is an alias for `cancel`
**File:** `tts_service.py:99-104`  
**Issue:** Minor naming consistency issue. `cancel_all` exists but `cancel` also does the same thing.  
**Fix:** Remove `cancel_all` or have `cancel` call `cancel_all`.

### 33.9 🟡 `stream_ref` parameter is a callable — unclear ownership/timing
**File:** `tts_service.py:63, 120, 146, 155, 254`  
**Issue:** `stream_ref` is a callable that returns the current stream ID. This is passed down from the WebSocket handler. If the handler closes or the connection drops, `stream_ref()` may raise or return garbage.  
**Fix:** Document the contract clearly.

---

## 34. Cross-Cutting Issues

### 34.1 🔴 No context manager / cleanup protocol for TTS providers
**Files:** All `*_provider.py` files  
**Issue:** Many providers have `async def close()` but there's no guarantee it's called. The `TTSRouter` doesn't implement `__aenter__`/`__aexit__` or have a `close()` method that closes all providers. httpx clients, subprocess resources, and temp files may leak.  
**Fix:** Add `async def close()` to `TTSRouter` that closes all cached providers. Ensure it's called at application shutdown.

### 34.2 🟠 Mixed sync/async patterns in STT providers
**Files:** `backend/voice/stt/*_provider.py`  
**Issue:** All STT providers have synchronous `transcribe()` methods that make HTTP calls or run ML models. They're called from a ThreadPoolExecutor, which is correct, but the watchdog timer in `pipeline.py` can cancel the future even though the actual computation keeps running in the thread pool, wasting resources.  
**Fix:** Use asyncio with `asyncio.to_thread()` and proper cancellation via `asyncio.wait_for()`.

### 34.3 🟡 `retry_http` imported in many files but not used consistently
**Files:** Multiple TTS providers  
**Issue:** Some providers use `retry_http` (OpenAI, AllTalk, Piper, Coqui, Kokoro, DashScope, Volcengine, RVC), while others implement their own error handling (ElevenLabs, Deepgram TTS), and STT providers don't use it at all.  
**Fix:** Standardize retry strategy across all HTTP-based providers.

### 34.4 🟡 `numpy` normalization inconsistency (`32767` vs `32768`)
**Files:** Multiple files  
**Issue:** Different providers use different denominators:
- `edge_tts_provider.py:119` uses `/ 32768.0` 
- `elevenlabs_provider.py:158` uses `/ 32768.0`
- `azure_provider.py:107` uses `/ 32767.0`
- `dashscope_provider.py:46` uses `/ 32767.0`
- `volcengine_provider.py:71` uses `/ 32767.0`
- `deepgram_provider.py:45` uses `/ 32767.0`
- `rvc_provider.py:59` uses `* 32767.0` and line 86 uses `/ 32767.0`
- `stt/utils.py:7` uses `* 32767`
- `pipeline.py:463-464` uses `/ 32768.0`

The standard for int16 PCM is 32768 (symmetric range [-32768, 32767]). Using 32767 clips the maximum positive value slightly, reducing amplitude by ~0.003%. This is minor but inconsistent.  
**Fix:** Standardize all to `/ 32768.0` for both encode and decode.

### 34.5 🟡 Empty return values hardcoded sample rates
**Files:** Multiple TTS providers  
**Issue:** When returning empty audio on error, many providers hardcode the sample rate (e.g., `16000`, `24000`). If the sample rate map changes, these values become inconsistent.  
**Fix:** Use class constants or the SR_MAP from router.

### 34.6 🟡 `logger` variable formatting uses f-strings in some places, lazy % formatting in others
**Files:** All files  
**Issue:** Some `logger.debug(f"...")` use f-strings (always evaluated), while others use `logger.debug("... %s", var)` (lazy evaluation). For debug-level logs, the lazy form is preferred to avoid formatting overhead when the log level is not enabled.  
**Fix:** Convert f-strings in logger calls to lazy %-formatting for consistency and performance.

### 34.7 🟡 `TODO` / `FIXME` / `HACK` / `XXX` search
**Files:** All files  
**Issue:** No explicit TODO/FIXME/HACK/XXX comments found in the reviewed files. The codebase appears to avoid them or they've been removed.

---

## 35. Return Type Consistency Audit

| File | Function | Declared Return | Actual Return | Consistent? |
|------|----------|-----------------|---------------|-------------|
| `base.py` | `TTSProvider.synthesize` | `tuple[np.ndarray, list[dict]\|None, int]` | Raises NotImplementedError | N/A |
| `router.py` | `TTSRouter.synthesize` | `tuple` | `(np.ndarray, list, int)` or `(np.ndarray, list, int)` | ✅ (generic) |
| `edge_tts_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, list, int)` | ✅ |
| `elevenlabs_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, list, int)` | ✅ |
| `openai_tts_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` | ✅ |
| `openvoice_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None)` — only 2 values! | ❌ **Missing SR** |
| `speecht5_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` | ✅ |
| `alltalk_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` or `None` | ❌ **HTTPStatusError path returns None** |
| `piper_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` or `None` | ❌ **HTTPStatusError path returns None** |
| `coqui_local_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` or `None` | ❌ **HTTPStatusError path returns None** |
| `kokoro_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` | ✅ |
| `azure_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, list, int)` | ✅ |
| `dashscope_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` | ✅ |
| `volcengine_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` | ✅ |
| `deepgram_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` | ✅ |
| `mlx_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` | ✅ |
| `rvc_provider.py` | `synthesize` | `->tuple` | `(np.ndarray, None, int)` | ✅ |

---

## 36. Async/Sync Correctness Matrix

| File | Function | Declared | Implementation | Risk |
|------|----------|----------|----------------|------|
| `azure_provider.py` | `_synthesize_sync` | sync | Calls `speak_ssml_async().get()` — blocks thread ✅ (runs in executor) | Low |
| `elevenlabs_provider.py` | `_decode_mp3` | sync | `subprocess.run(... timeout=30)` — blocks event loop ⚠️ | **HIGH** |
| `elevenlabs_provider.py` | `synthesize` | async | Calls `_decode_mp3` (sync) without executor | **HIGH** |
| `speecht5_provider.py` | `_synthesize_sync` | sync | Blocking torch calls in executor ✅ | Low |
| `openvoice_provider.py` | `synthesize` | async | `loop.run_in_executor` ✅ | Low |
| `pipeline.py` | `start` | sync | Creates ThreadPoolExecutor ✅ | Low |

---

## Prioritized Fix Instructions

### 🔴 MUST FIX (crash, data loss, security)

1. **`elevenlabs_provider.py:61-79`** — Double iteration of response body (`aiter_lines` then `aiter_bytes`) means MP3 data is always empty. Fix: read all bytes once, parse alignment from bytes.
2. **`alltalk_provider.py:76-77`** — HTTPStatusError handler doesn't return, causing `None` unpack. Fix: add `return np.zeros(...)`.
3. **`piper_provider.py:33-34`** — Same as #2. Fix: add return.
4. **`coqui_local_provider.py:37-38`** — Same as #2. Fix: add return.
5. **`pipeline.py:288-289`** — ThreadPoolExecutor created every `start()` and never shut down. Fix: store and clean up executor.
6. **`elevenlabs_provider.py:151-153`** — `subprocess.run` blocks event loop. Fix: use `asyncio.create_subprocess_exec`.
7. **`kokoro_provider.py:34-36`** — Same as #2 for HTTPStatusError, but Kokoro already has a return after the handler — actually wait, Kokoro has `return` at line 36. Let me re-check.

Actually re-checking Kokoro:
```
except httpx.HTTPStatusError as e :
    logger .error (f"Kokoro TTS HTTP error: {e }")
    return np .zeros (0 ,dtype =np .float32 ),None ,24000 
```
Kokoro is fine — it has the return.

Piper:
```
except httpx.HTTPStatusError as e :
    logger .error (f"Piper TTS HTTP error: {e }")
    # no return!
```
Piper is missing return. Coqui is the same.

AllTalk:
```
except httpx .HTTPStatusError as e :
    logger .error (f"AllTalk TTS HTTP error: {e }")
    # falls through to next except
except httpx .RequestError as e :
    logger .error (f"AllTalk TTS request error: {e }")
    return np .zeros (0 ,dtype =np .float32 ),None ,24000 
```
AllTalk HTTPStatusError falls through to RequestError? No — the HTTPStatusError catches, logs, then falls through past the RequestError to the generic `except Exception` which returns. Wait:

```python
except httpx.HTTPStatusError as e :
    logger.error(f"AllTalk TTS HTTP error: {e}")
    # No return — falls through
except httpx.RequestError as e :
    logger.error(f"AllTalk TTS request error: {e}")
    return np.zeros(0, dtype=np.float32), None, 24000
except Exception as e :
    logger.error(f"AllTalk TTS error: {e}")
    return np.zeros(0, dtype=np.float32), None, 24000
```

Actually, if HTTPStatusError is a subclass of Exception, the first except catches it, and then it falls through to... no other matching except because Python only enters one except block. So after the HTTPStatusError handler runs, execution continues after ALL except blocks, i.e., the function's end, which returns `None` implicitly.

So AllTalk DOES have this bug. Let me update the priority list.

Let me finalize the review.

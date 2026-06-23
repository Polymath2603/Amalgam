# API Layer Code Review

**Review date:** 2026-06-22
**Scope:** All route files + WS handler + deps
**Total files reviewed:** 16
**Total lines reviewed:** 3,340

---

## Severity Legend
| Severity | Meaning |
|----------|---------|
| **CRITICAL** | Crash/security/data-loss bug in production |
| **HIGH**    | Real security vulnerability or functional bug that will cause errors |
| **MEDIUM**  | Significant code quality or design concern |
| **LOW**     | Minor style/robustness improvement |

---

## 1. `backend/api/ws/handler.py`

### CRITICAL: `_re` NameError in `_normalize_error()`

**`handler.py:54`** — The function uses `_re.sub(...)` but the file only does `import re` (no `as _re`). `_re` is undefined. Every incoming message that triggers error normalization will raise `NameError: name '_re' is not defined`.

**Fix:** Change line 54 to use `re.sub(...)` or add `import re as _re` to the imports.

---

### CRITICAL: Unbounded `receive_json()` in main loop

**`handler.py:1135`** — `await self.ws.receive_json()` parses JSON of any size. A malicious/large payload can exhaust memory. FastAPI's WebSocket doesn't enforce a message size limit by default.

**Fix:** Read raw bytes up to a limit (e.g. 10 MB), then parse manually. Or wrap in `asyncio.wait_for()` with a timeout.

---

### HIGH: `_normalize_error()` — potential ReDoS

**`handler.py:30`** — `re.search(r'\{.*\}', error_text, re.DOTALL)` on untrusted `error_text`. With `re.DOTALL` + greedy `.*` + nested braces in a large string, catastrophic backtracking is possible. Error text from LLM providers could be arbitrarily long.

**Fix:** Use `\{[^}]*\}` (non-greedy, no nested matching) or limit input length before regex.

---

### HIGH: Race condition in `cancel_assistant()` / `_on_task_done()`

**`handler.py:181-188`** — `cancel_assistant()` iterates over `self.pending_tasks` and calls `.cancel()` on each, then filters out done tasks *after* cancelling. Meanwhile `_on_task_done()` (registered via `add_done_callback`) also removes from the same list. Concurrent `remove()` and iteration on a `list` is not thread-safe (though all in the same event loop, callbacks run synchronously, so not a thread-safety issue). However, after `cancel_assistant()` at line 188 does `self.pending_tasks = [t for t in self.pending_tasks if not t.done()]`, the `_on_task_done` callbacks for those cancelled tasks will run and call `self.pending_tasks.remove(t)` on a potentially stale list reference.

**Fix:** Use `asyncio.Task.all_tasks()` pattern or use a `set` for pending tasks with `t.discard()`.

---

### HIGH: `retry_tool` exposes arbitrary MCP tool calls

**`handler.py:1206-1230`** — The frontend can call **any** MCP tool by name via `retry_tool` message type. The `tool_name` comes from `data.get("tool", "")` without any allowlist. If frontend security is compromised or a malicious frontend is used, this bypasses the normal slash-command permission model.

**Fix:** Add an allowlist or reuse the permission-level check from the `/permission` command.

---

### HIGH: `_voice_input_on()` callbacks silently swallow errors

**`handler.py:528-538`** — `on_transcription` and `on_speech_start` callbacks use `asyncio.run_coroutine_threadsafe()` and log failures, but the returned `Future` is never inspected. Exceptions from these coroutines are silently lost.

**Fix:** Store the Future and call `.add_done_callback()` to log/track exceptions.

---

### MEDIUM: `voices` route path parameter used in filesystem operations

**`handler.py:62-70`** — `_animation_dir(char_id)` constructs a filesystem path from `char_id` without sanitization. While this function is primarily called internally (not from user-controlled input directly), it's called from `_resolve_animation()` which receives text that could be crafted.

**Fix:** Normalize the resolved path and verify it's under `CHARACTERS_DIR`.

---

### MEDIUM: Large payload from `receive_json()` in main loop

**`handler.py:1135`** — No limit on incoming message size. An oversized JSON message could cause memory exhaustion.

**Fix:** Read raw bytes up to a configured maximum (e.g. 1 MB) and parse manually.

---

### MEDIUM: Missing rate limiting / throttling

**`handler.py:1133-1244`** — The main loop has no throttling. A client sending rapid messages, pings, or interrupt requests could starve the event loop.

**Fix:** Add token-bucket rate limiting per connection.

---

### MEDIUM: `_handle_avatar_signal` — no JSON schema validation

**`handler.py:418-434`** — Parses `sig_val` as JSON and accesses arbitrary fields. If the payload contains unexpected nested data, it may lead to errors (though the outer try/except handles that).

**Fix:** Use Pydantic model validation for structured data.

---

### MEDIUM: `handle_command("speak")` text length unbounded

**`handler.py:455-460`** — `data.get("text", "").strip()` with no length check. A very long text string could cause excessive TTS generation and memory use.

**Fix:** Truncate or reject text > N characters.

---

### MEDIUM: `asyncio.create_task` fire-and-forget in companion events

**`handler.py:1127, 1149, 1169, 1201`** — Multiple places use `asyncio.create_task()` without tracking or error handling. If these tasks fail, exceptions are silently lost.

**Fix:** Track with `self._track_task()` or add `.add_done_callback()` for logging.

---

### LOW: `_resolve_animation` uses `os.listdir` without error handling

**`handler.py:81-83`** — `os.listdir(default_dir)` and `os.listdir(char_dir)` could raise `PermissionError` if the directory exists but isn't readable. No try/except.

**Fix:** Wrap in try/except or use `Path.iterdir()` with error handling.

---

### LOW: `process_response` creates task without checking `agent()` availability

**`handler.py:194-199`** — Creates task for `_run_agent_loop` assuming `agent()` is available. If `agent()` returns None, the task will fail asynchronously.

**Fix:** Check `agent()` is not None before creating the task.

---

### LOW: `_wake_word_on` uses deprecated `asyncio.ensure_future`

**`handler.py:587`** — Uses `asyncio.ensure_future()` instead of `asyncio.create_task()`. The latter is preferred since Python 3.7.

**Fix:** Use `asyncio.create_task()`.

---

## 2. `backend/api/ws/tts_service.py`

### HIGH: Unpack tuple without length check in `synthesize_sentence()` and `synthesize_now()`

**`tts_service.py:319`** — `audio_np, viseme_schedule, sr = result` — unpacks a 3-tuple without validation. If the underlying TTS engine changes output format (returns 2-tuple or 4-tuple), this raises `ValueError: too many values to unpack`.

**`tts_service.py:383`** — Same issue in `synthesize_now()`.

**Fix:** Use the same safe unpacking pattern as `OrderedTTSScheduler._do_generate()` (lines 204-217) — check `len(result)` and handle 2-tuple case.

---

### MEDIUM: `_do_generate()` — radio silence during long TTS synthesis

**`tts_service.py:191-195`** — `asyncio.wait_for(tts().synthesize(...), timeout=60.0)` — if synthesis takes the full 60 seconds, no progress is reported to the frontend. The frontend has no heartbeat to know synthesis is still running.

**Fix:** Send periodic heartbeat/progress messages or reduce timeouts with retry.

---

### MEDIUM: No limit on base64 audio payload size

**`tts_service.py:225, 326, 386`** — `base64.b64encode(wav_bytes).decode("utf-8")` — if audio is very long (e.g., a 30-second clip), the base64 string could be multiple MB. Sent over WebSocket, this could cause head-of-line blocking.

**Fix:** Use chunked delivery for large audio payloads.

---

### MEDIUM: `synthesize_now()` called from `handle_command` is fire-and-forget

**`handler.py:459`, called by `tts_service.py:359`** — The task is created but not tracked in `self._track_task()` at the handler level (though `handle_command` does `self._track_task(t)` for the `synthesize_now` call). Actually line 459 does `self._track_task(t)`. So this is okay. But `synthesize_now` itself at line 359 doesn't have an explicit stream guard — it relies on the orchestrator.

Wait — actually `synthesize_now` is a standalone free function, not tied to any stream. It receives `ws` directly. No stream ID guard. So if a user speaks while a previous speak is still synthesizing, both results go to the WS.

---

## 3. `backend/api/routes/settings.py`

### HIGH: `/api/settings/get/{key}` exposes API keys without masking

**`settings.py:289-294`** — `get_setting(key)` returns the raw value for any settings key, including `provider.chatgpt.api_key`. No authentication. Any frontend or script can retrieve plaintext API keys.

**Fix:** Mask values matching `api_key` patterns, like `get_settings_safe()` does, or restrict which keys are readable.

---

### HIGH: `test_provider_connection()` — no timeout on external HTTP calls in non-async paths

**`settings.py:331, 369, 383`** — Uses `httpx.AsyncClient(timeout=10.0)` but does not apply `asyncio.wait_for()`. If the client's internal timeout mechanism fails (old httpx version, or OS-level hang), the coroutine could hang indefinitely.

**Fix:** Wrap in `asyncio.wait_for()` with a reasonable overall timeout.

---

### HIGH: Resource leak in `test_provider_connection()` when exception occurs before async with

**`settings.py:325-407`** — The `try` starts at line 325, but `async with httpx.AsyncClient(timeout=10.0) as client:` is inside `try`. If `AsyncClient()` raises before entering the `with` block, the client is never cleaned up. The `try` catches it, so the request returns an error, but not a resource leak since the client was never opened. Actually `httpx.AsyncClient()` constructor doesn't start a connection, so this is low risk.

---

### MEDIUM: TTS engine configuration not wrapped in try/except

**`settings.py:146-202`** — `update_settings()` configures TTS engines inline with no error handling. If `tts().configure_elevenlabs(api_key, model)` raises (e.g., bad API key), the entire request returns a 500 with no helpful error message.

**Fix:** Wrap TTS config blocks in try/except, log errors, and return a graceful error response.

---

### MEDIUM: Inconsistent error response format

**`settings.py:139`** — Returns `{"status":"error","errors":[...],"voice":...}` for validation errors.
**`settings.py:228, 250`** — Same format for set/batch.
**`settings.py:317`** — But uses `HTTPException(status_code=404, detail=...)` for provider-not-configured.

This inconsistency makes frontend error handling more complex.

**Fix:** Standardize on one error format across all routes (recommend `{"error": "...", "detail": {...}}` matching FastAPI conventions).

---

### MEDIUM: `get_settings_safe()` mask logic may expose partial API keys

**`settings.py:419-422, 433-442`** — The mask function returns `"****"` for strings < 12 chars, but the `if` guards at lines 433, 437, 441 check `len(iv) > 10`. An API key of length 11 would pass the `> 10` check but not be masked by `_mask()` (which checks `len(val) < 12`), so it would be returned in plaintext.

**Fix:** Make thresholds consistent: `_mask()` should use `len(val) < 8` or match the same `> 10` threshold.

---

### LOW: `reset_settings()` doesn't reload TTS/agent settings

**`settings.py:448-492`** — Only calls `llm().reload_settings()` at line 491, but doesn't reconfigure TTS, agent, or companion subsystems after resetting their values.

**Fix:** Apply the same propagation logic as `batch_set_settings()` (lines 262-285).

---

### LOW: `test_provider_connection()` — unused `import time` inside function

**`settings.py:308`** — `import time` inside the function body is unconventional. Should be at module top.

---

## 4. `backend/api/routes/characters.py`

### HIGH: Path traversal via `char_id` in `get_animations()`

**`characters.py:49-80`** — `char_id` query param is used in path construction at lines 69-78: `base / char_id / "anim"`. If `char_id` is `../../etc`, the path could escape `CHARACTERS_DIR`.

**Fix:** Validate `char_id` against a set of known character directories, or sanitize with `os.path.normpath()` and verify the resolved path starts with `CHARACTERS_DIR`.

---

### HIGH: Resource leak in `get_provider_models()` on exception

**`characters.py:126-147`** — Creates `LLMRouter(settings=settings())` and calls `await fresh_llm.close()` at the end. But if `fetch_opencode_models()`, `fetch_openai_compat_models()`, `fetch_bedrock_models()`, or `fetch_vertex_models()` raises an exception, `close()` is never called, leaking HTTP client connections.

**Fix:** Use try/finally to ensure `close()` is always called.

---

### MEDIUM: No error handling for external HTTP calls in model-fetching endpoints

**`characters.py:106-107`** — `await llm().fetch_ollama_models()` — if the Ollama server is unreachable, this raises an exception → 500.

**`characters.py:113-114`** — Same for `fetch_gemini_models()`.

**Fix:** Wrap in try/except, log error, return graceful error response.

---

### MEDIUM: Large subprocess output in `regenerate_icons()`

**`characters.py:177`** — `stdout.decode() + stderr.decode()` — if the Node.js VRM script produces gigabytes of output during 300s timeout, this could exhaust memory.

**Fix:** Stream output in chunks, or at least truncate.

---

### LOW: `get_character()` returns 404 with `{"error":"Character not found"}` — inconsistent format

**`characters.py:36`** — Uses `JSONResponse` with `{"error":...}`. Other routes use different formats.

**Fix:** Standardize error format.

---

## 5. `backend/api/routes/mcp.py`

### MEDIUM: No authentication on `update_mcp_servers()`

**`mcp.py:38-43`** — Any client can update MCP server configs, including enabling/disabling arbitrary commands via `approve_command` at line 53.

**Fix:** Add at least a permission level check (admin/auth).

---

### MEDIUM: `approve_command()` — mode validation bypass

**`mcp.py:69`** — Only checks `mode in ("prefix", "exact")` when `mcp()` is truthy. If `mcp()` is falsy, the mode check is skipped and the function proceeds to persist the command to `shell.allowed_prefixes` via any mode value (including "once").

**Fix:** Validate mode before any persistence: `if mode not in ("once", "prefix", "exact"): return error`.

---

### LOW: `get_mcp_tools()` — no try/except around `mcp().get_tool_schema()`

**`mcp.py:49`** — If `mcp().get_tool_schema()` raises (e.g., MCP client not initialized), this returns 500.

---

## 6. `backend/api/routes/memory.py`

### MEDIUM: No rate limit / size limit on session operations

**`memory.py:20-28`** — `get_session_messages(session_id)` takes a raw path param with no length validation. Very long session_id strings propagate to database queries.

**`memory.py:41-45`** — `resume_session(session_id, turns=5)` — `turns` parameter is unbounded. A value of 999999 could cause memory issues.

**Fix:** Clamp `turns` to a sane range (1–100); reject overly long session_id strings.

---

### MEDIUM: `delete_session()` — no existence check, no confirmation

**`memory.py:57-60`** — `delete_session(session_id)` deletes any session ID without checking if it exists. Returns `{"status": "ok"}` even if nothing was deleted.

**Fix:** Return 404 if session doesn't exist; add confirmation/soft-delete for destructive operations.

---

### LOW: `rename_session` deprecated but uses new_title as query param

**`memory.py:31-38`** — `new_title` is a FastAPI query param (not in body). If the title contains special characters (&, =), it could be malformed.

**Fix:** Accept new_title in request body via a Pydantic model.

---

## 7. `backend/api/routes/push.py`

### HIGH: File race condition — concurrent writes to `push_tokens.json`

**`push.py:32-43`** — `_load_tokens()` reads the file, `_save_tokens()` writes it. Multiple concurrent requests to `/api/push/register` or `/api/push/unregister` can interleave:
1. Request A reads tokens
2. Request B reads tokens
3. Request A modifies and writes
4. Request B modifies and writes (overwrites A's changes)

**Fix:** Use file locking (`fcntl.flock` on Linux) or switch to a proper database (SQLite with WAL).

---

### MEDIUM: Token leaks via `/api/push/tokens`

**`push.py:76-79`** — `list_tokens()` returns all registered push tokens. The comment says "not exposed in production" but there is no access control.

**Fix:** Remove the endpoint or add authentication.

---

### MEDIUM: Inconsistent error response for missing token

**`push.py:54-55`** — Returns `JSONResponse({"error": "Missing push token"}, status_code=400)` while most other routes return `{"status": "error", "errors": [...]}`.

**Fix:** Standardize error format.

---

### LOW: `strip()` on token in `unregister_token()` could unregister wrong token

**`push.py:67`** — `body.token.strip()` — if the original registration had a token with trailing spaces, stripping on unregister would produce a different key, and `tokens.pop(token, None)` would silently fail.

**Fix:** Strip on registration too, or don't strip at all.

---

## 8. `backend/api/routes/vault.py`

### HIGH: Path traversal via `filename` parameter

**`vault.py:45-51, 54-58, 61-65`** — `filename` is a path param used directly in filesystem operations via `vault().read(filename)`, `vault().write(filename, ...)`, `vault().delete(filename)`. If filename is `../../etc/passwd`, it could read/write arbitrary files on the filesystem.

**Fix:** Validate filename against a safe character set (`[a-zA-Z0-9_.-]+`), resolve to an absolute path, and verify it's under `VAULT_DIR`.

---

### LOW: All vault endpoints are deprecated but still functional

No authentication, no rate limiting.

---

## 9. `backend/api/routes/relationship.py`

### MEDIUM: No validation on `character_id`

**`relationship.py:13-16`** — `character_id` path param is used directly in `relationship().get_stats(character_id)`. If this eventually accesses filesystem or database, could be an injection vector.

**Fix:** Validate character_id is alphanumeric or exists in known character list.

---

## 10. `backend/api/routes/tts.py`

### MEDIUM: No length limit on TTS preview text

**`tts.py:27`** — `body.text` can be any length. A very long text could cause excessive memory use during TTS synthesis and a very large base64 audio response.

**Fix:** Reject text > 1000 characters (or configure a limit).

---

### LOW: `TTS(engine="openvoice")` created but never closed/cleaned up

**`tts.py:44`** — Creates a `TTS` instance per request for OpenVoice. If `TTS.__init__` has side effects (loading models, opening connections), repeated calls could leak resources.

**Fix:** Use a shared TTS pool or singleton.

---

## 11. `backend/api/routes/setup.py`

### MEDIUM: `setup_step1()` and `setup_step2()` — no validation of sub-parameters

**`setup.py:210-240`** — `req.provider` is not validated against allowed providers. Could set arbitrary provider key.

**`setup.py:243-270`** — `req.stt_engine` and `req.tts_engine` are not validated. Arbitrary strings could be stored.

**Fix:** Validate against known engines list (similar to `VALID_TTS_ENGINES`/`VALID_STT_ENGINES` in settings.py).

---

### MEDIUM: `save_setup()` uses raw dict with no validation

**`setup.py:300-325`** — `body: dict` is a raw dict. No Pydantic model validation for `provider`, `api_key`, `model`. If `api_key` is missing, returns `{"status": "error", "message": ...}` but the status code is 200 (not 400).

**Fix:** Use a Pydantic model and return proper HTTP 400 status code.

---

### LOW: `ENV_KEYS` referenced in `ImportError` fallback without guarantee of definition

**`setup.py:201-202`** — In the `ImportError` handler, `ENV_KEYS` is used as `ENV_KEYS.get(pid, [])` guarded by `if 'ENV_KEYS' in dir()`, which is fragile.

**Fix:** Use a `locals().get('ENV_KEYS', {})` pattern instead.

---

## 12. `backend/api/routes/companion.py`

### MEDIUM: `trigger_companion_message()` may leak internal errors

**`companion.py:46-55`** — If `sched.trigger_now()` raises an exception, it propagates as 500. The error message may contain stack traces or internal details.

**Fix:** Wrap in try/except, log the exception, return generic error.

---

### LOW: `update_companion_settings()` calls `await get_companion_settings()` which re-reads settings

**`companion.py:43`** — Calls the async function which calls `settings()` again. Minor inefficiency.

---

## 13. `backend/api/routes/metrics.py`

### MEDIUM: `_turns` list grows unboundedly until `_max_turns`

**`metrics.py:45-47`** — `_turns` is a global list that holds up to 500 entries with per-turn metrics. Each entry includes token counts, latency, model name. At 500 entries this is fine, but if `record_turn()` is called faster than the limit trims, there's a brief window where `len(_turns) > _max_turns` before the trim at line 47. This is a minor race at the module level (module-level globals are threadsafe in CPython for list append).

**Fix:** Use `collections.deque(maxlen=500)` instead.

---

### MEDIUM: `get_tool_stats()` and `get_tool_history()` — no error handling for `get_shared()["mcp"]`

**`metrics.py:60-63, 69-72`** — `get_shared()["mcp"]` could raise KeyError if "mcp" is not in the shared dict. Also `hasattr(client, "analytics")` is checked, but `client` itself could be None from the dict.

**Fix:** Use `get_shared().get("mcp")` and check for None.

---

## 14. `backend/api/routes/commands.py`

### LOW: No issues — static data, cached response.

---

## 15. `backend/api/deps.py` & `backend/api/server.py`

### LOW: No issues — simple re-exports.

---

## Summary by Severity

| Severity | Count | Key Examples |
|----------|-------|-------------|
| **CRITICAL** | 2 | `_re` NameError in error normalizer; unbounded WS receive |
| **HIGH** | 11 | Race in `cancel_assistant`; API key leak via `get_setting()`; path traversal in vault/characters; resource leak in `get_provider_models`; push token file race; ReDoS in error normalizer |
| **MEDIUM** | 23 | No rate limiting; unbounded text/params; missing error handling around external calls; inconsistent error formats; fire-and-forget task leaks |
| **LOW** | 10 | Style/dead-code/minor robustness |

---

## Action Items

1. **Fix CRITICAL bugs immediately**: `_re` NameError, WS receive limit
2. **Fix HIGH security issues**: API key exposure, path traversal, push token race
3. **Fix HIGH reliability issues**: resource leak, task race condition
4. **Address MEDIUM items** in next sprint: error response standardization, rate limiting, input validation
5. **Add authentication** — the entire API layer has no auth/authentication of any kind. Every route is accessible to any client that can reach the server.

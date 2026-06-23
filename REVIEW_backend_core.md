# Backend Core Code Review

**Files reviewed:**
- `backend/core/deps.py`
- `backend/app.py`
- `backend/core/startup.py`

**Date:** 2026-06-22
**Reviewer:** Jcode Agent

---

## How to Read This Report

Each finding has a severity: **CRITICAL** (will cause a runtime failure or data corruption), **HIGH** (likely to cause a bug in production), **MEDIUM** (definite code-quality / maintainability / edge-case issue), **LOW** (minor or advisory).

---

## CRITICAL Issues

### C1. Race condition: lazy initializations outside the lock (deps.py:126-143)

**File:** `backend/core/deps.py`, lines 126-143
**Severity:** CRITICAL
**Problem:** The `with _init_lock:` block ends at line 125. Lines 126-143 run *outside* the lock, yet they perform lazy-initialization checks-and-mutations on `_shared`:

```python
if _shared.get("characters_dir") is None:
    from backend.core.paths import CHARACTERS_DIR as _C
    _shared["characters_dir"] = _C
if _shared.get("health_registry") is None:
    from backend.core.health import get_registry as _gr
    _shared["health_registry"] = _gr()
if _shared.get("metrics_collector") is None:
    from backend.core.metrics import get_collector as _gc
    _shared["metrics_collector"] = _gc()
...
```

If two threads call `get_shared()` concurrently (e.g. from the WebUI *and* the CLI), both can see `None`, both execute the import + call, and the second assignment silently replaces the first. For `health_registry` and `metrics_collector` this could instantiate duplicate singletons with duplicate background tasks.

**Fix:** Move all lazy-init blocks inside the `with _init_lock:` block. Or restructure so there is a clear two-phase init: (1) everything inside the lock, (2) return after lock.

---

### C2. CompanionScheduler lambda closures close over mutable `_shared` dict (deps.py:97-101)

**File:** `backend/core/deps.py`, lines 97-101
**Severity:** CRITICAL
**Problem:** The `CompanionScheduler` is created with lambda closures that capture `_shared` by name:

```python
_shared["companion"] = CompanionScheduler(
    settings_provider=lambda: _shared["settings"],
    llm_provider=lambda: _shared["llm"],
    memory_provider=lambda: _shared["memory"],
)
```

These lambdas are evaluated lazily — when the scheduler actually starts, it reads `_shared["settings"]` etc. If any code path sets `_shared["settings"] = None` (or replaces it), the scheduler gets a broken reference. Also, because these are evaluated long after init, there's no guarantee those keys still exist in `_shared`.

**Fix:** Capture the references at init time instead of using lambdas:
```python
_settings, _llm, _memory = _shared["settings"], _shared["llm"], _shared["memory"]
_shared["companion"] = CompanionScheduler(
    settings_provider=lambda: _settings,
    llm_provider=lambda: _llm,
    memory_provider=lambda: _memory,
)
```

---

### C3. `settings._characters` — private attribute accessed from outside (startup.py:114)

**File:** `backend/core/startup.py`, line 114
**Severity:** CRITICAL
**Problem:** The settings reload callback directly writes to a private attribute:

```python
settings._characters = load_characters_from_yaml()
```

If `Settings` renames `_characters` (or changes its storage), this silently breaks. Additionally, any change callbacks or validation that `Settings` has registered for character data are bypassed.

**Fix:** Add a public method to `Settings`, e.g. `settings.reload_characters()`, that encapsulates the internal field update and triggers appropriate callbacks.

---

## HIGH Issues

### H1. Bare `except Exception` with zero logging in AgentFactory fallback (deps.py:115)

**File:** `backend/core/deps.py`, lines 115-116
**Severity:** HIGH
**Problem:** When `AgentFactory.create(...)` fails, the exception is caught with a bare `except Exception:` and *no error is logged at all*:

```python
try:
    _shared["agent"] = AgentFactory.create(...)
except Exception:
    _shared["agent"] = Agent(
        mcp_client=mcp_client,
        ...
    )
```

If the factory raises a `ValueError` (unknown agent type), `ImportError`, or any other exception, the operator has zero visibility into the failure. The fallback `Agent` may behave differently from the requested type.

**Fix:** At minimum, log the exception with `logger.exception(...)` before the fallback.

---

### H2. `get_shared()` is called on every accessor invocation (deps.py:147-166)

**File:** `backend/core/deps.py`, lines 147-166
**Severity:** HIGH
**Problem:** Each accessor function (e.g., `settings()`, `llm()`, `memory()`, etc.) calls `get_shared()` which acquires the threading lock every time. This is called potentially hundreds or thousands of times during a single user turn (from the WebSocket handler, agent loop, etc.), creating a lock contention bottleneck.

```python
def settings(): return get_shared()["settings"]
def llm(): return get_shared()["llm"]
...
```

**Fix:** Use a read-optimized pattern — after initialization is complete, accessors could reference the singletons directly (e.g., store references in module-level variables after first init, or use `_shared` directly without re-acquiring the lock). The lock is only needed for initialization; reads can be lock-free once initialized.

---

### H3. No type hints anywhere in `deps.py` (deps.py:1-185)

**File:** `backend/core/deps.py`
**Severity:** HIGH
**Problem:** The file has zero type hints. `_shared` dictionary keys are string literals with no typed interface, making refactoring error-prone. The accessor functions have no return type annotations. The voice pipeline registry uses `dict` without a type hint.

**Fix:** Add types — `from typing import ...` and annotate `_shared: dict[str, Any]`, the `get_shared()` return, all accessor functions, and the voice registry.

---

### H4. `asyncio.get_event_loop()` in async context — deprecated behavior (startup.py:51,69)

**File:** `backend/core/startup.py`, lines 51 and 69
**Severity:** HIGH
**Problem:** Uses `asyncio.get_event_loop()` inside an `async def` function. On Python 3.10+ this issues a `DeprecationWarning`; on 3.12+ it may behave unexpectedly (event loop policy changes).

```python
loop = asyncio.get_event_loop()         # line 51
settings.on_change(make_settings_reloader(mcp_client, asyncio.get_event_loop()))  # line 69
```

**Fix:** Use `asyncio.get_running_loop()` instead.

---

### H5. `asyncio.get_event_loop()` captured in closure — may become stale (startup.py:69, 92-118)

**File:** `backend/core/startup.py`, lines 69, 92-118
**Severity:** HIGH
**Problem:** The event loop reference is captured at init time (line 69) and passed to `make_settings_reloader()`, which stores it in a closure used by `_reload()`. If the event loop is replaced (e.g., in some testing frameworks or after a loop crash), the captured reference points to a closed/non-running loop. The `_reload` callback checks `loop.is_running()` (line 100), but between the check and `run_coroutine_threadsafe()` (line 110), the loop could be closed — a classic TOCTOU race.

**Fix:** Don't cache the loop reference. Instead, call `asyncio.get_running_loop()` fresh inside `_reload()`. Or pass the loop reference as a parameter whenever the callback is invoked.

---

### H6. `_shared` dict returned by reference — callers can silently corrupt state (deps.py:144)

**File:** `backend/core/deps.py`, line 144
**Severity:** HIGH
**Problem:** `get_shared()` returns the internal `_shared` dict directly. Any caller can write to it without holding the lock:

```python
# In startup.py line 76:
shared["plugin_manager"] = plugin_mgr
```

This bypasses the threading lock and can cause concurrent mutation races if `get_shared()` is called from another thread simultaneously.

**Fix:** Return a `copy.copy(_shared)` or a `types.MappingProxyType(_shared)` for read-only access, or provide a `set_shared(key, value)` function that acquires the lock.

---

### H7. Fire-and-forget tasks never referenced — un-trackable/un-cancellable (app.py:222,229,241, startup.py:66)

**Files:**
- `backend/app.py` line 222 (`asyncio.create_task(run_telegram())`)
- `backend/app.py` line 229 (`asyncio.create_task(serve_grpc())`)
- `backend/app.py` line 241 (`asyncio.create_task(_delayed_startup_tasks())`)
- `backend/core/startup.py` line 66 (`asyncio.create_task(mcp_client.connect_from_settings(mcp_servers))`)
**Severity:** HIGH
**Problem:** All of these create asyncio Tasks that are never stored. On shutdown, there is no mechanism to wait for them to complete or cancel them. If any of these tasks currently holds a resource (e.g., a gRPC listener socket, an MCP connection, a file handle), the shutdown path may close resources out from under them, leading to `Task was destroyed but it is pending!` warnings or runtime errors.

**Fix:** Store task references in a module-level set, and cancel them in the shutdown handler:
```python
_background_tasks: set[asyncio.Task] = set()

task = asyncio.create_task(...)
_background_tasks.add(task)
task.add_done_callback(_background_tasks.discard)
```

---

### H8. `_RateLimitMiddleware` uses `BaseHTTPMiddleware` — known compatibility issues (app.py:64-87)

**File:** `backend/app.py`, lines 64-87
**Severity:** HIGH
**Problem:** Starlette's `BaseHTTPMiddleware` is explicitly discouraged in the Starlette/FastAPI docs because it wraps the entire ASGI interface and can:
- Break streaming responses (the middleware reads the entire body before passing it)
- Mangle background tasks
- Cause issues with WebSocket endpoints

**Fix:** Implement rate limiting as pure ASGI middleware (a class implementing `__init__` and `__call__` with the `(scope, receive, send)` signature), or use FastAPI's middleware via `@app.middleware("http")`.

---

### H9. `FTSSearch` runs synchronous I/O in an async endpoint (app.py:158-163)

**File:** `backend/app.py`, lines 158-163
**Severity:** HIGH
**Problem:** The `/ready` endpoint creates an `FTSSearch` instance and calls `.search("probe")` — both are synchronous I/O-bound operations. This blocks the event loop for the duration of the FTS index load and search.

```python
fts = FTSSearch(CONVERSATIONS_DIR)   # synchronous disk I/O
fts.search("probe")                   # synchronous disk I/O
```

**Fix:** Wrap in `asyncio.to_thread()` or `loop.run_in_executor()`.

---

### H10. `memory.start_session()` called every time `init_application()` runs (startup.py:45)

**File:** `backend/core/startup.py`, line 45
**Severity:** HIGH
**Problem:** The docstring says `init_application()` is "Safe to call multiple times (idempotent for singletons)." But `memory.start_session()` is called unconditionally (line 45). Each call starts a *new* conversation session, which may have side effects (e.g., creating a new session DB record, resetting conversation state). If `init_application()` is called twice (e.g., during testing or a restart), sessions proliferate.

**Fix:** Guard with an `if not memory.has_active_session():` check, or track initialization state externally.

---

## MEDIUM Issues

### M1. Stale entries pruned with O(n) `list.pop(0)` in rate limiter (app.py:79-80)

**File:** `backend/app.py`, lines 79-80
**Severity:** MEDIUM
**Problem:** `while window and window[0] < now - self.window_seconds: window.pop(0)` — `list.pop(0)` is O(n) because it shifts all remaining elements. With 120 requests per window per IP, this is modest but unnecessary. A `collections.deque` would give O(1) `popleft()`.

**Fix:** Change `_in_flight_requests` values from `list[float]` to `collections.deque[float]` and use `window.popleft()`.

---

### M2. Rate limiter IP-fallback key `"unknown"` creates a single shared bucket (app.py:75)

**File:** `backend/app.py`, line 75
**Severity:** MEDIUM
**Problem:** When `request.client` is `None` (e.g., behind certain proxies), the client IP defaults to `"unknown"`. All such requests share a single rate-limit bucket of 120/60s, which is either too permissive (one misbehaving source starves others) or too restrictive (well-behaved sources get blocked by the bucket being consumed by others).

**Fix:** Use the `X-Forwarded-For` header or a proxy IP as a fallback, or at least log when the IP is missing.

---

### M3. `logger.warning` used for normal operational messages (app.py:207,237)

**File:** `backend/app.py`, lines 207 and 237
**Severity:** MEDIUM
**Problem:** Startup messages like "Starting Amalgam backend..." and "Server ready on http://..." use `logger.warning()` instead of `logger.info()`. This pollutes WARNING-level logs with routine messages.

**Fix:** Use `logger.info()` for normal lifecycle messages, reserve `warning()` for unusual-but-recoverable conditions.

---

### M4. `logger.debug` used for an error on shutdown (app.py:253)

**File:** `backend/app.py`, line 253
**Severity:** MEDIUM
**Problem:** If the companion scheduler fails to stop during shutdown, the error is logged at DEBUG level:

```python
logger.debug("Failed to stop companion scheduler on shutdown: %s", e)
```

This buries a potentially important error in verbose debug logs. At minimum it should be `logger.warning`.

**Fix:** Change to `logger.warning(...)`.

---

### M5. Imports with spaces around dots (app.py:27-41)

**File:** `backend/app.py`, lines 27-41
**Severity:** MEDIUM
**Problem:** The import statements use unusual spacing:
```python
from backend .api .ws .handler import handle_chat
from backend .api .routes import (
    settings as settings_route ,
```

While syntactically valid Python, this is non-idiomatic and will confuse linters, formatters, and human readers. Most auto-formatters (`black`, `ruff format`) would strip these spaces.

**Fix:** Use standard Python import style:
```python
from backend.api.ws.handler import handle_chat
from backend.api.routes import (
    settings as settings_route,
    ...
)
```

---

### M6. `asyncio` re-imported inside a function when already imported at module level (app.py:214-215)

**File:** `backend/app.py`, lines 214-215
**Severity:** MEDIUM
**Problem:** Inside the `startup` event handler:
```python
import asyncio
asyncio.create_task(sched.start())
```

`asyncio` is already imported at line 7. This re-import is redundant and adds unnecessary import overhead.

**Fix:** Remove the redundant `import asyncio`.

---

### M7. Inconsistent router variable naming convention (app.py:173-185)

**File:** `backend/app.py`, lines 173-185
**Severity:** MEDIUM
**Problem:** Some routers are imported with a `_route` suffix (`settings_route`, `commands_route`, `mcp_route`, `memory_route`, `metrics_route`, `push_route`, `tts_route`, `setup_route`, `companion_route`) while others have no suffix (`characters`, `vault`, `relationship`). This inconsistency makes the code harder to read and maintain.

**Fix:** Adopt a single convention — either always suffix `_route` or never suffix it.

---

### M8. `serve_webui` route defined inside conditional block — invisible to linters (app.py:259-267)

**File:** `backend/app.py`, lines 259-267
**Severity:** MEDIUM
**Problem:** The `serve_webui` function and its `@app.get(...)` decorator are inside `if index_path.exists():`. Static analysis tools cannot see this route declaration, so route listings and linters may miss it. If the file is absent at import time but created later, the route is never registered (even after a re-create).

**Fix:** Register the route unconditionally, and have the handler itself check `index_path.exists()` and return 404 if absent, or generate it.

---

### M9. `_delayed_startup_tasks` imports private `_reloader` from another module (app.py:277)

**File:** `backend/app.py`, line 277
**Severity:** MEDIUM
**Problem:** 
```python
from backend.core.hot_reload import setup_hot_reload, _reloader
```
Importing a private name (`_reloader`) from another module breaks encapsulation. If `hot_reload.py` renames or refactors `_reloader`, this import silently breaks.

**Fix:** Import only the public API (`setup_hot_reload` which already returns the reloader). The caller already gets the return value on line 281.

---

### M10. `/ready` endpoint creates a new `FTSSearch` instance on every request (app.py:162-163)

**File:** `backend/app.py`, lines 162-163
**Severity:** MEDIUM
**Problem:** Each `/ready` probe creates a fresh `FTSSearch(CONVERSATIONS_DIR)` object, which may:
- Open/close FTS index files
- Initialize Whoosh/FTS objects
- Run synchronous I/O (see H9)

This is wasteful for a health-check endpoint that may be called every few seconds by load balancers.

**Fix:** Cache the FTS instance globally or use a simpler health check (e.g., can the DB file be stat'd?).

---

### M11. Missing `has_active_session()` guard in `memory.start_session()` (startup.py:45)

**File:** `backend/core/startup.py`, line 45
**Severity:** MEDIUM
**Problem:** Every call to `init_application()` calls `memory.start_session()` unconditionally. If called multiple times (e.g., in tests), this creates multiple active sessions with no cleanup.

**Fix:** Check `memory.has_active_session()` before starting a new one, or call `start_session()` only once from `__main__`.

---

### M12. Module-level `_metrics = MetricsCollector(...)` in agent/core.py creates a global file handle (agent/core.py:26)

**File:** `backend/core/agent/core.py`, line 26
**Severity:** MEDIUM
**Problem:** 
```python
_metrics = MetricsCollector("data/metrics.db")
```
This is at module level, so the MetricsCollector is instantiated when the module is first imported (possibly before logging is configured, before data directories exist). It opens a SQLite file handle. If `data/` doesn't exist yet, this may fail or create an empty file in an unexpected location.

**Fix:** Lazily initialize the metrics collector, or use the one from `_shared`/`deps`.

---

### M13. Inconsistent error-level logging in shutdown paths (startup.py:139-146, app.py:253)

**File:** `backend/core/startup.py`, lines 139-146 and `backend/app.py` line 253
**Severity:** MEDIUM
**Problem:** In `startup.py:139-146`, plugin shutdown errors are logged as `logger.warning(...)`. In `app.py:253`, companion scheduler stop failure is logged as `logger.debug(...)`. In `startup.py:145-146`, the top-level shutdown exception handler uses `logger.warning(...)`. There is no consistent policy.

**Fix:** Establish a policy: unrecoverable errors during shutdown should be `logger.error()`, recoverable issues `logger.warning()`. Debug-level should never be used for errors.

---

### M14. `_voice_pipeline_registry` is completely unprotected (deps.py:173-185)

**File:** `backend/core/deps.py`, lines 173-185
**Severity:** MEDIUM
**Problem:** The voice pipeline registry is a module-level dict accessed through setters/getters without any locking:

```python
_voice_pipeline_registry: dict = {}

def set_voice_pipeline(pipeline):
    _voice_pipeline_registry["pipeline"] = pipeline

def get_voice_pipeline():
    return _voice_pipeline_registry.get("pipeline")
```

If `set_voice_pipeline()` is called from one thread while `get_voice_pipeline()` is called from another (e.g., WebSocket handler vs. settings-change callback), this is a data race on the dict.

**Fix:** Add a threading lock or use `asyncio.Lock` since this is likely only accessed from async contexts. Or use a simple module-level variable protected by a lock.

---

### M15. `cli.provider` import depends on the package root being on `sys.path` (deps.py:139-140)

**File:** `backend/core/deps.py`, lines 139-140
**Severity:** MEDIUM
**Problem:** 
```python
from cli.provider import KNOWN_PROVIDERS as _kp
from cli.provider import PROVIDER_MODELS as _pm
```

`cli/` is at the project root, NOT inside `backend/`. This import only works when the project root is on `sys.path`. If the backend is installed as a package (e.g., via `pip install`), `cli.provider` is not resolved and this import fails at runtime.

**Fix:** Move `cli/provider.py` to `backend/cli/provider.py` or re-export from a backend-internal module.

---

### M16. 500 % chance of silent half-init if `register_subagent_spawner` raises (deps.py:124-125)

**File:** `backend/core/deps.py`, lines 124-125
**Severity:** MEDIUM
**Problem:** Inside the lock, after `_shared["agent"]` is set (either from factory or fallback), line 125 calls:
```python
mcp_client.register_subagent_spawner(_shared["agent"].spawn_subagent)
```
If this call raises, the `with _init_lock` block exits with an exception. But `_shared["agent"]` is already set to a value, and `_shared["mcp"]` is also set. However, the rest of the lock block (e.g., `_shared["orchestrator"]`, `_shared["companion"]`) may not have been executed yet, leaving `_shared` in an inconsistent partially-initialized state. Subsequent calls to `get_shared()` will see some non-None values and skip initialization for those, but others remain None.

**Fix:** Use a temp dict, assemble everything, then assign to `_shared` atomically. Or at minimum add a try-except around the spawner registration.

---

## LOW Issues

### L1. Agent type silently degrades from `None` to `"basic"` (deps.py:103-107)

**File:** `backend/core/deps.py`, lines 103-107
**Severity:** LOW
**Problem:**
```python
agent_type = _shared["settings"].get("agent.type", "reflective_planning")
mcp_client = _shared["mcp"]
try:
    _shared["agent"] = AgentFactory.create(
        agent_type or "basic",
        ...
    )
```

If `agent.type` is set to `null` in config, `agent_type` becomes `None`, and the fallback `agent_type or "basic"` silently changes the agent type to "basic" without any log. If the key is absent, the default "reflective_planning" is used. The behavior differs between `null` (→ "basic") and missing-key (→ "reflective_planning"), which is likely unintended.

**Fix:** Normalize the default before the fallback, or log when the agent type is overridden.

---

### L2. `vault.path` default is `""` — empty string may cause issues (deps.py:58)

**File:** `backend/core/deps.py`, line 58
**Severity:** LOW
**Problem:**
```python
vault_path = _shared["settings"].get("vault.path", "")
_shared["vault"] = VaultManager(vault_path, embeddings_path=str(EMBEDDINGS_DIR))
```

If `vault.path` is not set, the empty string `""` is passed to `VaultManager`, which may use the CWD or fail with an unclear error. A proper default (like `str(VAULT_DIR)`) would be safer.

**Fix:** Provide a meaningful default:
```python
vault_path = _shared["settings"].get("vault.path", str(VAULT_DIR))
```

---

### L3. `loop.run_in_executor` on OpenVoice preload but not on other TTS engine init (startup.py:51-52)

**File:** `backend/core/startup.py`, lines 51-52
**Severity:** LOW
**Problem:** OpenVoice TTS preloading runs via `run_in_executor` (non-blocking), but other TTS initialization happens synchronously in `get_shared()` (blocking the event loop). The inconsistency suggests some TTS engines may block at startup without warning.

**Fix:** Either document that all TTS engines are lazy-loaded except OpenVoice, or make all TTS initialization async.

---

### L4. `_RateLimitMiddleware` catches rate-limit-exceeded after the limit, not before (app.py:77-86)

**File:** `backend/app.py`, lines 77-86
**Severity:** LOW
**Problem:** The sliding window algorithm adds the current request timestamp to the window *before* reaching the limit check. This means a burst of 121 requests in 1 second would pass the first 120 and reject the 121st, but the 120th request that *caused* the window to be full would have already passed through. This is a minor accounting issue for a simple rate limiter.

**Fix:** Check `len(window) >= self.max_requests` *before* appending the current timestamp. If exceeded, return 429 without appending.

---

### L5.  `_in_flight_requests` format is typed but the type annotation is `list[float]` (app.py:61) — correct, but the key `"unknown"` breaks the type contract

**File:** `backend/app.py`, line 61
**Severity:** LOW
**Problem:** The annotation says `dict[str, list[float]]`. The `"unknown"` key is consistent with that. No type problem. Noting only that the unknown-IP bucket is shared (already covered in M2). Not an actual type issue.

---

### L6. `load_characters_from_yaml` imported but only used in `_reload` (startup.py:12, 114)

**File:** `backend/core/startup.py`, line 12 and line 114
**Severity:** LOW
**Problem:** `load_characters_from_yaml` is imported at module level (line 12) but only used inside the `_reload()` closure (line 114). The import could be moved to the function to avoid loading the YAML module at import time.

---

### L7. `mimetypes.add_type` calls at module level (app.py:23-25)

**File:** `backend/app.py`, lines 23-25
**Severity:** LOW
**Problem:** `mimetypes.add_type("text/css", ".css")` etc. are module-level side effects. If `app.py` is imported (not just run), these modify the global `mimetypes` mapping, which may affect other modules in the process. This is a minor concern but worth noting.

**Fix:** Move inside `create_app()` or guard with `if __name__ == "__main__":`.

---

### L8. `os.environ.get("NO_BROWSER")` and threading.Timer inside async startup (app.py:239-240)

**File:** `backend/app.py`, lines 239-240
**Severity:** LOW
**Problem:** 
```python
if not os.environ.get("NO_BROWSER"):
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
```

Spawning a thread from inside an async startup handler is a code-smell (mixing threading with async). The browser-open could also be done from the `_delayed_startup_tasks` coroutine using `asyncio.create_subprocess_exec`.

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 3     |
| HIGH     | 10    |
| MEDIUM   | 16    |
| LOW      | 8     |
| **Total**| **37**|

### Most impactful findings:

1. **C1** — Race condition in lazy init outside the lock (`deps.py:126-143`) will cause data corruption under concurrent access from CLI + WebUI.
2. **H2** — `get_shared()` lock held on every singleton access — major performance bottleneck.
3. **H7** — Un-tracked fire-and-forget tasks (`app.py:222,229,241`, `startup.py:66`) cause shutdown races and resource leaks.
4. **C3** — Private attribute `settings._characters` write (`startup.py:114`) bypasses encapsulation.
5. **H8** — `BaseHTTPMiddleware` in rate limiter (`app.py:64-87`) can break streaming and WebSocket responses.

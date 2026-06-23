# Backend Core Code Review — Round 2

**Files reviewed (line by line):**
- `backend/core/deps.py` (269 lines)
- `backend/app.py` (356 lines)
- `backend/core/startup.py` (153 lines)

**Previous review:** `REVIEW_backend_core.md` — 37 issues found
**This review:** Verifies all 37 fixes and identifies remaining/new issues

---

## 1. Verification of Previous 37 Issues

| ID | Severity | Status | Notes |
|----|----------|--------|-------|
| C1 | CRITICAL | ✅ FIXED | Lazy inits moved inside `with _init_lock:` block (lines 148-174) |
| C2 | CRITICAL | ✅ FIXED | Lambdas capture local refs (`_settings_ref`, etc.) at lines 104-108 |
| C3 | CRITICAL | ✅ FIXED | Uses `settings.reload_characters()` public API (startup.py:121) |
| H1 | HIGH | ✅ FIXED | `logger.exception()` added before fallback (deps.py:131) |
| H2 | HIGH | ✅ FIXED | Accessors read `_shared` directly without lock (deps.py:189-247) |
| H3 | HIGH | ⚠️ PARTIALLY | 7 of 16 accessors + 3 voice pipeline functions still lack return type annotations |
| H4 | HIGH | ✅ FIXED | Uses `asyncio.get_running_loop()` (startup.py:52) |
| H5 | HIGH | ❌ **REGRESSION** | `get_running_loop()` inside `_reload` callback WILL crash in thread context (see #N4) |
| H6 | HIGH | ✅ FIXED | Returns `MappingProxyType(_shared)` (deps.py:177) |
| H7 | HIGH | ⚠️ PARTIALLY | app.py tasks tracked with `_track_task`; startup.py task tracked but NEVER cancelled (see #N2) |
| H8 | HIGH | ✅ FIXED | Pure ASGI middleware `_RateLimitMiddleware` |
| H9 | HIGH | ✅ FIXED | `asyncio.to_thread()` wraps FTS search (app.py:212) |
| H10 | HIGH | ❌ **PARTIALLY** | Guard added but accesses private `memory._current_session` (see #N1) |
| M1 | MEDIUM | ✅ FIXED | Uses `deque.popleft()` |
| M2 | MEDIUM | ✅ FIXED | X-Forwarded-For detection added |
| M3 | MEDIUM | ✅ FIXED | `logger.info()` for lifecycle messages |
| M4 | MEDIUM | ✅ FIXED | `logger.warning()` for shutdown errors |
| M5 | MEDIUM | ✅ FIXED | Normal import spacing |
| M6 | MEDIUM | ✅ FIXED | No redundant `import asyncio` |
| M7 | MEDIUM | ✅ FIXED | Consistent `_route` suffix |
| M8 | MEDIUM | ✅ FIXED | Route registered unconditionally |
| M9 | MEDIUM | ✅ FIXED | Only imports public `setup_hot_reload` |
| M10 | MEDIUM | ✅ FIXED | Cached `_cache_fts` instance (though race-prone, see #N7) |
| M11 | MEDIUM | ❌ SAME AS H10 | Same private-attribute-access issue |
| M12 | MEDIUM | ⏭️ OUT OF SCOPE | `agent/core.py` — not in reviewed files |
| M13 | MEDIUM | ✅ FIXED | Consistent `logger.warning()` for shutdown errors |
| M14 | MEDIUM | ✅ FIXED | `_voice_pipeline_lock` protects registry |
| M15 | MEDIUM | ✅ MITIGATED | try/except around `cli.provider` imports |
| M16 | MEDIUM | ✅ FIXED | try/except resets agent to `None` and re-raises |
| L1 | LOW | ✅ FIXED | Logs when `agent.type` is null (deps.py:117-118) |
| L2 | LOW | ✅ FIXED | Uses `str(VAULT_DIR)` default |
| L3 | LOW | ⏭️ DESIGN NOTE | Documents that only OpenVoice is eagerly preloaded |
| L4 | LOW | ✅ FIXED | Checks limit before appending |
| L5 | LOW | ✅ FIXED | `deque[float]` annotation |
| L6 | LOW | ✅ FIXED | No module-level `load_characters_from_yaml` |
| L7 | LOW | ✅ FIXED | Inside `create_app()` |
| L8 | LOW | ✅ FIXED | `asyncio.create_task()` instead of `threading.Timer` |

---

## 2. New & Remaining Issues Found

### N1 [MEDIUM] — Private attribute access: `memory._current_session` (startup.py:45)

**File:** `backend/core/startup.py`, line 45
**Severity:** MEDIUM
**Description:** The fix for H10 guards `memory.start_session()` with a check of the private attribute `_current_session`:
```python
if memory._current_session is None:
    memory.start_session()
```
This is the **same anti-pattern as the original C3** (which was writing to `settings._characters`). Accessing `_current_session` bypasses encapsulation. `Memory` does have a public `get_current_session()` method (manager.py:330), but it has a side effect (auto-starts a session if None). The correct fix would be to either:
- Add a public `has_active_session()` method to `Memory` that checks `_current_session is not None`, or
- Use `get_current_session()` knowing it auto-starts (but then the guard would be pointless).

This works today but will silently break if `Memory` renames `_current_session`.
**Fix:** Add `memory/manager.py`: `def has_active_session(self) -> bool: return self._current_session is not None` and call that from startup.py.

---

### N2 [HIGH] — Startup.py MCP background task is tracked but never cancelled (startup.py:67)

**File:** `backend/core/startup.py`, lines 67, 94
**Severity:** HIGH
**Description:** Line 67 adds the MCP connection task to `_background_tasks`:
```python
_background_tasks.add(asyncio.create_task(mcp_client.connect_from_settings(mcp_servers)))
```
But `_background_tasks` (defined at line 94) is **never used for cancellation**:
- `shutdown_application()` (lines 128-153) does not cancel these tasks
- `app.py`'s shutdown handler cancels app.py's own `_background_tasks` set, **not** startup.py's
- No `add_done_callback(_background_tasks.discard)` is set, so completed tasks accumulate in the set (unbounded growth)

This means: (a) the MCP connection task is not gracefully shut down, (b) it creates a memory leak of task references, (c) on shutdown, `mcp().close()` may race with the still-running connection task.
**Fix:** Either (1) add `task.add_done_callback(_background_tasks.discard)` and cancel tasks in `shutdown_application()`, or (2) track the MCP task in app.py's `_background_tasks` which IS properly cancelled, or (3) use app.py's `_track_task()` utility.

---

### N3 [CRITICAL] — Settings hot-reload callback WILL crash — regression from H5 fix (startup.py:106)

**File:** `backend/core/startup.py`, lines 106, 101-125
**Severity:** CRITICAL
**Description:** The fix for H5 replaced the cached event-loop reference with:
```python
def _reload(settings):
    loop = asyncio.get_running_loop()   # line 106
    ...
    asyncio.run_coroutine_threadsafe(..., loop)
```

However, `_reload` is called synchronously from `Settings._fire_callbacks()` (settings.py:552-565), which is called from:
1. The file-watcher daemon thread (settings.py:603: `self._fire_callbacks()` in `_watch_loop`)
2. The `set()` method (settings.py:773: `self._fire_callbacks()`) — potentially from any thread

Since these are **non-async threads**, `asyncio.get_running_loop()` raises `RuntimeError: no running event loop`. The exception IS caught by the `except Exception` at line 122, so the app doesn't crash, but the **settings hot-reload silently fails** — MCP servers are not reconnected, characters are not reloaded. The entire settings-change reactivity is broken.

This is a **regression**: the original cached-loop approach at least worked (though it had TOCTOU issues). The new code always fails in the file-watcher path.
**Fix:** Do not use `get_running_loop()` in the `_reload` callback. Instead, either:
- Store the event loop reference at app startup (e.g., from `init_application()` which is async) and capture it in the closure, OR
- Use `asyncio.run_coroutine_threadsafe` with a stored loop reference, OR
- Use `loop.call_soon_threadsafe()` with a stored loop, OR
- Run the entire hot-reload logic via `loop.run_in_executor()` or schedule it with the stored loop.

The safest approach: capture the loop at app initialization time:
```python
_loop = asyncio.get_running_loop()  # in init_application()
# ...
make_settings_reloader(mcp_client, loop=_loop)
```
And inside `_reload`, use the stored loop.

---

### N4 [MEDIUM] — In-place mutation of cached MCP server config dicts (startup.py:60-66, 109-115)

**File:** `backend/core/startup.py`, lines 60-66 and `make_settings_reloader` closure lines 109-115
**Severity:** MEDIUM
**Description:** `Settings.get_mcp_servers()` returns `self.get("mcp.servers", [])` (settings.py:913) which returns the **actual list object** from `self.data` (not a copy, settings.py:737). The code then mutates the server dicts in-place:
```python
for s in mcp_servers:
    if s.get("name") == "shell":
        s.setdefault("env", {})
        s["env"]["AMALGAM_SHELL_MODE"] = shell_mode   # mutates cached config!
        s["env"]["AMALGAM_SHELL_ALLOWED_COMMANDS"] = ...   # mutates cached config!
```

This modifies the internal cached settings data directly. On subsequent calls, the env vars are already present (re-set to same values, benign but wrong). If `mcp_servers` is passed to other code or serialized, the modified state leaks. Additionally, if the config file is reloaded, the in-memory cache might get stale env values that don't match the file.
**Fix:** Make a deep copy before modifying:
```python
import copy
mcp_servers = copy.deepcopy(settings.get_mcp_servers())
```
Or have `get_mcp_servers()` return a deep copy.

---

### N5 [MEDIUM] — Writing to private attribute of another module (deps.py:54)

**File:** `backend/core/deps.py`, line 54
**Severity:** MEDIUM
**Description:** The C1 fix introduced:
```python
_settings_mod._global_settings = _shared["settings"]
```

This writes to the **private** attribute `_global_settings` of the `_settings_mod` module (`backend.core.config.settings`). While this is documented in the settings module (line 959-962) as "C5" — an intentional backdoor for the module-level convenience wrappers — it is the same pattern that was flagged as CRITICAL in C3 (`settings._characters` write). The settings module has a public `_get_global_settings()` accessor but the initial assignment bypasses it.

If `_settings_mod` renames `_global_settings`, this line silently breaks.
**Fix:** Add a public setter `Settings.set_global_instance(instance)` and call that instead. Or have `get_shared()` create the settings module wrappers through a proper init function.

---

### N6 [MEDIUM] — Missing return type annotations on 7 accessors + 3 voice functions (deps.py:228-269)

**File:** `backend/core/deps.py`, lines 228-247, 256-269
**Severity:** MEDIUM
**Description:** Most accessor functions were given return type annotations (H3 fix), but these still lack them:

| Function | Line |
|----------|------|
| `companion()` | 228 |
| `characters_dir()` | 231 |
| `health_registry()` | 234 |
| `metrics_collector()` | 237 |
| `switch_profile_func()` | 240 |
| `known_providers()` | 243 |
| `provider_models()` | 246 |
| `set_voice_pipeline(pipeline)` — `pipeline` param | 256 |
| `get_voice_pipeline()` — return type | 261 |
| `clear_voice_pipeline()` — return type | 267 |

**Fix:** Add appropriate return type annotations. For the lazy-initialized ones, use `Optional[str]`, `Optional[HealthRegistry]`, etc.

---

### N7 [LOW] — Race condition on `_cache_fts` in `/ready` endpoint (app.py:203-216)

**File:** `backend/app.py`, lines 61, 203-216
**Severity:** LOW
**Description:** `_cache_fts` (line 61) is a module-level variable accessed without synchronization in the `/ready` handler:
```python
global _cache_fts
if _cache_fts is None:
    _cache_fts = FTSSearch(CONVERSATIONS_DIR)   # race: two requests both see None
await asyncio.to_thread(_cache_fts.search, "probe")
db_ok = True
...
except Exception:
    _cache_fts = None  # race: overwrites another request's valid FTS
```

Two concurrent `/ready` requests can both see `_cache_fts is None`, both create `FTSSearch` instances, and one's reference is lost (resource leak). If one fails, its exception handler sets `_cache_fts = None`, potentially discarding the other request's valid FTS.
**Fix:** Use a simple lock or `asyncio.Lock` for `_cache_fts` access. Or use `setdefault` on a dict. Since it's a health-check endpoint, could also use `threading.Lock`.

---

### N8 [LOW] — Forward reference to `_background_tasks` before definition (startup.py:67)

**File:** `backend/core/startup.py`, lines 67, 94
**Severity:** LOW
**Description:** Line 67 references `_background_tasks`, but the assignment `_background_tasks: set[asyncio.Task] = set()` doesn't appear until line 94. Python resolves global names at function-call time (not definition time), so this works in practice. But it's fragile: if anything ever calls `init_application()` during module import (before `_background_tasks` is assigned), it will raise `NameError`.
**Fix:** Move `_background_tasks` definition (line 94) before `init_application()` definition (line 16), or import it from a shared location.

---

### N9 [LOW] — X-Forwarded-For detection has unnecessary condition (app.py:89)

**File:** `backend/app.py`, lines 89
**Severity:** LOW
**Description:** In the rate limiter, the code checks `if scope["type"] == "http":` at line 89, but this condition is **always True** because lines 78-80 already returned early for non-http scopes:
```python
if scope["type"] != "http":
    await self.app(scope, receive, send)
    return
```
The guard is dead code. Minor, but suggests confusion about the control flow.
**Fix:** Remove the redundant `if scope["type"] == "http":` guard.

---

### N10 [LOW] — `_background_tasks` snapshot during shutdown may miss newly-added tasks (app.py:307-311)

**File:** `backend/app.py`, lines 307-311
**Severity:** LOW
**Description:** The shutdown handler takes a snapshot:
```python
tasks_to_cancel = list(_background_tasks)
```
If a new task is added to `_background_tasks` between the snapshot and `asyncio.gather()`, it won't be cancelled. Under normal shutdown this is unlikely, but during a rapid startup-then-shutdown sequence (e.g., in tests), tasks created by `_delayed_startup_tasks` or `_open_browser` may not yet have been added.
**Fix:** Cancel and gather in a loop until the set is empty, or add a `_shutting_down` flag that prevents new task registrations.

---

### N11 [LOW] — `/ready` endpoint uses `global` keyword but variable is module-level (app.py:203)

**File:** `backend/app.py`, lines 61, 203
**Severity:** LOW
**Description:** The `global _cache_fts` declaration at line 203 is correct — it makes the function write to the module-level `_cache_fts` (line 61). But the use of `global` for a single cache variable is unnecessary; `_cache_fts` could be refactored into a closure or an attribute of the app instance. Style note only.

---

## 3. Issues Not in Scope

- **M12** (module-level `_metrics` in `agent/core.py`) — file not reviewed in this pass.
- **L3** (OpenVoice preload inconsistency) — design note, not actionable.

---

## 4. Summary

| Severity | Count | Key items |
|----------|-------|-----------|
| CRITICAL | 1 | N3 — settings hot-reload broken (regression from H5 fix) |
| HIGH | 2 | N2 — startup.py MCP task never cancelled; N3 is also HIGH but escalated |
| MEDIUM | 4 | N1, N4, N5, N6 |
| LOW | 5 | N7, N8, N9, N10, N11 |
| **New total** | **12** | |

### Previously unfixed carry-over:
- H3 partial: 7 accessors + 3 voice functions lack type hints (N6)
- H7 partial: startup.py MCP task tracked but never cleaned up (N2)
- H10/H11: Uses private `_current_session` instead of public API (N1)

### Most critical finding:
**N3: Settings hot-reload is completely broken.** The fix for H5 (switching from cached event loop to `asyncio.get_running_loop()`) failed to account for the fact that the `_reload` callback is invoked synchronously from a daemon thread (the file watcher). `get_running_loop()` raises `RuntimeError` when no event loop is running, the exception is silently swallowed, and MCP reconnection + character reloading on settings changes silently fails. This needs either (a) capturing the event loop reference at init time, or (b) using `loop.call_soon_threadsafe()` with the captured loop.

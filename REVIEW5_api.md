# REVIEW 5 — API Layer Audit

**Date:** 2026-06-24  
**Scope:** All 17 files under `backend/api/`  
**Reviewer:** Jcode Agent

---

## Summary

**2 bugs found** (both in `routes/settings.py`). All other files are clean: no dead imports, no path traversal vulnerabilities, no route conflicts, no missing routers in `app.py`, no logic bugs.

---

## BUG 1 — Missing `asyncio` import (CRASH)

**File:** `routes/settings.py`  
**Lines:** 345, 347, 349, 395 (uses `asyncio.wait_for`), 411 (uses `asyncio.TimeoutError`)  
**Severity:** HIGH — endpoint `/api/settings/test/{provider}` crashes with `NameError`

The `test_provider_connection` function calls `asyncio.wait_for()` and catches `asyncio.TimeoutError`, but **`asyncio` is never imported** in this file. The top-level imports (line 4–10) have no `import asyncio`, and the local imports inside the function (lines 320–321) only import `time` and `httpx`.

```python
# routes/settings.py line 9 — current imports:
from backend .api .deps import settings ,llm ,tts ,agent

# ... inside test_provider_connection (line 345):
resp =await asyncio.wait_for(client .get (f"{base_url }/api/tags"), timeout=15.0)
#        ^^^^^^^ NameError: name 'asyncio' is not defined
```

**Fix:** Add `import asyncio` to the local imports inside `test_provider_connection`:

```python
# Line 320, change:
    import time 
    import httpx 
# To:
    import asyncio
    import time 
    import httpx 
```

---

## BUG 2 — Missing `companion` import (SILENT FAILURE)

**File:** `routes/settings.py`  
**Lines:** 9 (import), 286 (usage of `companion()`)  
**Severity:** MEDIUM — companion settings propagation silently broken

The `batch_set_settings` function calls `companion()` at line 286 to propagate companion-related settings changes, but **`companion` is not included in the import from `backend.api.deps`** at line 9.

```python
# Line 9 — current import:
from backend .api .deps import settings ,llm ,tts ,agent
#                                                      ^ missing 'companion'

# Line 283-290 — uses companion:
    companion_keys = [k for k in pairs if k.startswith('companion.')]
    if companion_keys:
        try:
            c = companion()  # NameError: name 'companion' is not defined
            if c and hasattr(c, 'reload_settings'):
                c.reload_settings(s)
        except Exception as e:
            logger.warning(f"Failed to propagate companion settings: {e}")
```

The `except Exception` prevents a crash, but the `NameError` is caught as a warning and companion settings are never propagated. Users changing companion settings via the batch endpoint will see "ok" but the changes won't take effect until restart.

**Fix:** Add `companion` to the import on line 9:

```python
from backend .api .deps import settings ,llm ,tts ,agent ,companion
```

---

## Files Verified CLEAN (no issues)

| File | Checks Passed |
|---|---|
| `routes/settings.py` | *Except bugs 1 & 2 above* — all other imports used, validation present, output sanitization OK |
| `routes/characters.py` | All imports used. Path traversal sanitized in `get_animations`. No dead code. |
| `routes/commands.py` | All imports used. Static cache. Clean. |
| `routes/mcp.py` | All imports used. Pydantic models validate input. No issues. |
| `routes/memory.py` | All imports used. Session ID length validated (line 30). No issues. |
| `routes/push.py` | All imports used. File locking via `fcntl`. Atomic write via `tmp.replace`. No issues. |
| `routes/vault.py` | All imports used. Filename regex `^[a-zA-Z0-9_.-]+$` prevents path traversal. No issues. |
| `routes/relationship.py` | All imports used. Character ID regex `^[a-zA-Z0-9_-]+$` prevents injection. No issues. |
| `routes/tts.py` | All imports used. Text length limited to 1000 chars. No issues. |
| `routes/setup.py` | All imports used. Provider/TTS/STT validation via imported constants. No path traversal. No issues. |
| `routes/companion.py` | All imports used. Pydantic model validates input. No issues. |
| `routes/metrics.py` | All imports used. `Optional` used. No issues. |
| `ws/handler.py` | All imports used. Path traversal sanitized in `_animation_dir` (line 71), `/character` command (line 879). RateLimitError caught (line 420). WAV path W^X. No issues. |
| `ws/tts_service.py` | All imports used. `_SynthesisResult` has `__slots__`. Safe tuple unpacking (lines 127–146). No issues. |
| `deps.py` | Clean re-export of all singletons from `backend.core.deps`. No issues. |
| `server.py` | Backward-compatible re-export. No issues. |
| `telegram.py` | All imports used. Auth check via `_is_allowed`. Voice processing handled. No issues. |

**Route conflicts:** None. All routers registered in `app.py` (lines 228–240) with distinct prefixes. No overlapping paths.

**Path traversal:** All files that handle user-supplied paths sanitize input:
- `characters.py:54-57` — `..` / `/` / `\` / non-printable check
- `ws/handler.py:71` — same checks in `_animation_dir`
- `ws/handler.py:879` — same checks in `/character` command
- `vault.py:42-46` — strict filename regex
- `app.py:248-250` — `Path.resolve()` + `is_relative_to()` for character assets
- `app.py:324-326` — same for webui files

---

## Conclusion

**2 bugs found**, both in `routes/settings.py`. Both are easily fixable import additions. All other 16 files are clean with zero dead imports, zero logic bugs, zero route conflicts, and proper input validation throughout.

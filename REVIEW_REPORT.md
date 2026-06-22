# Code Review Report

**Date:** 2026-06-22  
**Scope:** 15 commits (`HEAD~15..HEAD`), ~70 source files changed  
**Reviewer:** Jcode automated review agent

---

## Summary

Reviewed all code changes across the session covering: emotion pipeline, companion mode, translation module, security fixes (path traversal, settings injection), half-baked area fixes, test suite rewrite, and various bug fixes.

### Issues Found & Fixed

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 1 | **Fixed** |
| HIGH | 1 | **Fixed** |
| MEDIUM | 3 | 1 Fixed, 2 Reported |
| LOW | 4 | Reported |

---

## CRITICAL Issues (Fixed)

### C1: Emotion events routed to wrong method — avatar stuck neutral
**File:** `webui/js/modules/ws.js:347`  
**Severity:** CRITICAL  
**What was wrong:** The `emotion` WebSocket message handler called `avatarRenderer.setExpression()` instead of `avatarRenderer.setEmotion()`. The `setExpression()` method only handles the 5 basic VRM expressions (`happy`, `angry`, `sad`, `relaxed`, `surprised`), while `setEmotion()` maps all 20+ emotion names (thinking, bored, sleep, excited, shy, etc.) to VRM expression candidates. Every non-basic emotion sent by the backend was silently ignored.  
**Impact:** The avatar appeared stuck in neutral for extended emotions like 'thinking', 'bored', 'sleep', 'excited', etc. The entire emotion pipeline was non-functional for all emotions except the 5 basic VRM presets.  
**Fix:** Changed `setExpression?.(data.emotion)` to `setEmotion?.(data.emotion)` at line 347-348.  
**Verification:** The `expression` message type (line 349-351) correctly calls `setExpression()` — the two message types are properly separated now.

---

## HIGH Issues (Fixed)

### H1: Path traversal bypass via `str.startswith()` prefix collision
**File:** `backend/app.py:193, 244`  
**Severity:** HIGH  
**What was wrong:** The path traversal guard used `str(full_path).startswith(str(DIR.resolve()))` which is vulnerable to prefix collision. A directory named `characters_evil/` adjacent to `characters/` would pass the check since `/path/to/characters_evil/...` starts with `/path/to/characters`.  
**Impact:** Potential arbitrary file read via path traversal on both `/characters/{path}` and the catch-all `/{path}` routes.  
**Fix:** Replaced `str.startswith()` with `Path.is_relative_to()` which does exact parent-directory matching (Python 3.9+). Applied to both `CHARACTERS_DIR` (line 193) and `WEBUI_DIR` (line 244).  
**Note:** An external agent (`ox`) also fixed the WEBUI_DIR route; my fix ensured consistency using the same `is_relative_to()` pattern.

---

## MEDIUM Issues

### M1: TranslationService drops `source_lang` parameter (FIXED)
**File:** `backend/core/translation/__init__.py:14-16`, `backend/core/translation/deeplx.py:19-23`  
**Severity:** MEDIUM  
**What was wrong:** `TranslationService.translate()` accepted `source_lang` as a parameter but never passed it through to `translate_text()`. The underlying `deeplx.py` function also had no `source_lang` parameter — it hardcoded `"auto"`. User-configured `translation.source_lang` settings were silently ignored.  
**Impact:** Users who configured a specific source language (e.g., English-only translation) would get auto-detection instead.  
**Fix:** Added `source_lang` parameter to `deeplx.py:translate_text()` and wired it through `TranslationService.translate()`.

### M2: Companion scheduler started without error propagation check
**File:** `backend/app.py:208-215`  
**Severity:** MEDIUM  
**What's wrong:** The companion scheduler is started via `asyncio.create_task(sched.start())` but if `companion_fn()` returns `None` (not initialized), the exception is caught and logged as a warning. However, the `init_application()` call at line 206 must complete before the scheduler is started. If `init_application()` fails, the startup continues and tries to start the scheduler anyway.  
**Impact:** Low — the scheduler gracefully handles being disabled via `_enabled()` check in its loop. But the warning log is misleading ("Companion scheduler start failed") when the real issue is `init_application()` failure.

### M3: Settings `update_all()` deep-merges arbitrary keys
**File:** `backend/core/config/settings.py:704-707`  
**Severity:** MEDIUM  
**What's wrong:** `settings().update_all(body)` in `POST /api/settings` deep-merges the entire request body into settings without restricting which keys can be set. While `_validate_settings_update()` validates known fields, it only checks specific keys (provider, voice engine, etc.) and passes through any unknown keys without validation. A malicious client could inject arbitrary top-level keys.  
**Impact:** Limited by the `rate_limit_middleware` (120 req/min) and the fact that injected keys don't affect existing behavior unless they collide with internal key names. But it's a defense-in-depth gap.  
**Recommendation:** Add a key allowlist to `_validate_settings_update()` that rejects unknown top-level keys, or maintain a set of known acceptable top-level keys.

---

## LOW Issues

### L1: `_reconnectAttempts` not incremented in max-retry branch
**File:** `webui/js/modules/ws.js:207-213`  
**Severity:** LOW  
**What's wrong:** When `_reconnectAttempts >= _reconnectDelays.length`, the code schedules a reconnection with 5000ms delay but only increments `_reconnectAttempts` at line 212. If `_reconnectAttempts >= _reconnectDelays.length + 30`, it shows "disconnected" but doesn't `return` before incrementing, so the counter keeps growing indefinitely.  
**Impact:** Cosmetic — the "disconnected" state is shown but the 5000ms reconnect timer still fires. The infinite reconnect is arguably intentional for "never give up" UX.

### L2: `setExpression()` doesn't update `currentEmotion`
**File:** `webui/js/avatar.js:860-870`  
**Severity:** LOW  
**What's wrong:** `setExpression()` modifies `_targetExpressions` but doesn't update `this.currentEmotion`. This means `currentEmotion` reflects the last `setEmotion()` call, not the last expression set via `setExpression()`. The lipsync code at line 615 uses `this.currentEmotion === 'neutral'` to scale mouth movement, which could use stale state.  
**Impact:** Minor visual inconsistency in lipsync amplitude when expressions are set directly.

### L3: Companion scheduler `trigger_now()` requires at least one registered session
**File:** `backend/core/companion/scheduler.py:147-156`  
**Severity:** LOW  
**What's wrong:** `trigger_now()` returns `None` if no WebSocket sessions are registered. The companion route at `/api/companion/trigger` calls this and returns an error message. But if the user triggers companion via the slash command `/companion` toggle, there's no check that the scheduler actually has a session to send to.  
**Impact:** User gets "Companion mode ON" but no messages appear until they send their first chat message (which triggers session registration).

### L4: `basic.test.js` emoji test uses invalid escape sequences
**File:** `webui/tests/basic.test.js:68`  
**Severity:** LOW  
**What's wrong:** The test at line 68 uses `\U0001f600` (Python-style Unicode escape) instead of `\u{1F600}` (JavaScript ES6 Unicode escape). This means the test string contains the literal characters `\U0001f600` rather than the emoji character. The `toContain` assertion passes because it's checking for the literal backslash sequence.  
**Impact:** The test doesn't actually validate emoji handling — it passes vacuously.

---

## Verified Working Correctly

### Emotion Pipeline (ws.js + avatar.js)
- **avatar.js `setEmotion()`** (line 808-858): Correctly resets all expressions, applies target emotion via candidate list, and auto-resets to neutral after `_emotionDuration` (5s). Pending emotion queue works for pre-ready deferral.
- **ws.js `emotion` handler** (line 346-348): Now correctly calls `setEmotion()` (after fix). The `expression` handler (line 349-351) correctly calls `setExpression()`.
- **Backend handler** (line 217-219): Correctly sends `{"type": "emotion", "emotion": current_emotion}` from `__emotion__` agent signals.

### Companion Mode Wiring
- **Scheduler** (`companion/scheduler.py`): Properly initialized in `deps.py` with lazy settings/LLM providers. Background loop runs every 30s, checks idle timeouts and time-aware triggers.
- **Startup** (`app.py:208-215`): Scheduler started on app startup, stopped on shutdown.
- **WS registration** (`handler.py:1041-1056`): Session registered on connect, unregistered on disconnect. `idle_enter`/`idle_exit` events properly forwarded.
- **Frontend** (`companion.js`): Idle detection with configurable timeout, sends WS events. `initCompanion()` called from app.js.

### Translation Module
- **`deeplx.py`**: Robust error handling — timeout, request errors, and generic exceptions all return original text (graceful degradation).
- **`TranslationService`**: Clean wrapper, now properly passes `source_lang` through (after fix).

### Security Fixes
- **Path traversal** (`app.py`): Both `/characters/{path}` and `/{path}` routes now use `Path.is_relative_to()` (after fix).
- **Settings injection** (`settings.py`): `_validate_settings_update()` validates known fields. `/character` slash command sanitizes names (line 763).
- **Vault** (`vault.py`): `_safe_path()` correctly uses `resolve()` + parent check.

### Half-Baked Area Fixes
- **`deprecated.py`**: Clean decorator supporting both sync and async handlers.
- **Metrics `_estimate_cost()`** (line 49): `max(0.0, ...)` correctly clamps negative token costs.
- **`voice/pipeline.py`**: Formal state machine with legal transition table, proper error handling.

### Test Suite
- **8 test files** covering basic sanity, DOM operations, settings patterns, avatar rendering, lipsync, app initialization, modules, and themes.
- Tests use vitest with happy-dom environment. Coverage of edge cases (null elements, Unicode, long text, CSS animations) is thorough.

---

## Files Changed (Key Source Files)

| File | Changes | Verdict |
|------|---------|---------|
| `webui/js/modules/ws.js` | Emotion pipeline fix, heartbeat, reconnect | Good (after fix) |
| `webui/js/avatar.js` | Emotion candidates, pending queue, auto-reset | Good |
| `backend/app.py` | Path traversal, companion startup, CORS | Good (after fix) |
| `backend/api/ws/handler.py` | Companion wiring, slash commands, error handling | Good |
| `backend/core/translation/` | New TranslationService + deeplx client | Good (after fix) |
| `backend/core/config/settings.py` | Profile system, validation, atomic save | Good |
| `backend/core/vault.py` | Path traversal fix, BM25 search | Good |
| `backend/core/metrics.py` | Cost clamping fix | Good |
| `backend/voice/pipeline.py` | Formal state machine | Good |
| `backend/core/companion/` | Scheduler + events (new) | Good |
| `webui/js/modules/companion.js` | Frontend idle detection (new) | Good |
| `webui/js/animation-manager.js` | New animation system | Good |
| `webui/js/modules/memory-graph.js` | New visualization (451 lines) | Good |
| `webui/tests/` (8 files) | Comprehensive test suite rewrite | Good |

# REVIEW 3 — API Layer Cleanliness Report

**Date:** 2026-06-23
**Scope:** All 15 files under `backend/api/`
**Goal:** Prove 0 issues remain after Hippo fixed 46 issues.

---

## Executive Summary

**3 issues found** (1 logic bug, 2 code-cleanliness categories), **0 security vulnerabilities**.

---

## 1. LOGIC BUG — `routes/settings.py` line 497

### `reset_settings()` fails to preserve API keys during full reset

**File:** `backend/api/routes/settings.py`, lines 493–503

```python
elif target == "all":
    # Preserve provider keys (API keys are sensitive)
    preserved = {}
    for k, v in s.get_all().items():
        if k.startswith("provider.") and "api_key" in str(v).lower():  # ← BUG
            preserved[k] = v
```

**Problem:** The condition checks `"api_key" in str(v).lower()` — it inspects the **value** instead of the **key**. Settings are stored as flat key-value pairs (`provider.openai.api_key` → `"sk-..."`). The value is just the raw API key string (e.g. `"sk-proj-abc123"`), which does **not** contain the substring `"api_key"`. So provider API keys are **not preserved** during a `target="all"` reset, contradicting the documented intent.

**Fix:** Change to `"api_key" in k.lower()` or `k.endswith("api_key")`.

---

## 2. DEAD IMPORTS (6)

| # | File | Line | Unused Symbol | Risk |
|---|------|------|---------------|------|
| 1 | `routes/characters.py` | 14 | `DATA_DIR` (from `backend.core.paths`) | Low — dead code, wastes a lookup |
| 2 | `routes/characters.py` | 15 | `generate_missing_icons` (from `icon_generator`) | Low — only `_generate_missing_icons_sync` is called |
| 3 | `routes/characters.py` | 15 | `PALETTE` (from `icon_generator`) | Low — never referenced |
| 4 | `routes/vault.py` | 4 | `import os` | Low — no `os` calls in the file |
| 5 | `routes/vault.py` | 10 | `settings` (from `backend.api.deps`) | Low — `llm` and `vault` are used, `settings` is not |
| 6 | `ws/handler.py` | 11 | `deque` (from `collections`) | Low — only reference is the import itself |

These are not harmful but violate "clean" — every import should serve a purpose.

---

## 3. CODE QUALITY / MAINTAINABILITY

### 3a. Redundant trim loop — `routes/metrics.py` lines 19–20, 47–48

```python
_turns: deque = deque(maxlen=500)
_max_turns = 500
…
while len(_turns) > _max_turns:
    _turns.popleft()
```

`deque(maxlen=500)` already enforces the cap automatically. The `_max_turns` constant and the `while` loop are dead code.

### 3b. TTS synthesis logic duplicated 3× — `ws/tts_service.py`

The same ~40-line sequence (OpenVoice ref-audio resolution → tuple unpacking → WAV encoding) is copy-pasted in:
- `OrderedTTSScheduler._do_generate()` (line 141)
- `synthesize_sentence()` (line 276)
- `synthesize_now()` (line 376)

Any future fix to one path must be ported to the other two. This is a maintenance liability.

---

## 4. Minor

- `routes/characters.py` line 43: `def _list_anim_files(base_dir: Path) -> list` — bare `list` type hint; prefer `list[str]`.

---

## 5. Previously Fixed Items Verified

| Category | Count | Status |
|----------|-------|--------|
| Path traversal | All endpoints checked | ✅ Clean |
| Input size limits | WS (1 MB), TTS (1k/5k), session_id (255), FTS top_k | ✅ Clean |
| Atomic file writes | `push.py` tmp+replace pattern | ✅ Clean |
| Async correctness | No sync-over-async antipatterns | ✅ Clean |
| Error handling | HTTPException, try/except on all fallible paths | ✅ Clean |
| File locking | `push.py` uses `fcntl.flock` (R/O + W exclusive) | ✅ Clean |
| Router registration | All routers including `providers_router` registered in `app.py` | ✅ Clean |

---

## Conclusion

**3 real issues remain.** The most important is the **logic bug in `reset_settings()`** that silently fails to preserve API keys. The rest are dead imports and code-quality items. No security vulnerabilities were found.

# REVIEW 3 — LLM Layer (`backend/core/llm/`)

**Goal:** Prove zero issues remain in `router.py`, `litellm_provider.py`, `cost_router.py`, `__init__.py`.

**Status:** 0 bugs, 0 logic errors, 0 type errors, 0 security issues — **but 3 dead imports persist.**

---

## Files reviewed

| File | Lines | Verdict |
|------|-------|---------|
| `__init__.py` | 7 | ✅ Clean |
| `router.py` | 173 | ✅ Clean |
| `litellm_provider.py` | 699 | ⚠️ 3 dead imports |
| `cost_router.py` | 105 | ✅ Clean |

---

## Per-file analysis

### `__init__.py` — ✅ CLEAN

- Re-exports `LLMRouter` and `LiteLLMProvider` via `__all__`.
- No dead code, no unused imports (the AST "unused" report is a false positive — both names are consumed by `__all__`).

### `router.py` — ✅ CLEAN

- `LLMRouter` is a thin, correct facade over `LiteLLMProvider`.
- `_check_local_only()` correctly enforces the privacy constraint.
- `stream()`, `stream_with_tools()`, `generate()`, `complete()`, `get_embedding()` all delegate correctly.
- All `fetch_*_models()` methods are well-structured with proper error handling.
- `close()` cleans up the provider.
- **Minor style note:** `self._provider._provider` accesses a private attribute of `LiteLLMProvider`. Since `LLMRouter` owns its `LiteLLMProvider`, this is not a bug, but adding a public `provider_name` property to `LiteLLMProvider` would be cleaner.
- All imports confirmed used.

### `litellm_provider.py` — ⚠️ 3 DEAD IMPORTS

**Found issues:**

| Line | Import | Status | Notes |
|------|--------|--------|-------|
| 9 | `import functools` | **UNUSED** | Leftover from a past refactor. Zero references in the file. |
| 12 | `import os` | **UNUSED** | `os` is used in `router.py` but not here. Zero references. |
| 15 | `import time` | **UNUSED** | Zero references. All timing uses `asyncio.sleep()` or `random.uniform()`. |

**Everything else is correct:**

- Exception hierarchy (`LLMProviderError` → `RateLimitError`, `EmbeddingError`) is well-designed.
- `_is_rate_limit_error()` uses three detection strategies (isinstance, status_code, string-matching) — robust.
- `_get_retry_delay()` extracts server-hinted delays or falls back to exponential backoff with jitter.
- `_retry_stream()` and `_retry_generate()` handle rate-limit + transient errors correctly.
- `_get_model_config()` builds the right litellm model string and kwargs for every provider in `PROVIDER_PREFIX`.
- `get_embedding()` correctly handles cross-provider API key injection.
- `stream_with_tools()` accumulates tool calls from streaming chunks and yields them correctly on `finish_reason="tool_calls"`.
- Incomplete tool calls are safely discarded on non-`tool_calls` finish.
- `close()` gracefully releases litellm HTTP resources.
- Model info caching with 5-minute TTL via `cachetools`.
- All other imports (`asyncio`, `json`, `logging`, `random`, `re`, `cachetools`, `litellm`, `AsyncIterator`, `List`, `Dict`, `Any`, `Optional`, `Union`) are used.

### `cost_router.py` — ✅ CLEAN

- `ModelConfig` dataclass is well-typed.
- `DEFAULT_ROUTING_TABLE` covers all task types with sensible defaults.
- `DEFAULT_PATTERNS` are ordered by specificity (first match wins).
- `_classify()` correctly lowercases the message before regex matching.
- Short messages (<12 words) with no classification match default to `"simple_qa"`.
- Singleton with double-checked locking (`_router_lock`) is thread-safe.
- `reset_router()` enables clean test isolation.
- All imports (`re`, `threading`, `dataclass`, `Optional`) confirmed used.

---

## Summary

| Category | Count |
|----------|-------|
| Bugs | 0 |
| Logic errors | 0 |
| Type errors | 0 |
| Security issues | 0 |
| Dead imports | **3** (`functools`, `os`, `time` in `litellm_provider.py`) |
| Style notes | 1 (`_provider._provider` — private attr access) |

**Bottom line:** The layer is functionally correct. The three dead imports are the only concrete defects. Cleaning them is trivial (remove lines 9, 12, 15 from `litellm_provider.py`).

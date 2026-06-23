# LLM Layer — Round 2 Aggressive Code Review

> Files reviewed: `router.py`, `litellm_provider.py`, `cost_router.py`, `deps.py`, `handler.py`, `basic_agent.py`, `api/deps.py`  
> Date: 2026-06-22  
> Severity legend: 🔴 CRITICAL | 🟠 HIGH | 🟡 MEDIUM | 🔵 LOW

---

## Verdict on previous 41 issues

| Status | Count | Issues |
|--------|-------|--------|
| ✅ Properly fixed | 27 | 1,2,3,4⁽ᵃᵗᵗᵉᵐᵖᵗ⁾,5,6⁽ᵃᵗᵗᵉᵐᵖᵗ⁾,8,9,10,11,13,14,17,19,20,21,22,24,25,26,27,28,30,31,36,37,40 |
| ⚠️ Partially fixed | 3 | 7, 18, 34 |
| ❌ Still broken / reintroduced | 2 | **12**, **23** |
| ❌ Never addressed | 9 | **16**, **29**, **32**, **33**, **35**, **38**, **39**, **41** |

### Key regressions introduced by previous fixes

The fixes for **issues 4, 6, and 23** introduced **new bugs that are worse than the original problems**.

---

## 🔴 CRITICAL (2 new, 1 reopened)

### C1 🔴 `handler.py:54` — `_re` is undefined (regression from issue-23 "fix")

```python
# handler.py:6
import re

# handler.py:28-59
def _normalize_error(error_text: str) -> str:
    ...
    normalized = _re.sub(r'\s+', ' ', error_text.lower()).strip()  # NameError!
```

The "fix" for issue 23 removed the `import re as _re` from inside the function body (which was indeed redundant) **but never changed `_re` to `re` at the usage site**. The module-level import is `import re`, not `import re as _re`. This will raise **`NameError: name '_re' is not defined`** on every call to `_normalize_error()` that reaches line 54 (which is every call — the whitespace collapse always runs).

**Fix:** `s/_re/re/` on line 54.

---

### C2 🔴 `litellm_provider.py:356-358,368-370,527-529,539-540` — Buffer replay on retry causes TRIPLE token duplication (regression from issues 4/6 "fixes")

**The premise of the "fix" is wrong.** Streaming APIs are stateless — a retry starts from the beginning of the response. Buffering already-yielded tokens and re-emitting them on retry **adds more duplication, not less**.

Scenario (3 retries):

| Step | Output to caller |
|------|-----------------|
| Attempt 1, tokens 1‑3 | `yield t1, t2, t3` → caller sees `t1, t2, t3` |
| Attempt 1 fails | buffer = `[t1, t2, t3]` |
| **Buffer replay** | **`yield t1, t2, t3` again** → caller sees `t1,t2,t3,t1,t2,t3` |
| Attempt 2 starts fresh | `yield t1, t2, t3, t4, t5` → caller sees `t1,t2,t3,t1,t2,t3,t1,t2,t3,t4,t5` |

**Result: TRIPLE duplication** instead of the original double duplication. Without the buffer replay, the caller would see `t1,t2,t3,t1,t2,t3,t4,t5` (double).

The same flawed pattern exists in both `_retry_stream` (lines 357‑358, 369‑370) and `stream_with_tools` (lines 528‑529, 539‑540).

**Fix:** Remove the buffer-replay-on-retry entirely. Accept that stateless streaming retries inherently cause duplication, and document the limitation. For a proper solution, consider a **two-phase streaming** approach (buffer until the caller acknowledges) or **mid-stream failover** via connection pooling.

---

## 🟠 HIGH (2 reopened, 1 new)

### H1 🟠 `handler.py:398` — `RateLimitError` / `LLMProviderError` still caught generically (issue 12 unfixed)

```python
except Exception as e:
    logger.error(f"Agent error in loop: {e}")
    # ... sends generic error to frontend
```

`RateLimitError` (from `litellm_provider.py:35`) and `LLMProviderError` (line 31) are custom exceptions but they are never caught by type. When a `RateLimitError` propagates here, the retry-after information and rate-limit semantics are lost. The error goes through `_normalize_error()` which matches on text substrings — fragile and loses structured data.

**Fix:** Add `except RateLimitError:` before `except Exception:` with a user-friendly "rate limited — please wait" message that includes the retry-after time.

---

### H2 🟠 `handler.py:366-371` — Token count still uses word splitting (issue 16 unfixed)

```python
record_turn(
    token_in=len(text.split()),
    token_out=_tok_out,        # = len(full_response.split())
    ...
)
```

Word count ≠ token count. For English, ratio is ~1.3 tokens/word; for CJK languages it can be 2‑3× higher. Metrics are systematically inaccurate.

**Fix:** Use `litellm.token_counter()` (or a local tokenizer such as `tiktoken`) for accurate counts.

---

### H3 🟠 `litellm_provider.py:65` — `gcp` prefix `vertex_ai` but `EMBEDDING_MODEL_DEFAULTS["gcp"]` uses `vertex_ai/` — inconsistent with the `gcp` → `"vertex_ai"` prefix in other providers

Not a bug per se (both use the same string), but the redundancy between `PROVIDER_PREFIX["gcp"] = "vertex_ai"` and `EMBEDDING_MODEL_DEFAULTS["gcp"] = "vertex_ai/textembedding-gecko"` means the embedding default hardcodes the prefix while other embedding defaults follow the `{prefix}/{model}` pattern inconsistently.

---

## 🟡 MEDIUM (7 previously unfixed, 2 new)

### M1 🟡 `litellm_provider.py:87-90` — Retry constants are not configurable (issue 32 unfixed)

```python
_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 5.0
_RATE_LIMIT_MAX_RETRIES_ON_5XX = 2
_RATE_LIMIT_BASE_DELAY_5XX = 1.0
```

These are module-level constants with no way to override via settings. Users on aggressive rate-limit tiers cannot customize retry behavior.

**Fix:** Read from `settings.get("llm.rate_limit_max_retries", 3)` etc. with fallback to defaults.

---

### M2 🟡 `litellm_provider.py:125-131` — `_is_rate_limit_error` is fragile string matching (issue 41 unfixed)

```python
def _is_rate_limit_error(exc: Exception) -> bool:
    exc_type = type(exc).__name__
    if "RateLimitError" in exc_type:
        return True
    msg = str(exc).lower()
    return "rate limit" in msg or "429" in msg or "rate_limit_exceeded" in msg
```

- Relies on class name containing "RateLimitError" — fragile across litellm versions.
- "429" could false-positive on other 4xx errors or model version strings.
- `_get_retry_delay()` uses regex `r"try again in ([\d.]+)s"` which only matches one specific error format.

**Fix:** Use `litellm.RateLimitError` exception type when available, or check the HTTP status code from `exc.response.status_code` if the exception carries it.

---

### M3 🟡 `handler.py:794-810` — `/resume` has no timeout (issue 29 unfixed)

```python
sid = memory().get_current_session()
turns = memory().get_session_turns(sid, turns=5)
```

If the session is large or storage is slow, this blocks the event loop with no timeout.

**Fix:** Wrap in `asyncio.wait_for(..., timeout=5.0)` or offload to a thread executor.

---

### M4 🟡 `litellm_provider.py:116-118,208` — `OPENAI_COMPAT_PROVIDERS` defined but never referenced; hardcoded tuple duplicates the set

```python
# line 116-118 — defined
OPENAI_COMPAT_PROVIDERS = {
    "opencode", "llamacpp", "koboldai", "siliconflow",
}

# line 208 — hardcoded tuple ignoring the set
if provider in ("llamacpp", "koboldai", "siliconflow", "opencode"):
    model = model_name
```

**Two problems:**
1. `OPENAI_COMPAT_PROVIDERS` is never referenced outside its definition. Dead code.
2. The hardcoded tuple at line 208 duplicates the set. If someone adds a new provider to `OPENAI_COMPAT_PROVIDERS` and forgets to update line 208, the new provider won't get the correct model prefix.

**Fix:** Use `OPENAI_COMPAT_PROVIDERS` directly: `if provider in OPENAI_COMPAT_PROVIDERS:`.

---

### M5 🟡 `router.py:15` — `OPENAI_COMPAT_PROVIDERS` imported but unused

```python
from .litellm_provider import LiteLLMProvider, OPENAI_COMPAT_PROVIDERS
```

`OPENAI_COMPAT_PROVIDERS` is imported in `router.py` but never referenced anywhere in that file.

**Fix:** Remove the unused import.

---

### M6 🟡 `litellm_provider.py:439` — `stream_with_tools` return type is unparameterized `AsyncIterator`

```python
async def stream_with_tools(
    self, messages: list, tools: List[Dict[str, Any]], temperature: float = None,
) -> AsyncIterator:
```

Compare with `router.py:78` which correctly has:
```python
) -> AsyncIterator[Union[str, Dict[str, Any]]]:
```

**Fix:** Add `[Union[str, Dict[str, Any]]]` type parameter.

---

### M7 🟡 `handler.py:1034-1036` — `cleanup()` iterates `pending_tasks` without copy during cancellation

```python
for t in self.pending_tasks:           # no copy!
    if not t.done():
        t.cancel()
# ...
await asyncio.gather(*self.pending_tasks, ...)
```

`t.cancel()` causes `_on_task_done` callbacks to fire (asynchronously), which call `self.pending_tasks.remove(t)`. The list is mutated during iteration — in CPython this can skip items. Also, `gather(*self.pending_tasks)` uses whatever remains in the list, which may be a different set than what was iterated.

**Fix:** `for t in list(self.pending_tasks):` (create a shallow copy before iteration).

---

### M8 🟡 `handler.py:75` — Redundant `import os` inside `_resolve_animation`

```python
def _resolve_animation(text: str, char_id: str) -> str | None:
    import os    # redundant — os already imported at module level (line 8)
```

**Fix:** Remove the redundant import.

---

### M9 🟡 `cost_router.py` — Still dead code (issue 18 partially fixed)

The TOCTOU race in `route_llm_call()` was fixed with a lock (line 89, 95‑98). However:
- `LLMCostRouter`, `route_llm_call`, and `reset_router` are exported from `__init__.py` but **never called anywhere** in the application.
- No integration point between `cost_router.py` and `litellm_provider.py` or `router.py`.
- The `_classify()` method does keyword-based routing but this code path is exercised by zero callers.

**Fix:** Either wire it into the actual routing path (e.g., `LLMRouter.stream()` could optionally call `route_llm_call()` for model selection), or remove the exports and mark the module for deletion.

---

## 🔵 LOW (5 previously unfixed, 2 new)

### L1 🔵 `litellm_provider.py:199-200` — Redundant empty dict check (issue 35 unfixed)

```python
if not cfg:
    cfg = {}
```

If `cfg` is falsy (empty `{}`), it's replaced with another empty `{}`. Harmless but confusing.

**Fix:** `cfg = cfg or {}` (already falsy-handled by the `if not cfg` guard — just remove the redundant assignment).

---

### L2 🔵 `litellm_provider.py:20` — Inconsistent aliases (issue 33 unfixed)

```python
from litellm import acompletion as _litellm_acompletion, aembedding as _litellm_aembedding
```

`_litellm_acompletion` vs `_litellm_aembedding` — one abbreviates, the other doesn't. Cosmetic.

---

### L3 🔵 `handler.py:137-138,1103-1104` — `client_caps` and `client_platform` stored but unused (issues 38 & 39 unfixed)

```python
self.client_caps: dict = {}
self.client_platform: str = "web"
...
self.client_caps = caps
self.client_platform = platform
```

Stored in `handle_client_hello()` but never read for any decision logic.

**Fix:** Remove the fields or use them for feature-flagging (e.g., conditional TTS based on platform).

---

### L4 🔵 `litellm_provider.py:468,491` — Redundant conditional on `chunk.choices`

```python
if not chunk.choices:       # line 468 — continues if falsy
    continue
# ...
finish = chunk.choices[0].finish_reason if chunk.choices else None  # line 491 — always truthy here
```

After line 468, `chunk.choices` is guaranteed truthy. The `else None` is dead code.

---

### L5 🔵 `litellm_provider.py:64` — `"aws": "bedrock"` but `EMBEDDING_MODEL_DEFAULTS["aws"]` is `"bedrock/amazon.titan-embed-text-v2:0"` — fine, but `"gcp": "vertex_ai"` while `EMBEDDING_MODEL_DEFAULTS["gcp"]` is also `"vertex_ai/textembedding-gecko"`. The embedding defaults already include the prefix, which means the `prefix = PROVIDER_PREFIX.get(provider, provider)` logic is bypassed for embeddings. This is correct but not obvious.

No fix needed — just a documentation clarity issue.

---

### L6 🔵 `litellm_provider.py:307-322` — `_is_transient_error` string-checks for transport errors

```python
if any(t in msg for t in ("connection reset", "connection refused", "connection aborted",
                           "dns", "timeout", "timed out", "eof", "broken pipe",
                           "cannot connect", "no route to host")):
```

The substring `"dns"` could match model names containing "dns" (unlikely) or error messages about "dns" in a non-transient context (extremely unlikely). Also, `"timeout"` could match `"timeout"` in any context. The `isinstance` check for `(ConnectionError, TimeoutError)` is the robust part.

**Fix:** Prefer `isinstance` checks over string matching where possible. Move the strict string checks after the type check.

---

### L7 🔵 `router.py:31-32` — Comment references removed concept

```python
# Providers that use an OpenAI-compatible API format
# (kept for reference but no longer needs special routing — LiteLLM handles it)
```

The comment says "kept for reference" but the actual set (`OPENAI_COMPAT`) was removed from this file. The comment is orphaned.

**Fix:** Remove the comment block.

---

## Summary

| Severity | Previous | 🔴 New regressions | Previously unfixed | New findings | Total remaining |
|----------|----------|---------------------|-------------------|--------------|-----------------|
| 🔴 CRITICAL | 6 | **2** (C1, C2) | 0 | 0 | **2** |
| 🟠 HIGH | 12 | 0 | 2 (H1, H2) | 1 (H3) | **3** |
| 🟡 MEDIUM | 14 | 0 | 4 (M1‑M4) | 5 (M5‑M9) | **9** |
| 🔵 LOW | 9 | 0 | 3 (L1‑L3) | 4 (L4‑L7) | **7** |
| **Total** | **41** | **2** | **9** | **10** | **21** |

### Must-fix before shipping (🔴)

1. **`handler.py:54`** — `_re` NameError (1‑char fix: `_re` → `re`)
2. **`litellm_provider.py:356-358,368-370,527-529,539-540`** — Remove counterproductive buffer-replay-on-retry that causes triple token duplication

### Top 5 impactful additional fixes

1. **`handler.py:366-371`** — Accurate token counting (fixes systematically wrong metrics)
2. **`handler.py:398`** — Catch `RateLimitError` by type for user-friendly messages
3. **`litellm_provider.py:116-118,208`** — Use `OPENAI_COMPAT_PROVIDERS` set instead of duplicated hardcoded tuple
4. **`handler.py:1034-1036`** — Copy `pending_tasks` before cancellation iteration
5. **`litellm_provider.py:87-90`** — Make retry constants configurable via settings

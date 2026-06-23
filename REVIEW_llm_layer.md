# LLM Layer — Aggressive Code Review

> Files reviewed: `router.py`, `litellm_provider.py`, `cost_router.py`, `deps.py`, `handler.py`, `basic_agent.py`  
> Date: 2026-06-22  
> Severity legend: 🔴 CRITICAL | 🟠 HIGH | 🟡 MEDIUM | 🔵 LOW

---

## 1. 🔴 `basic_agent.py:154` — `generate()` called with unsupported `tools` keyword argument

```python
return await self.llm.generate(messages, tools=schema)
```

`LLMRouter.generate()` (router.py:90) accepts only `(messages, temperature=None)`. It **does not accept** a `tools` keyword. `LiteLLMProvider.generate()` (litellm_provider.py:453) also has no `tools` parameter. This will **raise `TypeError`** at runtime if `get_response()` is ever called.

**Fix:** Either add `tools` support to `generate()` on both `LLMRouter` and `LiteLLMProvider`, or remove the `tools=schema` argument. Non-streaming tool calling is supported by litellm via `acompletion(..., tools=tools)` — just not wired up.

---

## 2. 🔴 `basic_agent.py:46,76` — Images passed via `handle_user_input()` are silently dropped

```python
# basic_agent.py line 132-141
async def handle_user_input(self, text, images=None, relationship_context=""):
    ctx = {
        "images": images or [],   # stored in context
    }
    async for chunk in self.run(text, ctx):
        ...

# basic_agent.py line 46 (inside run)
messages = await self._build_messages(user_message, None, relationship_context)
#                                                        ^^^^ hardcoded None
```

The context dict carries `images` but `_build_messages()` is called with `images=None` unconditionally. The images key in context is never read. Multimodal input is completely broken in `BasicAgent`.

**Fix:** Pass `context.get("images")` to `_build_messages()`.

---

## 3. 🔴 `litellm_provider.py:146-152` — `_get_cached_model_info` claims TTL but `lru_cache` has no TTL

```python
@functools.lru_cache(maxsize=32)
def _get_cached_model_info(model_name: str) -> dict:
    """Cached wrapper around litellm.get_model_info()."""
```

Docstring says "TTL: 5 minutes" but `lru_cache` stores results indefinitely with no expiry. Stale model info is served forever until the process restarts or the cache fills (maxsize=32).

**Fix:** Use `cachetools.TTLCache` with a 5-minute TTL, or document that TTL is not enforced.

---

## 4. 🔴 `litellm_provider.py:296-299` — Partial-stream retry causes token duplication

```python
async for chunk in response:
    delta = chunk.choices[0].delta if chunk.choices else None
    if delta and delta.content:
        yield delta.content
return
```

If the stream fails partway through (connection drop, server error), the `except` block catches the exception. On retry, the **new stream starts from the beginning** of the response, but the caller has already received the initial tokens. This means the frontend gets duplicated tokens (the beginning of the response twice).

The same issue exists in `stream_with_tools()` (lines 373-451) and `_retry_generate()` (but generate is non-streaming so it's fine).

**Fix (complex):** Buffer yielded tokens so they can be replayed on retry, or skip retry for mid-stream failures. For `_retry_generate`, the retry logic is correct since the entire response is consumed before returning.

---

## 5. 🔴 `handler.py:214-218` — Coroutine handling is broken

```python
it = agent().handle_user_input(text, images=images, relationship_context=rel_context)
if asyncio.iscoroutine(it):
    logger.error(f"CRITICAL: agent().handle_user_input returned a coroutine...")
    it = await it    # <-- now it's the return value, not an async generator
async for item in it:  # <-- TypeError if it was actually a coroutine
```

If `it` is a coroutine and we `await it`, the result is whatever the function returned — which is `None` (async generators return `AsyncGenerator`, not a coroutine). `async for` on `None` raises `TypeError`. The error path is itself broken.

**Fix:** Remove this check; the method signature guarantees an async generator. If defensive coding is desired, use `types.AsyncGeneratorType` check instead.

---

## 6. 🔴 `litellm_provider.py:373-451` — `stream_with_tools` has no retry for mid-stream failures

The retry loop wraps both the `acompletion()` call and the `async for chunk in response:` loop. If the stream fails mid-way, the retry restarts from scratch, yielding duplicated content (same as issue #4). Additionally, `pending_tool_calls` resets on each retry.

**Fix:** Extract the retry wrapper to only wrap the initial `acompletion()` call, or implement replay buffering.

---

## 7. 🟠 `router.py:31` / `litellm_provider.py:112-114` — `OPENAI_COMPAT` is dead code

```python
# router.py:31
OPENAI_COMPAT = OPENAI_COMPAT_PROVIDERS
```

`OPENAI_COMPAT` is assigned in `LLMRouter` but **never referenced** anywhere in the codebase. The `OPENAI_COMPAT_PROVIDERS` set (`opencode`, `llamacpp`, `koboldai`, `siliconflow`) has no functional effect.

---

## 8. 🟠 `litellm_provider.py:196-202` — `opencode` provider uses wrong model prefix

```python
if provider in ("llamacpp", "koboldai", "siliconflow"):
    model = model_name
elif provider == "ollama":
    model = f"ollama/{model_name}"
else:
    model = f"{prefix}/{model_name}" if model_name else prefix
```

`opencode` maps to prefix `"openai"` (line 62: `"opencode": "openai"`). Since it's not in the special-case list, the model string becomes `openai/{model_name}`. But OpenCode is an OpenAI-compatible API, not OpenAI itself. Many litellm configurations expect `opencode/{model_name}` or just the raw model name. This likely causes model-not-found errors.

**Fix:** Add `"opencode"` to the special-case list (like siliconflow) so the model name is passed as-is, or map to `opencode/` prefix.

---

## 9. 🟠 `litellm_provider.py:68-71` — `TOOL_CAPABLE` missing providers

```python
TOOL_CAPABLE = {
    "gemini", "openrouter", "groq", "deepseek", "mistral", "together",
    "chatgpt", "azure-openai", "alibaba", "huggingface", "zai", "siliconflow",
    "claude", "aws", "gcp",
}
```

Missing: `ollama` (newer versions support tools), `opencode` (if it supports tools), `llamacpp`, `koboldai`. These providers silently fall back to text-only streaming when they could support tool calling.

---

## 10. 🟠 `litellm_provider.py:81` — `OUTPUT_LIMITS["groq"] = 512` is too restrictive

```python
OUTPUT_LIMITS = {
    "groq": 512,
    ...
}
```

Many GROQ models (e.g., `llama-3.3-70b-versatile`) support 8K+ output tokens. The 512-token cap will silently truncate all GROQ responses. When `get_max_output_tokens()` fails to get model info, it falls through to this hard limit.

**Fix:** Increase to 8192 or remove the GROQ-specific limit for models known to support larger outputs (or rely on model_info lookup which is more accurate).

---

## 11. 🟠 `litellm_provider.py:210-213` — Provider-specific API key kwargs are incomplete

```python
if provider == "gemini":
    kwargs["gemini_api_key"] = api_key
elif provider == "chatgpt":
    kwargs["openai_api_key"] = api_key
```

Only Gemini and ChatGPT get provider-specific key kwargs. Other providers that may need them:
- `mistral` → `mistral_api_key`
- `deepseek` → `deepseek_api_key`
- `groq` → `groq_api_key`
- `together` → `together_ai_api_key`
- `openrouter` → `openrouter_api_key`

litellm may auto-detect from the generic `api_key` kwarg, but explicit keys are more reliable.

---

## 12. 🟠 `litellm_provider.py:312,339,450` — `RateLimitError` and `LLMProviderError` are never caught upstream

The custom exceptions `RateLimitError` and `LLMProviderError` are raised by the LLM layer but:
- `basic_agent.py` catches generic `Exception` (line 119), not these specific types
- `handler.py` catches generic `Exception` (line 393) and `ServiceError` (line 383)
- There is also `ProviderRateLimitError` in `backend/core/errors.py` (line 120) which is **never used** by the LLM layer

The custom exception hierarchy exists but is effectively dead — no caller distinguishes between rate limits, provider errors, and other failures.

**Fix:** Catch `RateLimitError` upstream in `handler.py` to provide user-friendly rate-limit messages. Integrate with `backend/core/errors.py` `ProviderRateLimitError` so the error handling framework tracks rate limits properly.

---

## 13. 🟠 `litellm_provider.py:502-513` — Cross-provider embedding API key injection has wrong provider name comparison

```python
embed_provider = embed_model.split("/", 1)[0]  # e.g., "openai" from "openai/text-embedding-3-small"
if embed_provider != self._provider and self._settings:
    embed_provider_cfg = self._settings.get(f"provider.{embed_provider}", {})
```

If `self._provider` is `"chatgpt"` (internal name) but the embedding model uses `"openai"` prefix, the comparison `embed_provider != self._provider` is `"openai" != "chatgpt"` which is `True`. So it tries `settings.get("provider.openai", {})` which likely doesn't exist — the user configured `provider.chatgpt`, not `provider.openai`.

Same issue applies to `siliconflow` → `openai`, `azure-openai` → `azure`, `claude` → `anthropic`.

**Fix:** Normalize `self._provider` through `PROVIDER_PREFIX` before comparison, or map both sides to the same canonical name.

---

## 14. 🟠 `litellm_provider.py:487-493` — Ollama embedding model fallback is overly aggressive

```python
ollama_model = self._settings.get("provider.ollama.model", ollama_model)
if "embed" not in ollama_model.lower():
    ollama_model = "nomic-embed-text"
```

If the user configures a custom Ollama model whose name doesn't contain "embed" (e.g., `"mistral"`, `"llama3"`), it gets overridden to `nomic-embed-text` even if the configured model supports embeddings. The string `"embed"` is an unreliable heuristic.

**Fix:** Use a dedicated `provider.ollama.embedding_model` setting instead of keyword-guessing.

---

## 15. 🟠 `basic_agent.py:265` — `None.mcp_client.has_servers()` crashes

```python
async def _get_tool_schema(self) -> Optional[List[Dict]]:
    if self.mcp_client and self.mcp_client.has_servers():
```

`self.mcp_client` can be `None` (set via `__init__` from `resolved_mcp` which evaluates to `None` if both `mcp_client` and `config` lack it). The guard `if self.mcp_client` correctly prevents the `None.has_servers()` crash. **This is safe**, but fragile — any future refactoring that forgets the guard will crash.

---

## 16. 🟠 `handler.py:358-369` — Token count is estimated with word splitting

```python
record_turn(
    token_in=len(text.split()),
    token_out=_tok_out,   # len(full_response.split())
    ...
)
```

Word count != token count. For English, the ratio is ~1.3 tokens/word; for CJK languages it can be 2-3x higher. Metrics are systematically inaccurate.

**Fix:** Use a proper tokenizer or litellm's `token_counter()` for accurate counts.

---

## 17. 🟠 `litellm_provider.py:284-340` — No retry for transient network errors

The retry logic only retries on **rate limit** errors (HTTP 429). Other transient errors (connection reset, DNS failure, HTTP 503, HTTP 502) are immediately escalated to `LLMProviderError` with no retry.

**Fix:** Add retry for 5xx errors, connection timeouts, and `httpx` transport errors.

---

## 18. 🟠 `cost_router.py` — Dead code, never integrated

- `LLMCostRouter`, `route_llm_call()`, and `reset_router()` are exported from `__init__.py` but **never called** anywhere in the application.
- The `_classify()` method does keyword-based routing but there's no integration point between `cost_router.py` and `litellm_provider.py` or `router.py`.
- The singleton `_router` at module level (cost_router.py:87) has a **TOCTOU race** in `route_llm_call()` (line 93-94):

```python
if _router is None:
    _router = LLMCostRouter()
```

Two concurrent calls can both see `None` and both create router instances. One assignment wins, the other is garbage.

**Fix:** Either wire it into the actual routing path or remove it. Add a lock for thread safety if kept.

---

## 19. 🟡 `litellm_provider.py:326` — `choices[0]` IndexError risk in `_retry_generate`

```python
return response.choices[0].message.content or ""
```

If the API returns a response with **empty choices** (e.g., content-filtered), `response.choices[0]` will raise `IndexError`. The `try/except` around this catches `Exception`, so it would be caught and retried or raised as `LLMProviderError`. But the retry is only for rate-limit errors — an empty choices response would immediately raise with a confusing error.

**Fix:** Add a guard: `if not response.choices: raise LLMProviderError("Empty response choices")`.

---

## 20. 🟡 `litellm_provider.py:404-418,421-435` — Pending tool calls with no `finish_reason="tool_calls"` could yield malformed tool calls

The code at lines 421-435 yields any remaining pending tool calls even if the stream ended with `finish_reason="stop"` (not "tool_calls"). If the LLM started emitting a tool call but then stopped (e.g., hit max_tokens), partially-constructed tool calls with empty names or arguments would be yielded to the caller.

**Fix:** Only yield pending tool calls if `finish_reason == "tool_calls"`.

---

## 21. 🟡 `litellm_provider.py:250,267` — `_get_cached_model_info` exceptions silently return `{}`

```python
except Exception:
    return {}
```

Any exception from `litellm.get_model_info()` (including network errors, invalid model name, malformed response) returns an empty dict. The error is completely silent — no `logger.warning` or `logger.error`.

**Fix:** Log a warning on failure.

---

## 22. 🟡 `litellm_provider.py:231-236` — `_get_temperature` crashes on non-numeric override

```python
def _get_temperature(self, override: float = None) -> float:
    if override is not None:
        return float(override)
```

If `override` is a string (e.g., `"auto"` or a user input string), `float(override)` will raise `ValueError`.

**Fix:** Validate input with try/except, or pass typed values from callers.

---

## 23. 🟡 `handler.py:28,56` — Redundant `import re` inside `_normalize_error`

```python
def _normalize_error(error_text: str) -> str:
    import re as _re   # re already imported at line 6
```

**Fix:** Remove the redundant import.

---

## 24. 🟡 `deps.py:115` — Silent fallback when AgentFactory.create() fails

```python
try:
    _shared["agent"] = AgentFactory.create(...)
except Exception:
    _shared["agent"] = Agent(mcp_client=mcp_client, llm=..., ...)
```

If `AgentFactory.create()` fails, the fallback `Agent(...)` call **omits the `tools={}` dict** that was passed to the factory. The error is completely silent (no `logger.exception` or `logger.warning`). Any misconfiguration in agent creation is hidden.

---

## 25. 🟡 `deps.py:147-166` — `get_shared()` lock contention on every access

Each accessor function (`llm()`, `memory()`, etc.) calls `get_shared()` which acquires `_init_lock`. While the lock is released quickly for already-initialized singletons, this is still a global bottleneck on a hot path (every WebSocket message processing calls `agent()` once, `relationship()` once, `settings()` multiple times).

**Fix:** Use `_shared` dict directly after initialization, or use `asyncio.Lock` with `async with`.

---

## 26. 🟡 `deps.py:169-181` — Voice pipeline registry is not thread-safe

```python
_voice_pipeline_registry: dict = {}
def set_voice_pipeline(pipeline):
    _voice_pipeline_registry["pipeline"] = pipeline
```

Reads and writes to this global dict from the WS handler (potentially multiple concurrent connections) without any synchronization.

**Fix:** Use `threading.Lock` around access.

---

## 27. 🟡 `handler.py:99-117` — `_OrchestratorAgentAdapter.handle_user_input` re-fetches agent on every call

```python
async def handle_user_input(self, inp: str) -> AsyncGenerator[str, None]:
    app_agent = agent()   # calls get_shared() which acquires lock
    async for chunk in app_agent.handle_user_input(inp):
```

For every orchestrator step, the lock is acquired again. The agent singleton doesn't change, so this is wasteful.

**Fix:** Cache the agent reference at adapter construction time.

---

## 28. 🟡 `handler.py:300-323` — `CorrectionStore` and `PreferenceLearner` objects created on every response

```python
cs = CorrectionStore(data_dir=str(DATA_DIR))
...
pl = PreferenceLearner(data_dir=str(DATA_DIR))
pl.observe_interaction(text, full_response)
```

These objects are created fresh every turn. If their constructors or `__init__` do I/O (e.g., loading data files), this is wasteful. Worse, any exception is silently swallowed at `DEBUG` level.

**Fix:** Cache instances, or lazy-init once.

---

## 29. 🟡 `handler.py:789-804` — `/resume` command calls `memory().get_session_turns()` which is potentially slow

No timeout on the memory query. If the session is large or storage is slow, the user gets no feedback.

---

## 30. 🟡 `router.py:103-104` — `get_embedding()` does not check `_check_local_only()`

```python
async def get_embedding(self, text: str) -> List[float]:
    return await self._provider.get_embedding(text)
```

All other public methods (`stream`, `stream_with_tools`, `generate`, `complete`) call `_check_local_only()`. Embedding bypasses this privacy check, potentially leaking data to external providers even in local-only mode.

**Fix:** Add `self._check_local_only()` call.

---

## 31. 🟡 `litellm_provider.py:525-527` — `close()` is a no-op

```python
async def close(self):
    """No-op — LiteLLM manages its own HTTP clients."""
    pass
```

LiteLLM's `acompletion()` uses `httpx.AsyncClient` under the hood. While LiteLLM does manage its own client lifecycle, calling `close()` should ideally trigger `await litellm.aclose()` (available in recent versions) to properly release connections and avoid warnings on shutdown.

---

## 32. 🟡 `litellm_provider.py:85-86` — Retry constants are not configurable

```python
_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 5.0
```

These are module-level constants with no way to override via settings. Users on aggressive rate-limit tiers might need more retries or longer delays.

**Fix:** Read from settings with fallback to defaults.

---

## 33. 🔵 `litellm_provider.py:293,324` — Uses `_litellm_acompletion` alias but also calls `_litellm_aembedding` — naming is inconsistent

```python
from litellm import acompletion as _litellm_acompletion, aembedding as _litellm_aembedding
# ...
response = await _litellm_acompletion(...)
response = await _litellm_aembedding(...)
```

Minor: `_litellm_acompletion` and `_litellm_aembedding` use different abbreviation styles. Not a bug, but inconsistent.

---

## 34. 🔵 `litellm_provider.py:45-65` — `PROVIDER_PREFIX` maps both `"claude"` and `"anthropic"` paths

`"claude": "anthropic"` maps claude provider to anthropic prefix. But the `model = f"{prefix}/{model_name}"` logic would produce `anthropic/claude-sonnet-4-6`. This is correct for litellm. But the mapping doesn't include a reverse mapping for `"anthropic"` as a provider name, meaning if someone sets `provider.active = "anthropic"`, it would look up `PROVIDER_PREFIX.get("anthropic", "anthropic")` = `"anthropic"`, produce `anthropic/model`, which is also valid. Minor documentation clarity issue.

---

## 35. 🔵 `litellm_provider.py:188-189` — Redundant empty dict check

```python
if not cfg:
    cfg = {}
```

If `cfg` is an empty dict (falsy), it's replaced with another empty dict. This is harmless but confusing.

**Fix:** Simplify to `cfg = cfg or {}`.

---

## 36. 🔵 `router.py:76` — Return type `AsyncIterator` (unparameterized)

```python
async def stream_with_tools(...) -> AsyncIterator:
```

Compared to `stream()` which returns `AsyncIterator[str]`. The unparameterized return type loses type information.

**Fix:** `AsyncIterator[Union[str, Dict[str, Any]]]`.

---

## 37. 🔵 `router.py:108` — Lazy `import httpx` inside method

Minor style issue. `httpx` is imported inside `fetch_ollama_models()` and `fetch_opencode_models()` instead of at module level.

---

## 38. 🔵 `handler.py:133` — `client_platform` is assigned but never read

```python
self.client_platform: str = "web"
```

Set in `handle_client_hello()` and initialization, but never used in any decision logic.

---

## 39. 🔵 `handler.py:132` — `client_caps` stored but unused

Capabilities from the client are stored in `self.client_caps` but never checked or used for conditional behavior.

---

## 40. 🔵 `handler.py:359-367` — Hardcoded metric key `"llm.model"` may not match actual model name

```python
record_turn(
    model=settings().get("llm.model", ""),
)
```

The setting key is `"llm.model"` but the model name is stored under `"provider.{provider_name}.model"`. This will likely return an empty string, making metrics useless for model attribution.

**Fix:** Use `llm().get_model_name()` instead.

---

## 41. 🔵 `litellm_provider.py:121-139` — Rate-limit detection is fragile string matching

```python
def _is_rate_limit_error(exc: Exception) -> bool:
    exc_type = type(exc).__name__
    if "RateLimitError" in exc_type:
        return True
    msg = str(exc).lower()
    return "rate limit" in msg or "429" in msg or "rate_limit_exceeded" in msg
```

- Relies on class name containing "RateLimitError" — fragile across litellm versions
- Message matching for "429" could false-match on other 4xx errors or model names
- `_get_retry_delay()` uses regex `r"try again in ([\d.]+)s"` which only matches one specific error format

**Fix:** Use `litellm.RateLimitError` exception type check (if available in the installed version). For retry-after, try `response.headers.get("retry-after")` or use `litellm`'s built-in retry mechanism.

---

## Summary

| Severity | Count |
|----------|-------|
| 🔴 CRITICAL | 6 |
| 🟠 HIGH | 12 |
| 🟡 MEDIUM | 14 |
| 🔵 LOW | 9 |
| **Total** | **41** |

### Top 5 most impactful fixes:

1. **`basic_agent.py:154`** — `generate()` called with unsupported `tools` kwarg will crash at runtime
2. **`basic_agent.py:46`** — Images silently dropped, multimodal input completely broken for `BasicAgent`
3. **`litellm_provider.py:296-299`** — Stream retry causes token duplication on mid-stream failures
4. **`litellm_provider.py:196-202`** — `opencode` provider uses wrong model prefix
5. **`handler.py:214-218`** — Coroutine fallback path is itself broken

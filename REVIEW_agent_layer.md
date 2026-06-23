# Aggressive Code Review — Agent Layer

**Review Date:** 2026-06-22  
**Scope:** `backend/core/agent/` + `deps.py`, `api/ws/handler.py`, `api/routes/settings.py`  
**Method:** Line-by-line reading of every source file in the agent layer and its call sites.

---

## Executive Summary

The agent layer has two parallel hierarchies (legacy `Agent` in `core.py` and new-style agents in `base.py`/`basic_agent.py`/etc.) that speak different protocols to the WebSocket handler. New-style agents do **not** emit the `(signal_type, value)` tuples that the handler expects, breaking error reporting, tool-call announcements, emotion display, image support, and the overall frontend contract. On top of that, there is widespread error swallowing, a path traversal vulnerability, a missing `mcp_client` pipe through `ReflectiveAgent`, inconsistent constructor patterns, and dead code.

**Severity distribution: 1 critical, 7 high, 8 medium, 4 low** (20 findings total).

---

## CRITICAL

### C1. New-style agents break the handler signal protocol

**Files:** `basic_agent.py`, `base.py`, `handler.py`  
**Lines:**
- `basic_agent.py:40-131` (run — yields plain strings)
- `base.py:102-116` (handle_user_input — passes through plain strings)
- `handler.py:214-270` (expects `(sig, val)` tuples)

**Problem:**  
The legacy `Agent.handle_user_input` (`core.py:236`) yields tuples `("__error__", msg)`, `("__tool__", name)`, `("__emotion__", label)`, `("__thinking__", text)`, etc. The WebSocket handler relies on these tuple signals at `handler.py:225-270` to send typed events to the frontend.

`BaseAgent.handle_user_input` (`base.py:102`) just yields whatever `self.run()` yields — which for `BasicAgent`/`PlanningAgent`/`ReflectiveAgent` are only plain `str` chunks. This means:

1. **Errors silently rendered as assistant text** — `BasicAgent.run()` yields `f"Error: {e}"` as a plain string (line 121). The handler never sees `("__error__", ...)`, so it appends "Error: …" to the chat buffer as if it were a normal response.
2. **Tool calls invisible to frontend** — No `("__tool__", "Calling tool: …")` tuples are emitted. The frontend never shows tool-call announcements.
3. **No emotion/thinking/expression signals** — These only exist in the legacy path.
4. **`__permission__`, `__avatar__`, `__roleplay__` signals absent** — Any agent relying on these for rich interaction is broken.

**Fix:**  
Either (a) port the tuple-signal contract into `BaseAgent.run()` as a yield-type union (`str | tuple[str, str]`) and update subclasses to emit signals, or (b) move the signal-emitting wrapper into `BaseAgent.handle_user_input` by introspecting the stream. The legacy `Agent` should eventually be deleted.

---

### C2. Images silently dropped in new-style agents

**Files:** `basic_agent.py`, `base.py`, `handler.py`  
**Lines:**
- `basic_agent.py:40-45` (`run()` ignores `context["images"]`)
- `basic_agent.py:240-249` (`_build_messages` always passes `images=None`)
- `handler.py:214` (calls `agent().handle_user_input(text, images=images, …)`)

**Problem:**  
`BaseAgent.handle_user_input` stores `images` in `ctx["images"]` (`base.py:113`), but `BasicAgent.run()` never reads `ctx["images"]` — it passes `None` for images in `_build_messages` (line 240-241). The legacy `Agent` (`core.py:301-307`) does handle images by converting them to `image_url` content blocks. Regression: any caller sending images gets them silently discarded with new-style agents.

**Fix:**  
Add image handling to `BasicAgent.run()` / `_build_messages()`:

```python
images = context.get("images", [])
messages = await self._build_messages(user_message, images or None, relationship_context)
```

And in `_build_messages` use the same `image_url` content-block pattern from `core.py:301-307`.

---

### C3. `ReflectiveAgent` wrapper never gets `mcp_client`

**Files:** `reflective_agent.py`, `factory.py`  
**Lines:**
- `factory.py:35-39` (calls `ReflectiveAgent(basic, llm, tools, memory, config)` — no `mcp_client` or `strategy_selector`)
- `reflective_agent.py:19-21` (`__init__(self, inner, *args, **kwargs)` → `super().__init__(*args, **kwargs)`)

**Problem:**  
`ReflectiveAgent.__init__` forwards positional args to `BaseAgent.__init__` as `(llm, tools, memory, config)`. `mcp_client` is never forwarded, so `self.mcp_client` is always `None` on the reflective wrapper. Any code that accesses `self.mcp_client` on the wrapper (e.g. `BaseAgent.execute_tool` at `base.py:79`) silently skips MCP tool execution. The inner agent still has it, but the wrapper layer doesn't.

Similarly, `strategy_selector` is not forwarded.

**Fix:**  
Update `factory.py` calls:
```python
ReflectiveAgent(basic, llm, tools, memory, config,
                mcp_client=mcp_client, strategy_selector=strategy_selector)
```

Update `ReflectiveAgent.__init__` to accept and pass `mcp_client`/`strategy_selector`.

```python
def __init__(self, inner: BaseAgent, llm, tools=None, memory=None, config=None,
             mcp_client=None, strategy_selector=None):
    super().__init__(llm, tools or {}, memory, config or {}, mcp_client=mcp_client)
    self.inner = inner
    self._turn_count = 0
```

---

### C4. Path traversal in `ReflectiveAgent._try_create_skill`

**File:** `reflective_agent.py`  
**Lines:** 96-109

**Problem:**  
The skill name is extracted from LLM output via regex (`name_m.group(1).strip()`) and concatenated directly into a filesystem path without sanitization:

```python
skill_name = name_m.group(1).strip()
skill_path = f"data/skills/{skill_name}.md"       # line 101
with open(skill_path, "w") as f:                    # line 108
    f.write(resp)
```

If an LLM response contains `name: ../../etc/cronjob/exploit`, the file write escapes the `data/skills/` directory. While the `_has_injection` check at line 104 runs first, it only looks for prompt-injection substrings — path traversal patterns (`../`, `~`, absolute paths) are not filtered.

**Fix:**  
Add path sanitisation before line 101:
```python
import re
safe_name = re.sub(r'[^a-z0-9_-]', '', skill_name.lower())[:64]
if not safe_name or safe_name != skill_name:
    logger.warning(f"Sanitised skill name '{skill_name}' → '{safe_name}'")
    skill_name = safe_name
skill_path = f"data/skills/{skill_name}.md"
```

---

## HIGH

### H1. Duplicated `execute_tool` — maintenance drag

**Files:** `base.py:68-100`, `basic_agent.py:168-205`  
**Lines:** Both files contain ~97% identical `execute_tool` implementations.

**Problem:**  
The `BaseAgent` default and `BasicAgent` both implement the exact same tool-execution logic (local lookup → MCP fallback → plugin hook). Any bug fix or enhancement must be applied in two places. They have already drifted: `BasicAgent.execute_tool` accesses the plugin registry inside the function, while `BaseAgent.execute_tool` imports it at the top. Functionally identical, but wasteful.

**Fix:**  
Remove `BasicAgent.execute_tool` — `BasicAgent` inherits the identical `BaseAgent.execute_tool`. Or vice versa: if `BasicAgent` needs custom behaviour, factor the common path into a `_execute_tool_impl` helper in `base.py`.

---

### H2. `strategy_selector` not in `BaseAgent` constructor — fragile `getattr` workaround

**Files:** `base.py:38-44`, `basic_agent.py:21-30`, `planning_agent.py:23-26`  
**Lines:**
- `base.py:39` (`__init__` signature: no `strategy_selector`)
- `base.py:62` (`spawn_subagent` uses `getattr(self, 'strategy_selector', None)`)

**Problem:**  
`strategy_selector` is stored only by subclasses, never by `BaseAgent`. The default `spawn_subagent` resorts to `getattr(self, 'strategy_selector', None)` — a fragile runtime workaround. Any new agent type that forgets to store `strategy_selector` silently loses strategy selection in spawned sub-agents.

**Fix:**  
Add `strategy_selector=None` to `BaseAgent.__init__` and store it as `self.strategy_selector = strategy_selector`. Remove the `getattr` workaround.

---

### H3. 8+ bare `except: pass` — error swallowing

**Files:**

| File | Line | What is swallowed |
|------|------|-------------------|
| `basic_agent.py` | 51 | `registry.hook_messages(messages)` |
| `basic_agent.py` | 81 | `registry.hook_messages(messages)` |
| `basic_agent.py` | 150 | `registry.hook_messages(messages)` |
| `basic_agent.py` | 202 | `registry.hook_tool_result(…)` |
| `basic_agent.py` | 259 | `registry.hook_system_prompt(…)` |
| `basic_agent.py` | 275 | `registry.hook_tool_definition(…)` |
| `reflective_agent.py` | 113 | `_try_create_skill` full body |
| `reflective_agent.py` | 135 | `_reflect` full body |
| `handler.py` | 429 | `_handle_avatar_signal` full body |

**Problem:**  
Every plugin hook call is wrapped in `try/except Exception: pass`. A plugin failure silently degrades the system with zero logging. This makes debugging plugin issues impossible. The same pattern exists in `reflective_agent.py` for background tasks — skill creation and reflection failures are logged at `DEBUG` level only, making them invisible in production.

**Fix:**  
Replace every `except: pass` with at minimum `logger.exception("…")` or `logger.warning("…")`. For plugin hooks, consider `logger.warning(f"Plugin hook failed: {e}")`.

---

### H4. `BasicAgent.load_history()` — synchronous blocking in async context

**File:** `basic_agent.py`  
**Lines:** 159-166

**Problem:**
```python
def load_history(self, session_id: str):
    """Load prior turns from memory."""
    stored = []
    if hasattr(self.memory, "get_session_messages"):
        msgs = self.memory.get_session_messages(session_id)  # <-- SYNC CALL
        stored = [{"role": m["role"], "content": m["content"]} for m in msgs[-20:]]
    self._history = stored
```

Called from async `run()` at line 43. If `get_session_messages` hits a database or network, the entire event loop is blocked.

**Fix:**  
Make `load_history` async:
```python
async def load_history(self, session_id: str):
    ...
    msgs = await self.memory.get_session_messages(session_id)  # if async
```

If the memory API is synchronous, wrap it in `asyncio.to_thread` or `loop.run_in_executor`.

---

### H5. `PlanningAgent` missing `self.settings` attribute

**File:** `planning_agent.py`  
**Lines:** 23-31

**Problem:**  
`BasicAgent.__init__` sets `self.settings = config or {}` (line 27). `PlanningAgent.__init__` does **not** set `self.settings`. Any code path that accesses `self.settings` on a `PlanningAgent` instance raises `AttributeError`. The `BaseAgent` doesn't define it either — it only stores `self.config`.

**Fix:**  
Add `self.settings = config or {}` to `PlanningAgent.__init__`, and ensure `update_settings` (line 28-31) also updates `self.settings`.

---

### H6. `PlanningAgent` fallback path missing `mcp_client`

**File:** `planning_agent.py`  
**Lines:** 50-53

**Problem:**
```python
# Decomposition failed — fall back to basic
async for chunk in BasicAgent(
    self.llm, self.tools, self.memory, self.config, strategy_selector=self.strategy_selector
    # ^^^^^^^^^^^ mcp_client NOT passed!
).run(user_message, context):
```

All other `BasicAgent` instantiations in `planning_agent.py` (lines 40, 74, 96) correctly pass `mcp_client=self.mcp_client`. The fallback path at line 50-53 omits it, so if decomposition fails, MCP tools are unavailable.

**Fix:**  
Add `mcp_client=self.mcp_client` to line 51.

---

### H7. `PlanningAgent.update_settings` doesn't call `self.llm.reload_settings()`

**File:** `planning_agent.py`  
**Lines:** 28-31

**Problem:**
```python
def update_settings(self, settings):
    self.config = settings if isinstance(settings, dict) else settings or {}
    logger.debug("PlanningAgent.update_settings called")
```

`BasicAgent.update_settings` (line 32-38) calls `self.llm.reload_settings()` after updating config. `PlanningAgent.update_settings` omits this call. While `settings.py` calls `llm().reload_settings()` before notifying the agent, other callers that go directly to `agent().update_settings()` will not trigger an LLM reload.

**Fix:**  
Add `self.llm.reload_settings()` inside `PlanningAgent.update_settings`.

---

### H8. `PlanningAgent._is_compound` — fragile heuristic

**File:** `planning_agent.py`  
**Lines:** 100-104

**Problem:**
```python
COMPOUND_SIGNALS = [
    " and then ", " after that ", ", then ", " first ",
    " also ", "step 1", "multiple", "each of", "for each",
]

def _is_compound(self, msg: str) -> bool:
    low = msg.lower()
    if any(s in low for s in COMPOUND_SIGNALS) and len(msg.split()) > 15:
        return True
    return False
```

The 15-word threshold is arbitrary. A genuinely compound query with fewer words (e.g., "Find all PDFs and then summarise them") falls below the threshold and skips decomposition entirely. Conversely, a long non-compound query (e.g., "Tell me a very long story about…") triggers unnecessary decomposition overhead.

**Fix:**  
Consider using an LLM call for classification (like the intent classifier but for compound detection), or at least reduce/lower the threshold and add a length-independent check.

---

## MEDIUM

### M1. `base.py` abstract `run()` has dead `yield ""` after `…`

**File:** `base.py`  
**Lines:** 46-52

**Problem:**
```python
@abstractmethod
async def run(self, user_message: str, context: dict) -> AsyncGenerator[str, None]:
    """Yield response chunks. Sets context['last_trace'] when done."""
    ...
    yield ""
```

The `...` (Ellipsis) and `yield ""` are both dead code — the body is never invoked because the method is abstract. But `yield ""` makes the abstract method syntactically an async generator; without it subclasses would fail type checks. Not strictly a bug, but misleading. The `...` placeholder is redundant.

**Fix:**  
Remove the `...` line. Keep `yield ""` as it's needed to make the ABC method syntactically a generator (so type checkers understand the protocol).

---

### M2. `ReflectiveAgent` delegation of `generate_idle_prompt` / `subconscious_reflect` always returns empty for new agents

**File:** `reflective_agent.py`  
**Lines:** 24-30

**Problem:**
```python
async def generate_idle_prompt(self) -> str:
    return await self.inner.generate_idle_prompt() if hasattr(self.inner, 'generate_idle_prompt') else ""

async def subconscious_reflect(self) -> str:
    if hasattr(self.inner, 'subconscious_reflect'):
        return await self.inner.subconscious_reflect()
    return ""
```

Only the legacy `Agent` (`core.py`) implements these methods. `BasicAgent` and `PlanningAgent` do not, so `hasattr` returns `False` and these methods return empty strings. The handler calls these at `handler.py:1138-1141` and `handler.py:1158-1161`, expecting to get idle prompts or reflections. With new-style agents, these features are dead.

**Fix:**  
Add `generate_idle_prompt` and `subconscious_reflect` implementations to `BaseAgent` or at least `BasicAgent` / `PlanningAgent`.

---

### M3. LLM error strings `[Error: …]` not handled in `BasicAgent.run()`

**File:** `basic_agent.py`  
**Lines:** 88-117

**Problem:**  
The legacy `Agent.handle_user_input` (`core.py:322-326`) detects `[Error:` prefixed tokens and yields them as `("__error__", item)`. `BasicAgent.run()` treats ALL strings from `self.llm.stream_with_tools()` as response text, including error strings like `[Error: rate limit exceeded]`. The error text ends up in `full_response` and is displayed as normal assistant output.

**Fix:**  
Add an `[Error:` prefix check before accumulating text, and either yield the error through a signal or raise an exception.

---

### M4. `ReflectiveAgent` background tasks are fire-and-forget with no tracking

**File:** `reflective_agent.py`  
**Lines:** 48-53

**Problem:**
```python
if trace and trace.is_complex:
    asyncio.create_task(self._try_create_skill(trace))

if self._turn_count % self.REFLECT_EVERY == 0:
    asyncio.create_task(self._reflect(context.get("history", [])))
```

These tasks are never tracked or awaited. If the event loop is shutting down, or if an exception is raised before the task starts, the work is silently lost. Both methods catch exceptions internally, but uncaught bugs in `_try_create_skill` or `_reflect` will raise `Task exception was never retrieved` warnings.

**Fix:**  
Track the tasks and ensure they're awaited during shutdown, or at minimum attach a done-callback that logs exceptions:

```python
task = asyncio.create_task(self._try_create_skill(trace))
task.add_done_callback(lambda t: t.exception() and logger.error(f"Skill task failed: {t.exception()}"))
```

---

### M5. `context["last_trace"]` mutation side-effect undocumented

**File:** `basic_agent.py`  
**Lines:** 126

**Problem:**
```python
trace.full_response = full_response
context["last_trace"] = trace
```

The `run()` method mutates the caller-supplied `context` dict as a side-effect. This is the intended contract (documented in `base.py:48`), but the pattern is fragile — if a caller reuses the same context dict across calls, stale traces accumulate. `ReflectiveAgent` already depends on this (reads `context.get("last_trace")` at line 45).

**Recommendation:**  
Document this clearly in all `run()` signatures, or return the trace alongside the final yield instead of relying on mutation.

---

### M6. `MCP client` resolution logic is duplicated and fragile

**Files:** `basic_agent.py:22`, `planning_agent.py:24`

**Problem:**
```python
resolved_mcp = mcp_client or (config.get('mcp_client') if isinstance(config, dict) else None)
```

This logic appears in both `BasicAgent.__init__` and `PlanningAgent.__init__`. It tries to extract `mcp_client` from `config` as a fallback, but only works when `config` is a `dict` — the actual `config` passed from `deps.py` is a `Settings` object (not a dict). So this fallback path never fires in production. The `mcp_client` must be passed explicitly.

**Fix:**  
Remove the dead `config.get('mcp_client')` fallback. If `mcp_client` needs to come from config, define a proper accessor. Or keep it for future use but add a `Settings` branch.

---

### M7. `handler.py:244-246` dead `if` check after `__avatar__`

**File:** `handler.py`  
**Lines:** 243-246

**Problem:**
```python
elif sig_type == '__avatar__':
    await self._handle_avatar_signal(...)
    if sig_type == '__avatar__':
        continue
```

Inside the `elif sig_type == '__avatar__':` block, the condition `if sig_type == '__avatar__':` is always `True`. The `continue` is correct behaviour, but the `if` is dead code. Any code added between `_handle_avatar_signal()` and the `if` in the future would be silently unreachable.

**Fix:**  
Replace with an unconditional `continue`:
```python
elif sig_type == '__avatar__':
    await self._handle_avatar_signal(...)
    continue
```

---

### M8. `BasicAgent.run()` loop termination relies on tool calls — no max iteration guard for empty schemas

**File:** `basic_agent.py`  
**Lines:** 73-123

**Problem:**  
The while loop iterates up to `max_iterations` (default 5). When `schema` is falsy (no tools), the `else` branch fires (line 114-118), yields the LLM stream, and `break`s — correct. But when `schema` is truthy (tools exist), the loop only terminates if either no tool calls are made (line 113 `break`) or all iterations are exhausted. If `max_iterations` is set very high (e.g., from an unvalidated strategy), a tool-calling loop could run many iterations without any guard on total tokens or time.

**Fix:**  
Add a total-token or wall-clock budget inside the loop, or cap `max_iterations` at a safe upper bound (e.g. `min(strategy.max_iterations, 25)`).

---

## LOW

### L1. No type hints for `llm` parameter

**Files:** All constructor signatures in `base.py`, `basic_agent.py`, `planning_agent.py`, `reflective_agent.py`

**Problem:**  
`llm` is typed as just the bare name with no annotation — `llm` without `: LLMRouter` or a Protocol. Type checkers cannot verify LLM interface compliance.

**Fix:**  
Add a type alias or Protocol for the LLM interface, or at minimum `from backend.core.llm import LLMRouter` and annotate parameters.

---

### L2. `BaseAgent.__init__` doesn't validate `tools` type

**File:** `base.py`  
**Lines:** 39-44

**Problem:**  
The annotation says `tools: dict`, but `BasicAgent.__init__` passes `tools or {}` where `tools` might be `None`. If `tools` is `None`, `tools or {}` is `{}`. But if the caller passes an unexpected type (e.g., a list), there is no validation and downstream code assumes it's a `dict`.

**Fix:**  
Add a type guard or conversion at the `BaseAgent` boundary.

---

### L3. Unused imports

**Files:** Various

| File | Import | Notes |
|------|--------|-------|
| `base.py:6` | `from abc import ABC, abstractmethod` | `ABC` imported but `BaseAgent` uses `ABC` implicitly (class `BaseAgent(ABC)`) — actually used. |
| `basic_agent.py:5` | `json` | Imported but never used in `basic_agent.py`. |
| `basic_agent.py:6` | `Optional, Union` | `Optional` not used; `Union` not used (AsyncIterator takes `str` only). |

**Fix:**  
Remove unused imports.

---

### L4. `_has_injection` is a module-level function with no test coverage

**File:** `reflective_agent.py`  
**Lines:** 138-152

**Problem:**  
The injection-detection function uses crude substring matching, has no associated tests, and the `"dan "` pattern (with trailing space) is likely to produce false positives. Since it's called before writing to the filesystem (C4), any bypass here compounds the path traversal risk.

**Fix:**  
Write unit tests for `_has_injection`. Consider using a dedicated prompt-injection detection library rather than ad-hoc substring matching.

---

## Summary Table

| ID | Severity | File | Line(s) | Issue |
|----|----------|------|---------|-------|
| C1 | CRITICAL | `basic_agent.py`, `base.py`, `handler.py` | 40-131, 102-116, 214-270 | New agents don't emit signal tuples → broken error/tool/emotion UI |
| C2 | CRITICAL | `basic_agent.py`, `base.py` | 40-45, 240-241 | Images silently ignored in new-style agents |
| C3 | CRITICAL | `factory.py`, `reflective_agent.py` | 35-39, 19-21 | `ReflectiveAgent` wrapper never gets `mcp_client` |
| C4 | CRITICAL | `reflective_agent.py` | 96-109 | Path traversal in skill name → arbitrary file write |
| H1 | HIGH | `base.py`, `basic_agent.py` | 68-100, 168-205 | Duplicate `execute_tool` implementations |
| H2 | HIGH | `base.py` | 39, 62 | `strategy_selector` not in `BaseAgent.__init__` |
| H3 | HIGH | 8 files | multiple | 8+ bare `except: pass` — error swallowing |
| H4 | HIGH | `basic_agent.py` | 43, 159-166 | Sync `load_history` in async `run()` |
| H5 | HIGH | `planning_agent.py` | 23-31 | Missing `self.settings` attribute |
| H6 | HIGH | `planning_agent.py` | 50-53 | Fallback path missing `mcp_client` |
| H7 | HIGH | `planning_agent.py` | 28-31 | `update_settings` doesn't reload LLM |
| H8 | HIGH | `planning_agent.py` | 100-104 | Fragile compound-detection heuristic |
| M1 | MEDIUM | `base.py` | 46-52 | Dead `...` before `yield ""` in abstract method |
| M2 | MEDIUM | `reflective_agent.py` | 24-30 | `generate_idle_prompt`/`subconscious_reflect` always empty for new agents |
| M3 | MEDIUM | `basic_agent.py` | 88-117 | `[Error:` strings not detected, rendered as normal text |
| M4 | MEDIUM | `reflective_agent.py` | 48-53 | Background tasks fire-and-forget with no tracking |
| M5 | MEDIUM | `basic_agent.py` | 126 | Undocumented context dict mutation side-effect |
| M6 | MEDIUM | `basic_agent.py`, `planning_agent.py` | 22, 24 | Duplicated dead MCP-client fallback logic |
| M7 | MEDIUM | `handler.py` | 243-246 | Dead `if sig_type == '__avatar__'` check |
| M8 | MEDIUM | `basic_agent.py` | 73-123 | No upper bound on tool-loop iterations |
| L1 | LOW | All constructors | — | Missing type hints for `llm` parameter |
| L2 | LOW | `base.py` | 39-44 | No type guard on `tools` parameter |
| L3 | LOW | `basic_agent.py` | 5-6 | Unused imports (`json`, `Optional`, `Union`) |
| L4 | LOW | `reflective_agent.py` | 138-152 | `_has_injection` untested, prone to false positives |

---

## Architectural Observations

1. **Two parallel agent hierarchies are not sustainable.** The legacy `Agent` (`core.py`) and new-style agents (`BaseAgent` + subclasses) share zero abstract interface. The `BaseAgent` ABC was introduced but the legacy `Agent` does not inherit from it. Every caller (`deps.py`, `handler.py`, `settings.py`) must deal with both. Plan: delete `core.py`'s `Agent` once all features (signals, images, idle prompts, reflection) are ported to the new hierarchy.

2. **`handle_user_input` as the main entry point is legacy baggage.** The handler should call `agent.run()` directly instead of going through the legacy-compatibility wrapper `handle_user_input` in `BaseAgent`. This would eliminate the unnecessary delegation layer and make the signal contract explicit.

3. **No integration tests for the agent → handler contract.** The signal-tuple protocol between `agent()` and `handler._run_agent_loop` is entirely implicit. A single integration test that feeds messages through the full pipeline would have caught C1 and C2 immediately.

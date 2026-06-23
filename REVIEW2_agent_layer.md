# Round 2 Aggressive Code Review — Agent Layer

**Review Date:** 2026-06-22  
**Reviewer:** Round 2 (post-fix verification)  
**Scope:** `backend/core/agent/` + `backend/core/deps.py`, `backend/api/ws/handler.py`, `backend/api/routes/settings.py`

---

## Executive Summary

Round 1 found 20 issues (1 critical, 7 high, 8 medium, 4 low). Most have been fixed or mitigated.  

**New findings: 1 critical, 0 high, 6 medium, 6 low / info (13 total).**  

**Key takeaway:** The signal-tuple protocol is now partially wired (tool-call tuples emitted), but a critical `NameError` lurks in `handler.py:54` (`_re` not defined). Several previously reported issues remain only partially addressed.

---

## PREVIOUS ISSUES — Fix Verification

### ✅ Fully Fixed (12 of 20)

| ID | Description | Status |
|----|-------------|--------|
| C2 | Images silently dropped | ✅ `BasicAgent.run()` now reads `context.get("images")` |
| C3 | mcp_client to ReflectiveAgent | ✅ Constructor accepts + passes `mcp_client`/`strategy_selector` |
| C4 | Path traversal in skill name | ✅ `_sanitise_skill_name()` strips `[^a-z0-9_-]` before file write |
| H1 | Duplicate `execute_tool` | ✅ BasicAgent no longer defines its own; inherits from BaseAgent |
| H2 | strategy_selector not in BaseAgent | ✅ Now stored as `self.strategy_selector` |
| H5 | PlanningAgent missing `self.settings` | ✅ Added `self.settings = config or {}` |
| H6 | Fallback path missing `mcp_client` | ✅ All `BasicAgent()` instantiations pass `mcp_client` |
| H7 | `update_settings` doesn't reload LLM | ✅ Added `self.llm.reload_settings()` call |
| M1 | Dead `...` in abstract method | ✅ Removed |
| M4 | Background tasks fire-and-forget | ✅ Tracked + done-callbacks with error logging |
| M7 | Dead `if sig_type == '__avatar__'` | ✅ Unconditional `continue` now |
| M8 | No max iteration upper bound | ✅ `min(strategy.max_iterations, 25)` guard added |
| L2 | No type guard on `tools` | ✅ `isinstance(tools, dict)` check added |
| L3 | Unused imports | ✅ `json`, `Union` removed from basic_agent.py |

### ⚠️ Partially Fixed (4 of 20)

| ID | Leftover |
|----|----------|
| C1 | **Tool tuples now emitted** (`("__tool__", ...)`) but **errors still plain strings** — `BasicAgent.run()` yields `f"Error: {e}"` (line 133) not `"[Error: …]"` format. `BaseAgent.handle_user_input` only checks for `[Error:` prefix (line 113), so error text renders as normal assistant output. |
| H3 | Plugin-hook `except` blocks now log, but **handler.py cleanup paths** (lines 395–397, 406–408, 1076) still use bare `except: pass`. Low risk (WS send failures), but should log at debug. |
| H4 | `load_history` is now `async`, and checks `iscoroutine()`. But **docstring falsely claims** "offloaded to a thread executor" — no `to_thread` or `run_in_executor` call exists. Sync memory backends still block the event loop. |
| M3 | `[Error:` prefix check added in `handle_user_input` (base.py:113). But `BasicAgent.run()` yields `"Error: …"` not `"[Error: …]"` (line 133). The check never fires for agent-internal errors. |

### ❌ Still Broken / Not Addressed (4 of 20)

| ID | Issue |
|----|-------|
| M2 | **`generate_idle_prompt` / `subconscious_reflect` always empty** for `BasicAgent`/`PlanningAgent`. `ReflectiveAgent` delegates to inner agent, which falls through to `BaseAgent`'s default `return ""`. Handler calls these (lines 1145–1149, 1165–1169) and gets nothing with new-style agents. |
| H8 | **`" first "` in `COMPOUND_SIGNALS`** still causes false positives for long non-compound queries containing "first". Heuristic improved (threshold 15→8, short signals added) but `" first "` is inherently ambiguous. |
| L1 | **`llm` parameter typed as `Any`** in all constructors. Not addressed. |
| L4 | **`_has_injection` untested.** Patterns improved but zero test coverage remains. |

---

## NEW ISSUES FOUND (Round 2)

### 🔴 CRITICAL

#### N1. `_normalize_error()` uses undefined `_re` — `NameError` at runtime

**File:** `handler.py`  
**Lines:** 54  

```python
normalized = _re.sub(r'\s+', ' ', error_text.lower()).strip()   # line 54
```

`import re` is at line 6 (not `import re as _re`). The name `_re` is **never defined** in `handler.py`'s namespace. The function `_normalize_error` is called from:
- Line 261: `_normalize_error(str(sig_val))` — on `__error__` signals
- Lines 393, 403: `_normalize_error(str(e))` — on `ServiceError` / general exceptions

**Impact:** The first time an error signal or exception triggers error normalization, the handler crashes with `NameError: name '_re' is not defined`. The exception propagates to the handler's main `try/except`, which then sends a generic error to the frontend, but the original error context is lost.

**Fix:** Replace `_re` with `re` on line 54.

---

### 🟡 MEDIUM

#### N2. `chunks` list is dead storage in `ReflectiveAgent.run()` — memory leak

**File:** `reflective_agent.py`  
**Lines:** 79–82  

```python
chunks = []                         # line 79
async for chunk in self.inner.run(user_message, context):
    yield chunk
    chunks.append(chunk)            # line 82 — never read
```

`chunks` is populated every iteration but **never referenced again**. For long streaming responses (thousands of chunks), this holds everything in memory indefinitely. The list is only used for `run()`'s lifetime but is never consumed.

**Fix:** Remove `chunks = []` and `chunks.append(chunk)`. They are unused. The trace information used for skill creation and reflection comes from `context["last_trace"]` and `context.get("history")`.

#### N3. `run()` contract violated — docs say plain `str` but tuples are yielded

**File:** `base.py:58–74` (docstring) vs `basic_agent.py:109` (yield)

**Contract (base.py):**
```python
@abstractmethod
async def run(...) -> AsyncGenerator[str, None]:
    """Yield response chunks. ...
    - Yields only plain ``str`` chunks for streaming.
    """
```

**Reality (basic_agent.py:109):**
```python
yield ("__tool__", f"Calling tool: {tc_info['name']}")
```

`BasicAgent.run()` yields `tuple[str, str]` objects. The type annotation says `AsyncGenerator[str, None]` which is a lie — the actual type is `AsyncGenerator[str | tuple[str, str], None]`. The `handle_user_input` wrapper handles tuples (base.py:110–112), so it works, but the **contract is misleading**. Any future caller that inspects the return type will assume only strings.

**Fix:** Either (a) update the type annotation and docstring of `BaseAgent.run()` to include signal tuples, or (b) emit tool events via a callback/metadata channel instead of mixing them into the stream.

#### N4. `load_history` docstring falsely claims thread-executor offloading

**File:** `basic_agent.py:190–195`  

```python
async def load_history(self, session_id: str):
    """Load prior turns from memory.
    If the memory API is synchronous, the call is offloaded to a thread
    executor to avoid blocking the async event loop.
    """
    stored = []
    if hasattr(self.memory, "get_session_messages"):
        msgs = self.memory.get_session_messages(session_id)  # <-- STILL SYNC
        ...
```

The docstring promises offloading, but the actual code calls `self.memory.get_session_messages(session_id)` directly. If the memory backend is synchronous (e.g., SQLite), this blocks the event loop. There is no `asyncio.to_thread()` or `loop.run_in_executor()` call.

The `iscoroutine(msgs)` check at line 200 helps for async backends, but the sync path is unmitigated.

**Fix:** Remove the misleading docstring sentence, or wrap the sync call:
```python
loop = asyncio.get_running_loop()
msgs = await loop.run_in_executor(None, self.memory.get_session_messages, session_id)
```

#### N5. `BaseAgent.spawn_subagent` shares `Memory` — cross-contamination risk

**File:** `base.py:127–145` vs `core.py:107–124`

**BaseAgent (new):**
```python
sub = BasicAgent(self.llm, self.tools, self.memory, ...)  # shares self.memory
```

**Agent (legacy):**
```python
sub_memory = Memory(llm_router=self.llm)  # separate Memory
sub_agent = Agent(mcp_client=..., llm=..., memory=sub_memory, ...)
```

The legacy `Agent.spawn_subagent` correctly creates a **new, independent `Memory` instance** for each sub-agent. `BaseAgent.spawn_subagent` passes `self.memory` directly. This means the sub-agent sees the parent's full conversation history, and any `add_turn` calls from the sub-agent pollute the parent's session.

**Fix:** Create a fresh `Memory` instance for the sub-agent, mirroring the legacy pattern.

#### N6. `core.py:Agent.update_settings()` does NOT reload the LLM

**File:** `core.py:63–65`

```python
def update_settings(self, settings):
    self.settings = settings
    self.context_builder.settings = settings
    # missing: self.llm.reload_settings()
```

Both `BasicAgent.update_settings` and `PlanningAgent.update_settings` call `self.llm.reload_settings()`. The legacy `Agent.update_settings` omits it. While `settings.py` lines 142, 230, 254 call `llm().reload_settings()` before notifying the agent, other callers that go directly to `agent().update_settings()` will not trigger an LLM reload for the legacy agent.

**Fix:** Add `if hasattr(self.llm, 'reload_settings'): self.llm.reload_settings()` to `Agent.update_settings()`.

#### N7. `core.py` iteration message uses wrong constant

**File:** `core.py:255, 523`

```python
# line 255
max_iterations = strategy.max_iterations if strategy else MAX_ITERATIONS  # could be > 5

# line 523
if iterations >= MAX_ITERATIONS:    # MAX_ITERATIONS is always 5
    yield "\n[Max tool iterations reached.]\n"
```

If `strategy.max_iterations` is set to, say, 10, the while loop (line 263) runs up to 10 iterations correctly. But after the loop, the comparison at line 523 uses `MAX_ITERATIONS` (always 5). So:
- If iterations = 6 and the loop exited normally (no tools → `break`), the misleading message `"[Max tool iterations reached.]"` is printed.
- If iterations = 10 and the strategy actually hit its limit, the message should appear but the logic is coincidentally correct for values > 5.

**Fix:** Change line 523 to `if iterations >= max_iterations:`. Also, the message should only be shown if the loop actually terminated due to the iteration limit (not via `break`). Add a flag.

#### N8. `PlanningAgent` sub-steps lose original conversation context

**File:** `planning_agent.py:93–97`

Each sub-step creates a fresh `BasicAgent` with default `_history = []`:
```python
async for chunk in BasicAgent(
    self.llm, self.tools, self.memory, self.config,
    mcp_client=self.mcp_client, strategy_selector=self.strategy_selector
).run(instruction, {**context, "is_substep": True}):
```

Only prior step results are injected into the instruction text (lines 87–91). The **original user context** (images, relationship_context, conversation history) is **not forwarded**. Each sub-step runs with an empty history and no relationship context, which means:
- The system prompt doesn't include relationship context.
- Conversation turns from earlier in the session are invisible.
- The agent has no memory of the original user's specific context.

**Fix:** Either (a) inject the full context into each sub-instruction, or (b) pre-load history into the sub-agent instances.

---

### 🔵 LOW

#### N9. Untracked `asyncio.create_task` for `AutoSkillCreator`

**File:** `handler.py:314–318`

```python
asyncio.create_task(self._auto_skill.maybe_create_skill(
    user_message=text,
    tool_calls=tool_calls_in_turn,
    full_response=full_response,
))
```

This task is **not tracked** by `self._track_task()`. If the event loop shuts down before the task completes (e.g., WebSocket disconnect), it may generate `"Task was destroyed but it is pending"` warnings.

**Fix:** Wrap in `self._track_task(asyncio.create_task(...))`.

#### N10. `" first "` in `COMPOUND_SIGNALS` — false positive risk

**File:** `planning_agent.py:16`

```python
COMPOUND_SIGNALS = [
    " and then ", " after that ", ", then ", " first ",
    ...
]
```

A long non-compound query like *"Tell me about the first human to walk on the moon, Neil Armstrong, and what he said when he stepped onto the lunar surface"* (>8 words, contains `" first "`) is falsely flagged as compound. The short-signal list `_COMPOUND_SHORT_SIGNALS` doesn't include `" first "`, so short queries are safe. But any query >8 words that mentions "first" triggers decomposition overhead.

**Fix:** Remove `" first "` from `COMPOUND_SIGNALS` (the short signals already catch true compound patterns like `" first then "`), or add an exclusion for common non-compound patterns.

#### N11. Bare `except: pass` in handler.py cleanup paths

**File:** `handler.py:395–397, 406–408, 1076–1077`

```python
except Exception:
    pass
```

These occur in WS-send cleanup blocks after error recovery. While the risk is low (WS send can fail during disconnect), they silently swallow errors. At minimum `logger.debug("WS send failed during cleanup")` should be added.

#### N12. `PlanningAgent._decompose` has no guard against LLM returning non-list JSON

**File:** `planning_agent.py:153–159`

```python
steps = json.loads(resp)
return [
    s for s in steps
    if isinstance(s, dict) and "title" in s and "instruction" in s
][:5]
```

If the LLM returns a JSON object (`{}`) instead of an array (`[]`), `json.loads` succeeds but `for s in steps` iterates over the object's **keys** (strings), and the `isinstance(s, dict)` check filters everything out, returning `[]`. This silently falls back to the basic agent (which is the intended degradation path). However, the decomposition prompt explicitly says "Respond ONLY with a JSON array" — if the LLM returns a JSON object, there's no log warning about the unexpected response format.

**Fix:** Add a log warning when `json.loads` result is not a list:
```python
resp_json = json.loads(resp)
if not isinstance(resp_json, list):
    logger.warning("Decomposition expected array, got %s", type(resp_json).__name__)
    return []
```

#### N13. `PlanningAgent._is_compound` imports module-level constants inside method

Not a bug, but `_COMPOUND_SHORT_SIGNALS` (line 20–26) and `COMPOUND_SIGNALS` (line 15–18) are module-level lists defined before `_is_compound` uses them. The lookup is O(n) for each because it's a linear scan. For a low-traffic agent this is fine, but it's worth noting that a **set** would be O(1) and more idiomatic for `in` membership checks.

```python
# These are searched with "any(s in text for s in SIGNALS)" — should be sets
COMPOUND_SIGNALS = {...}
_COMPOUND_SHORT_SIGNALS = {...}
```

---

## Summary Table

| ID | Severity | File | Line(s) | Issue |
|----|----------|------|---------|-------|
| N1 | 🔴 CRITICAL | `handler.py` | 54 | `_normalize_error` uses `_re` — `NameError` at first error event |
| N2 | 🟡 MEDIUM | `reflective_agent.py` | 79–82 | `chunks` list never read — dead storage / memory leak |
| N3 | 🟡 MEDIUM | `base.py`, `basic_agent.py` | 58–74, 109 | `run()` contract says plain `str` only, but yields `tuple` |
| N4 | 🟡 MEDIUM | `basic_agent.py` | 190–195 | Load-history docstring falsely claims thread-executor offloading |
| N5 | 🟡 MEDIUM | `base.py`, `core.py` | 127–145 vs 107–124 | `spawn_subagent` shares Memory; legacy correctly creates separate instance |
| N6 | 🟡 MEDIUM | `core.py` | 63–65 | `update_settings()` doesn't reload LLM (new agents do) |
| N7 | 🟡 MEDIUM | `core.py` | 255, 523 | Max-iteration message uses `MAX_ITERATIONS` (5) instead of strategy's `max_iterations` |
| N8 | 🟡 MEDIUM | `planning_agent.py` | 93–97 | Sub-steps lose original context (history, images, relationship) |
| N9 | 🔵 LOW | `handler.py` | 314–318 | Untracked `asyncio.create_task` for AutoSkillCreator |
| N10 | 🔵 LOW | `planning_agent.py` | 16 | `" first "` signal causes compound false positives for long queries |
| N11 | 🔵 LOW | `handler.py` | 395–397, 406–408, 1076 | Bare `except: pass` in cleanup paths |
| N12 | 🔵 LOW | `planning_agent.py` | 153–159 | No log warning when decomposition returns non-list JSON |
| N13 | 🔵 LOW | `planning_agent.py` | 15–26 | Lists used for `in` lookup — sets would be O(1) |

---

## Unfixed from Round 1 (4 issues)

| ID | Severity | Leftover |
|----|----------|----------|
| M2 | MEDIUM | `generate_idle_prompt` / `subconscious_reflect` always empty for `BasicAgent`/`PlanningAgent` |
| H8 | HIGH | `" first "` in `COMPOUND_SIGNALS` still causes false positives |
| L1 | LOW | `llm` parameter typed as `Any` everywhere |
| L4 | LOW | `_has_injection` has zero test coverage |

---

## Final Verdict

**13 new issues found** (1 critical, 6 medium, 6 low) + **4 still-unfixed Round 1 issues**.

The most actionable items:
1. 🛑 **Fix `_re` → `re` in handler.py:54** — will crash on any error signal.
2. Remove dead `chunks` list in `reflective_agent.py:79–82`.
3. Fix the `run()` contract — update type annotation or refactor signal emission.
4. Align `spawn_subagent` memory handling between legacy and new agent hierarchies.
5. Fix `core.py` iteration-count message and `update_settings` LLM reload.
6. Pass full conversation context to PlanningAgent sub-steps.

The agent layer is in much better shape than Round 1. Signal-tuple support is wired, file-write sanitisation is in place, and background tasks are tracked. But the `_re` bug is a genuine runtime blocker, and the shared-memory sub-agent pattern could cause hard-to-debug session corruption.

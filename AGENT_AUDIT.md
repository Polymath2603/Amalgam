# AGENT Layer Audit

Audited: 2026-06-22

Files in `/backend/core/agent/`:
- `__init__.py` — re-exports `AgentFactory`, `BaseAgent`, `AgentTrace`, `ToolCall`
- `base.py` — abstract `BaseAgent`, dataclasses `ToolCall`, `AgentTrace`
- `basic_agent.py` — `BasicAgent(BaseAgent)`
- `reflective_agent.py` — `ReflectiveAgent(BaseAgent)` — wraps any agent with reflection
- `planning_agent.py` — `PlanningAgent(BaseAgent)` — decomposes compound tasks
- `factory.py` — `AgentFactory.create()` — dispatches by type string
- `core.py` — legacy monolithic `Agent` — fallback only
- `permissions.py` — tool permission system (actively imported by MCP client)
- `hooks.py` — tool hook system (actively imported by MCP client)
- `analytics.py` — tool analytics (actively imported by MCP client)
- `interface.py` — DEAD — backward-compat shim, no imports since migration to `base.py`
- `stream_processor.py` — DEAD — emotion-tag stream parser, superseded by `core.py` inline handling

---

## Findings

### 1. `interface.py` — DEAD (safe to delete)

- **Imports**: Zero matches for `from backend.core.agent.interface` anywhere in `backend/`.
- It's a backward-compat shim that re-exports from `base.py`:
  ```python
  from backend.core.agent.base import BaseAgent, AgentTrace, ToolCall
  AgentInterface = BaseAgent
  ```
- `__init__.py` already re-exports `BaseAgent`, `AgentTrace`, `ToolCall` from `base` directly.
- **Verdict**: DELETE. No code references it.

### 2. `stream_processor.py` — DEAD (safe to delete)

- **Imports**: Zero matches for `stream_processor` or `parse_emotion_stream` anywhere in the codebase.
- Contains `parse_emotion_stream()` — an async generator that strips `[emotion]` tags from LLM streams.
- Emotion tag handling is now done inline in `core.py` (`_process_tags`, `_strip_all_tags`).
- **Verdict**: DELETE. No code references it.

### 3. `factory.py` — Correct, handles all types

- Handles: `"basic"`, `"planning"`, `"reflective"`, `"reflective_planning"`
- Unknown type raises `ValueError(f"Unknown agent type: {agent_type}")` — correct.
- Settings route (`api/routes/settings.py:74`) validates against the same set.
- **Verdict**: No fix needed.

### 4. Agent type coverage

- `BasicAgent` — ✔ creatable by factory
- `PlanningAgent` — ✔ creatable by factory
- `ReflectiveAgent` — ✔ creatable by factory (wrapping either BasicAgent or PlanningAgent)
- Default in `deps.py:103` is `"reflective_planning"`.

### 5. `core.py` (legacy Agent)

- Imported directly in `deps.py:15` as a **fallback** when `AgentFactory.create()` raises.
- Also imported by `tests/test_agent_tags.py`.
- Not created through the factory; it's the legacy path.
- **Verdict**: Keep as fallback — still wired to active code.

### 6. `update_settings()` / `reload_settings()` consistency

| Class | `update_settings()` | `reload_settings()` |
|---|---|---|
| `BaseAgent` (base.py) | ✗ | ✗ |
| `BasicAgent` | ✔ delegates to llm.reload_settings() | ✗ |
| `PlanningAgent` | **✗ MISSING** | ✗ |
| `ReflectiveAgent` | ✔ delegates to inner.update_settings() | ✗ |
| `Agent` (core.py) | ✔ updates self + context_builder | ✗ |

- **`PlanningAgent` is missing `update_settings()`** — settings changes silently fail to propagate when agent type is `"planning"`.
- `reload_settings()` does not exist on any agent class; it's only on LLM/TTS/Companion.

**Bug**: `api/routes/settings.py:257` calls `agent().update_settings(s)` unconditionally. When the agent is a `PlanningAgent`, this raises `AttributeError` caught at line 258, logging a warning. Settings do NOT propagate to the PlanningAgent.

---

## Fixes Applied

1. **Deleted** `backend/core/agent/interface.py` — zero consumers.
2. **Deleted** `backend/core/agent/stream_processor.py` — zero consumers.
3. **Added** `update_settings(self, settings)` to `PlanningAgent` — mirrors `BasicAgent.update_settings()`.

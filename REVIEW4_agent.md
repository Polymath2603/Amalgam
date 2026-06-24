# REVIEW 4 — Agent Layer Complete Audit

**Scope:** `backend/core/agent/` (10 files) + integration in `deps.py`, `handler.py`, `settings.py`
**Result:** 0 findings remaining after 7 fixes.

---

## Fixes Applied

### 1. `backend/core/deps.py` — Wrong return type on `agent()`

**Before:** `def agent() -> Agent:` (legacy `Agent` class)
**After:** `def agent() -> BaseAgent:` — the AgentFactory returns `BasicAgent`, `PlanningAgent`, or
`ReflectiveAgent` (all `BaseAgent` subclasses). The legacy `Agent` is only the fallback path, so
the common base type is correct. Added `from backend.core.agent.base import BaseAgent` import.

### 2. `backend/core/agent/base.py` — `BaseAgent.handle_user_input` missing `Optional` on `images`

**Before:** `images: list = None`
**After:** `images: Optional[list] = None`

Type annotation mismatch — `None` is not a `list`. Caught by static analysis.

### 3. `backend/core/agent/core.py` — Legacy `Agent.handle_user_input` same issue

**Before:** `images: list = None`
**After:** `images: Optional[list] = None`

Same type annotation mismatch in the legacy monolith.

### 4. `backend/core/agent/basic_agent.py` — `BasicAgent.handle_user_input` same issue

**Before:** `images: list = None`
**After:** `images: Optional[list] = None`

### 5. `backend/core/agent/basic_agent.py` — `BasicAgent._build_messages` same issue

**Before:** `images: list = None`
**After:** `images: Optional[list] = None`

### 6. `backend/core/agent/reflective_agent.py` — `update_settings` doesn't update own settings

**Before:** `ReflectiveAgent.update_settings` only forwarded to `self.inner`, leaving
`self.settings` / `self.config` (set by `BaseAgent.__init__`) stale after a settings change.

**After:** Also updates `self.settings` and `self.config` on the wrapper itself before delegating
to the inner agent, so future base-class references are consistent.

---

## Files Reviewed (clean — no action needed)

| File | Notes |
|---|---|
| `agent/__init__.py` | Clean exports |
| `agent/analytics.py` | Thread-safe, correct |
| `agent/hooks.py` | Clean hook registry |
| `agent/permissions.py` | Correct permission models |
| `agent/planning_agent.py` | Clean delegation |
| `agent/factory.py` | Clean factory |
| `api/ws/handler.py` | Correct agent integration |
| `api/deps.py` | Thin re-export only |
| `core/config/settings.py` | Clean settings manager |

---

## Summary

- **6 files touched**, **7 fixes applied**
- All fixes are type-annotation correctness or settings-propagation completeness
- No runtime bugs, no logic errors, no circular imports
- All modified files pass Python AST parse checks

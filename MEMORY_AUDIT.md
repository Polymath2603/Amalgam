# Memory Subsystem Audit

**Date:** 2026-06-22  
**Scope:** `backend/core/memory/` + integration points in `backend/core/agent/`, `backend/api/routes/memory.py`, `webui/js/modules/memory-graph.js`

---

## 1. Memory class — Initialization & Methods

**Status:** ✅ Well-structured, correctly initialized.

**Files:** `manager.py` (826 lines), `__init__.py` 

```python
# Key methods (manager.py):
- start_session()          ✅ Used from routes & agent
- set_current_session()    ✅ Used from routes
- get_current_session()    ✅ Used from routes
- add_turn()               ✅ Used from agent
- get_recent()             ✅ Used from agent (core.py:189, 266)
- get_sessions()           ✅ Used from routes
- get_session_messages()   ✅ Used from routes
- delete_session()         ✅ Used from routes
- get_relevant()           ✅ Used from agent (core.py:268) & routes
- retrieve_for_context()   ✅ Internal use by get_relevant
- search_all_sessions()    ✅ Used from routes
- clear()                  ✅ Used from routes
- rename_session()         ✅ Used from routes (deprecated)
- check_and_summarize()    ✅ Internal via add_turn
- search_all_sessions_fts()❌ **UNUSED** — defined but never called (now exposed via API)
- store_semantic_fact()    ❌ **UNUSED** — defined but never called by agent or routes
- search_semantic()        ❌ **UNUSED** — defined but never called by agent or routes
```

**Initialization:** The class is instantiated in `deps.py` (line 51-52) with llm_router and settings. All sub-components are lazy-loaded or initialized in `__init__`.

---

## 2. ContextBuilder vs ContextManager

| Feature | ContextBuilder | ContextManager |
|---|---|---|
| **File** | `backend/core/context_builder.py` | `backend/core/context_manager.py` |
| **Role** | Builds the system prompt template (identity, character, tools, vault, skills) | Token-budget-aware context selection & truncation |
| **Created in deps.py** | ✅ Yes (line 53-54) | ✅ Yes (line 55-56) |
| **Called from agent** | ✅ `agent/core.py:282 — self.context_builder.build()` | ❌ **NEVER CALLED** — `build_context()` is dead code |
| **Injected to API** | ✅ As `context_builder()` dependency | ✅ As `context_manager()` dependency |

**Finding:** `ContextManager` is instantiated in `deps.py` and available as a dependency, but its `build_context()` method is never called from any agent, orchestrator, or route code. The agent uses `ContextBuilder.build()` directly and handles token truncation via `_truncate_context()` instead. `ContextManager` is **dead code** — it should be either wired into the agent's context pipeline or removed.

---

## 3. FTS (Full Text Search)

**Status:** 🟡 Implemented but under-exposed.

**File:** `backend/core/memory/fts.py` (205 lines, class `FTSSearch`)

**Usage:**
- ✅ `manager.py:87` — `FTSSearch` initialized during `Memory.__init__()`
- ✅ `manager.py:432` — `self._fts.index_message()` called during `add_turn()`
- ✅ `manager.py:720-724` — `search_all_sessions_fts()` uses `self._fts.search()`
- ✅ Exported in `memory/__init__.py`
- ✅ `app.py:159-162` — Used for /ready health check probe

**Issues:**
- ❌ `search_all_sessions_fts()` was defined but had **no API endpoint** until this audit (now fixed)
- ❌ FTS probe in `/ready` endpoint (app.py) creates a temporary FTSSearch instance — wasteful, should reuse `memory()._fts`

---

## 4. ChromaDB

**Status:** 🟡 Graceful fallback but some gaps.

**Files:** `manager.py`, `episodic.py`, `vault.py`

**Usage locations:**
- `manager.py:64-82` — conversations collection, **has fallback** (chroma = None)
- `manager.py:312-318` — episodic collection creation
- `vault.py:37-44` — vault collection

**Fallback behavior:**
- ✅ ChromaDB import is guarded with `try/except _HAS_CHROMADB`
- ✅ When absent, `chroma = None` / `chroma_col = None`
- ✅ All ChromaDB operations wrapped in `try/except`

**Issue fixed:**
- ❌ When ChromaDB was absent, `_known_sessions` was not populated (was inside the `if _HAS_CHROMADB:` block) — **fixed** by moving the scan outside the block.

---

## 5. BM25

**Status:** ✅ Correctly used alongside ChromaDB.

**Usage:**
- `hybrid.py` — `HybridRetrieval` uses BM25 + ChromaDB in RRF (Reciprocal Rank Fusion)
- `vault.py` — `VaultManager.search()` uses BM25Okapi standalone
- `semantic.py` — `SemanticMemory` uses BM25 for fact searching
- `manager.py:410` — `HybridRetrieval.rebuild_bm25()` called every `add_turn()`

**Fallback:** All BM25 usage is guarded:
- `HybridRetrieval` — `from rank_bm25 import BM25Okapi` with `try/except` (line 2-4 of hybrid.py)
- `SemanticMemory` — `_rebuild_bm25()` catches `ImportError` and degrades gracefully

---

## 6. Working Memory

**Status:** 🟡 Capacity mismatch **fixed**.

| Aspect | Value |
|---|---|
| **Class** | `WorkingMemory` in `working.py` |
| **Initial capacity** | Was hardcoded `20` → **Now dynamic from `memory.context_window`** (default 50) |
| **Used in `add_turn()`** | ✅ Always — `self._working.add(role, content)` |
| **Used in `get_recent()`** | ✅ Preferentially checked before disk fallback |
| **Eviction** | FIFO (OrderedDict popitem) — correct |

**Issue fixed:** The hardcoded capacity of 20 was smaller than the default `memory.context_window` setting of 50, causing `get_recent(50)` to always fall through to disk for even 21-50 turns.

---

## 7. Memory Graph (`webui/js/modules/memory-graph.js`)

**Status:** ✅ Functional and wired.

**Data sources:**
- `/api/memory/sessions` — list of sessions (nodes) with chronological edges
- `/api/memory/session/{id}` — individual session details (on node click)
- `/api/memory/search?q=...&scope=all` — search results (on search input)

**Integration:**
- Imported in `webui/js/app.js` (line 31)
- Called via `initMemoryGraph()` / `destroyMemoryGraph()` (app.js:226, 229)
- Container in `webui/index.html` line 204
- CSS styles in `webui/css/style.css` lines 2148-2280

**Limitations:** Only shows session-level nodes, not individual messages. Search resizes node radius to highlight hits. No WebSocket for real-time updates (must click Refresh).

---

## 8. Memory Routes

**File:** `backend/api/routes/memory.py`

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/api/memory/sessions` | GET | ✅ Active | Lists all sessions |
| `/api/memory/session/{id}` | GET | ✅ Active | Gets messages for a session |
| `/api/memory/session/{id}/rename` | POST | ⚠️ `@deprecated` | Uses query param instead of body |
| `/api/memory/session/{id}/resume` | GET | ⚠️ `@deprecated` | |
| `/api/memory/session/{id}/activate` | POST | ⚠️ `@deprecated` | |
| `/api/memory/session/{id}` | DELETE | ✅ Active | |
| `/api/memory/clear` | POST | ✅ Active | |
| `/api/memory/session/current` | GET | ✅ Active | |
| `/api/memory/new-session` | POST | ✅ Active | |
| `/api/memory/search` | GET | ✅ Active | semantic/hybrid search |
| `/api/memory/search-fts` | GET | ✅ **NEW** | FTS5 keyword search |

**Missing endpoints (for complete coverage):**
- ❌ `/api/memory/facts` — CRUD for semantic facts (uses `store_semantic_fact` / `search_semantic` which are defined but have no route)

---

## Summary of Issues Fixed

| # | Issue | Severity | Fix |
|---|---|---|---|
| 1 | `_known_sessions` not populated when ChromaDB absent | Medium | Moved session scan outside `if _HAS_CHROMADB:` block |
| 2 | Working memory capacity hardcoded to 20, mismatch with 50 default | Medium | Now reads `memory.context_window` setting at init |
| 3 | No FTS search API endpoint | Low | Added `/api/memory/search-fts` route |
| 4 | `search_all_sessions_fts()` dead code | Low | Now exposed via API route |

## Remaining Issues (Not Fixed)

| # | Issue | Severity | Recommendation |
|---|---|---|---|
| 1 | `ContextManager.build_context()` is dead code | Medium | Either wire into agent context pipeline or remove |
| 2 | `store_semantic_fact()` / `search_semantic()` have no API routes | Low | Add `/api/memory/facts` CRUD endpoints |
| 3 | `/ready` creates temporary FTSSearch instead of reusing `memory()._fts` | Low | Replace with `memory()._fts.search("probe")` |
| 4 | `rename_session` route uses query param `new_title` instead of body | Low | Convert to request body model |

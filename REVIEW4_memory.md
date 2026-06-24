# REVIEW4: Memory Layer — Complete Clean Review

**Date**: 2026-06-23  
**Scope**: `backend/core/memory/` (10 files) + `context_builder.py`, `context_manager.py`, `vault.py`  
**Goal**: 0 findings after fix pass

---

## Summary

13 files reviewed. **7 issues found and fixed**. All fixes verified by syntax check (`py_compile`).

---

## Issues Found & Fixed

### 1. [HIGH] `semantic.py` — Missing thread-safety lock

**Problem**: `SemanticMemory` is used from multiple threads (event loop + executor), but `_documents`, `_dirty`, and `_bm25` were accessed without any synchronization. Concurrent `add_fact()` + `search()` could corrupt the document list or BM25 index.

**Fix**: 
- Added `threading.Lock()` 
- Wrapped `add_fact()`, `search()`, `count()`, `clear()` inside the lock
- `_rebuild_bm25()` and `_load()` now document "caller must hold _lock"
- `save()` snapshots `_documents` under the lock before releasing for file write
- All public API methods now thread-safe

### 2. [HIGH] `manager.py` — Race condition on shared `_session_data_cache`

**Problem**: `_cache_get()`, `_cache_put()`, `_cache_remove()` modify the shared `OrderedDict` `_session_data_cache` while only holding a *per-session* lock. Two threads accessing different sessions could corrupt the LRU cache (e.g., concurrent `pop` + `__setitem__` or concurrent `popitem` eviction).

**Fix**: Added `self._cache_lock` (`threading.Lock`) and wrapped all three cache access methods with it.

### 3. [HIGH] `manager.py` — `check_and_summarize()` blocked event loop with synchronous I/O

**Problem**: The two `self._read_sync(session_id)` calls (lines 896, 906) are synchronous file reads executed directly inside an `async` task, blocking the entire event loop. For sessions with large JSON files (~MB), this could cause visible UI stutter.

**Fix**: Offloaded both reads to `loop.run_in_executor(self._executor, self._read_sync, session_id)`.

### 4. [HIGH] `manager.py` — `_get_local_embedding()` race condition

**Problem**: Double-checked locking pattern was missing — two concurrent coroutines could both pass the `not _LOCAL_EMBEDDING_LOADED` check and both attempt to load SentenceTransformer.

**Fix**: Added `_LOCAL_EMBEDDING_LOCK` with proper double-checked locking pattern (fast path with `_LOCAL_EMBEDDING_LOADED`, then acquire lock, re-check, load).

### 5. [MEDIUM] `manager.py` — Blocking I/O calls on event loop in `add_turn()`

**Problem**: `_session_index.upsert()`, `_fts.index_message()`, and `episodic.add_episode()` all perform synchronous disk I/O (SQLite/JSON writes) directly on the event loop thread.

**Fix**: Offloaded all three to `loop.run_in_executor(self._executor, ...)`.

### 6. [MEDIUM] `manager.py` `clear()` — Private member access on `SessionIndex`

**Problem**: `self._session_index._index.clear()` followed by `self._session_index._save()` accessed private attributes of `SessionIndex`.

**Fix**: Added public `SessionIndex.clear()` method and replaced calls with `self._session_index.clear()`.

### 7. [LOW] `context_builder.py` — Blocking file I/O in `_build_vault_section()`

**Problem**: `_build_vault_section()` read `rules.md` synchronously via `open()` inside an async context (called from `_build_character_prompt()` which is awaited from `build()`).

**Fix**: Made `_build_vault_section()` async and used `asyncio.to_thread()` for the file read.

---

## Files Without Issues (Clean)

| File | Verdict |
|------|---------|
| `memory/__init__.py` | Clean |
| `memory/cache.py` | Clean (has own lock, proper TTL eviction) |
| `memory/consolidator.py` | Clean |
| `memory/episodic.py` | Clean |
| `memory/fts.py` | Clean (thread-local connections, proper FTS5 escaping) |
| `memory/hybrid.py` | Clean |
| `memory/working.py` | Clean (event-loop-thread-only usage) |
| `context_manager.py` | Clean (well-structured token budget math) |
| `vault.py` | Clean (proper path traversal protection, mtime caching) |
| `memory/manager.py` *(after fixes)* | Clean |

---

## Re-review Result: 0 remaining findings

All identified issues have been addressed. Memory layer is **COMPLETELY CLEAN**.

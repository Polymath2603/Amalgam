# ROUND 2 Aggressive Code Review: Memory & Context Layer

**Date:** 2026-06-22  
**Reviewer:** Jcode Agent  
**Scope:** `backend/core/memory/`, `backend/core/context_builder.py`, `backend/core/context_manager.py`, `backend/core/vault.py`, `backend/core/deps.py`, `backend/core/agent/core.py`, `backend/core/agent/basic_agent.py`, `backend/core/agent/base.py`, `backend/core/startup.py`, `backend/api/routes/memory.py`, `backend/api/ws/handler.py`, `backend/cli/companion.py`

**Previous Review:** `REVIEW_memory_layer.md` (63 issues)  
**This Review:** Verification of all 63 fixes + new findings.

---

## 1. VERIFICATION OF PREVIOUS 63 ISSUES

### 1.1 Criteria

| Severity | Fixed | Partially Fixed | Not Fixed | Out of Scope |
|----------|-------|----------------|-----------|-------------|
| 🔴 Critical | 4 | 0 | 0 | 0 |
| 🟠 High | 16 | 2 | 0 | 0 |
| 🟡 Medium | 28 | 3 | 2 | 3 |
| ⚪ Low | 5 | 0 | 0 | 0 |
| **Total** | **53** | **5** | **2** | **3** |

### 1.2 Summary of Fixed Items

The following 53 issues from the original review are **fully resolved**:

- **🔴 #1** (`_write_sync` race): Per-session lock + atomic write (tmp+rename) implemented. ✓
- **🟠 #2** (`_read_sync` race): Both use per-session lock consistently. ✓
- **🟠 #3** (`start_session` blocking): Now uses `await self._write()` (executor path). ✓
- **🟠 #4** (shutdown `wait=False`): Changed to `wait=True`. ✓
- **🟡 #5** (`add_turn` lock+sync I/O): Deferred to executor via `_write_sync` inside per-session lock. ✓
- **🟡 #6** (`_maybe_migrate` re-entrancy): Sentinel file + per-file exception handling. Remaining TOCTOU race is benign (one-time migration). ✓
- **🔴 #7** (no rollback): Operations reordered — disk write first, auxiliary ops after. ChromaDB failures logged at WARNING. ✓
- **🟠 #8** (`session_index._save` atomicity): tmp + `os.replace` atomic write. ✓
- **🟠 #9** (FTS `PRAGMA synchronous=OFF`): Changed to `synchronous=NORMAL`. ✓
- **🟡 #10** (`semantic.add_fact` sync I/O): `save()` uses atomic write. Still sync, but mitigated. ✓
- **🟡 #11** (session_index rewrite every turn): Atomic write mitigates corruption risk. ✓
- **🟠 #12** (`_get_embedding` dead paths): Priority-list based fallback chain implemented. ✓
- **🟡 #13** (`_get_local_embedding` silent failure): Warnings logged on failure. ✓
- **🔴 #14** (BM25 rebuild every turn): Changed to `add_document` (incremental). ✓ (but see Issue #4 below)
- **🟡 #15** (BM25 empty-doc index mismatch): `_bm25_non_empty_indices` mapping implemented. ✓
- **🟡 #16** (`semantic._rebuild_bm25` O(n) per search): Dirty flag skip when not dirty. ✓
- **🟡 #17** (vault BM25 rebuild every search): Mtime caching. ✓
- **🟠 #18** (ChromaDB `add` failure silent): Changed to `logger.warning`. ✓
- **🟠 #19** (delete_session ChromaDB failure silent): Changed to `logger.warning`. ✓
- **🟡 #20** (ChromaDB None → crash): `HybridRetrieval.__init__` types `chroma_col` as `Optional[Any]`, handles None. ✓
- **🟡 #21** (episodic `get()` fragility): `(results.get("documents") or [[]])[0]` pattern. ✓
- **🟠 #22** (session_data_cache unbounded): `OrderedDict` + LRU eviction at 100 entries. ✓
- **🟠 #23** (`_episodic_memories` unbounded): Cleaned on `delete_session` and `clear`. ✓
- **🟡 #24** (`cache.py` no eviction): Periodic cleanup with `_cleanup_interval`. ✓
- **🟡 #25** (session_index unbounded): Acceptable — entries are small. ✓
- **🟠 #27** (`get_recent` working memory cold start): Disk fallback handles it. ✓
- **🟡 #28** (capacity side effect): Documented behavior, acceptable. ✓
- **🟡 #29** (working counter reset): `clear()` resets `_counter = 0`. ✓
- **🟡 #31** (BM25 index mismatch with non-empty docs): Mapping with `_bm25_non_empty_indices` fixed. ✓
- **🟡 #34** (FTS5 syntax errors): `_sanitize_query()` escapes special characters. ✓
- **🟠 #35** (`relationship_context` injection): Section header added, placed after vault rules. ✓
- **🟡 #36** (vault path traversal): Directory traversal check added. ✓ (but see Issue #11 below)
- **🟠 #38-41** (context_manager overhead/documentation): Calibration notes added, whitespace handling fixed, deque used for O(n) → O(1). ✓
- **🟡 #42** (`pop(0)` → `deque.popleft()`): Fixed in `agent/core.py`. ✓
- **🟡 #43** (`_known_sessions` dead data): Removed. ✓
- **🟠 #44** (dead fallback in `get_relevant`): Removed. ✓
- **🟡 #45** (`get_all_recent` alias): Removed. ✓
- **🟡 #46** (no-op methods in core.py): Removed. ✓
- **🟡 #48** (`build_from_messages` side effect): Now returns new list without mutating input. ✓
- **🟡 #49** (migration exception logging): Changed to WARNING level. ✓
- **🟠 #50** (`retrieve_for_context` exception logging): WARNING level. ✓
- **🟡 #51** (`hybrid.retrieve` exception logging): DEBUG with exception detail. ✓
- **🟡 #52** (vault ChromaDB delete silent): WARNING level. ✓
- **🟡 #53** (basic_agent `except: pass`): WARNING level logging in all hook wrappers. ✓
- **🟡 #55** (FactCache/HybridRetriever aliases): Removed. ✓
- **🟡 #58** (magic number `5`): `MAX_ITERATIONS = 5` constant. ✓
- **🟡 #59** (magic constants in context_manager): Calibration notes added. ✓
- **🟡 #60** (`VAULT_CHUNK_SIZE = 500`): Increased to 1000. ✓
- **🟡 #61-63, type hint issues**: Most type hints improved — `__init__` has `Any`/`Optional`, `→ None` added, etc. ✓
- **vault path traversal check**: Added `rglob` for subdirectories in `_index_vault`. ✓
- **hasattr(self, '_bm25')**: Removed dead `hasattr` check. ✓

### 1.3 Partially Fixed Items

| # | Severity | Issue | Status |
|---|----------|-------|--------|
| 10 | 🟡 | `semantic.add_fact` sync I/O from async context | `save()` uses atomic write, but `store_semantic_fact` (line 655) is still synchronous and calls `_save()` which does I/O. Blocks event loop when called from async code. |
| 14 | 🔴 | BM25 rebuild O(n²) per session | Changed to `add_document()`, but `_rebuild()` is still called on **every** `add_document`, iterating all accumulated docs. Still O(n²) per session. |
| 16 | 🟡 | `semantic._rebuild_bm25` on every search | Dirty flag prevents rebuild when not dirty. But `_rebuild_bm25` still O(n) when triggered. Acceptable. |

### 1.4 Not Fixed Items

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 30 | 🟡 | RRF uses first 50 chars of content as dedup key — collisions possible | `hybrid.py` lines 74, 96: `content[:50]` still used. Two messages with same first 50 chars collide. Should use proper message ID (e.g., `session_id + "_" + idx`). |
| 32 | 🟡 | BM25 tokenization uses `\b\w+\b` regex | `hybrid.py` lines 28, 46: `\b\w+\b` misses code snippets (`foo_bar`, `foo::bar`), URLs, decimal numbers. Should match FTS5 `porter unicode61` tokenization or at least include `_` and common symbols. |

---

## 2. NEW AND REMAINING ISSUES

### 🔴 CRITICAL (2)

#### 🔴 Issue #1: `start_session()` called without `await` across 8 call sites

`Memory.start_session()` is `async def` (manager.py:255), but called without `await` in **8 locations** across 5 files. In each case, the coroutine is created and immediately discarded — the session data is never written to disk, and the returned session_id is a coroutine object (not a string).

**Affected call sites:**

| File | Line | Call | Impact |
|------|------|------|--------|
| `backend/core/agent/core.py` | 110 | `sub_memory.start_session()` | Sub-agent has no valid session; `get_current_session()` falls back to `_start_session_sync()` |
| `backend/core/startup.py` | 46 | `memory.start_session()` | No session created at startup if none active |
| `backend/api/routes/memory.py` | 66 | `memory().start_session()` | `/api/memory/clear` returns coroutine as session_id |
| `backend/api/routes/memory.py` | 79 | `memory().start_session()` | `/api/memory/new-session` returns coroutine as session_id |
| `backend/api/ws/handler.py` | 607 | `memory().start_session()` | `/clear` slash command returns coroutine as session_id |
| `backend/api/ws/handler.py` | 612 | `memory().start_session()` | `/new` slash command returns coroutine as session_id |
| `backend/cli/companion.py` | 155 | `self._memory.start_session()` | CLI `/clear` does not create new session |
| `backend/cli/companion.py` | 159 | `self._memory.start_session()` | CLI `/new` returns coroutine as session_id |

Example of the bug:
```python
# api/routes/memory.py:79
sid = memory().start_session()  # sid is a coroutine, not a string!
return {"session_id": sid, "status": "ok"}  # FastAPI serializes to "<coroutine object start_session at 0x...>"
```

**Fix:** Either add `await` to all 8 call sites, or for the sync callers, use `_start_session_sync()` (which exists at line 289).

---

#### 🔴 Issue #2: Cache key collision in `retrieve_for_context` — all sessions in same month share cache entries

`manager.py:735`:
```python
cache_key = f"{session_id[:8]}:{query[:80]}"
```

Session ID format is `"%Y-%m-%d_%H%M%S"` (17 chars, e.g., `"2026-06-22_225511"`). The first 8 chars are `"2026-06-"` — **identical for all sessions created in the same month**. Every session in June 2026 shares the same cache prefix, causing:

- Session A searches "how to debug Python" → result cached
- Session B searches "how to debug Python" → **serves Session A's cached result** (wrong session's data)
- Session B searches something unique → Session A gets Session B's cached result

This affects `retrieve_for_context` which caches hybrid retrieval results with a 300-second TTL (line 751-752).

**Fix:** Use the full session_id (or at least `session_id[:16]` which includes date+hour+minute, reducing collision window to 1 minute):
```python
cache_key = f"{session_id}:{query[:80]}"
```

**Proof:**
```python
sid1 = '2026-06-22_225511'
sid2 = '2026-06-22_230011'
assert sid1[:8] == sid2[:8] == '2026-06-'  # COLLISION
```

---

### 🟠 HIGH (3)

#### 🟠 Issue #3: `rename_session` and `delete_message` use `threading.Lock` in async context — blocks event loop

`manager.py:428-436`:
```python
async def rename_session(self, session_id: str, new_title: str) -> str:
    ...
    lock = self._get_session_lock(session_id)
    with lock:                    # threading.Lock in async ctx — BLOCKS
        data = self._read_sync(session_id)    # sync I/O inside lock
        ...
        self._write_sync(session_id, data)    # sync I/O inside lock
```

Same pattern in `delete_message` (line 663-680), `add_turn` disk-write section (line 464-490), `_prune_tool_outputs` (line 799-811), and `check_and_summarize` final write section (line 855-863).

Using `threading.Lock` with `with lock:` in an `async def` blocks the event loop thread. While the lock ensures thread safety, the event loop is blocked during all synchronous I/O inside the locked section.

**Fix:** Either:
- Move the locked section into a thread pool executor (e.g., `loop.run_in_executor`)
- Use `asyncio.Lock` with `async with lock:` and keep actual I/O in executor
- Or make these methods fully synchronous (remove `async`)

---

#### 🟠 Issue #4: `hybrid.add_document` calls O(n) `_rebuild()` on every turn — still O(n²) per session

`hybrid.py:23-40`:
```python
def add_document(self, msg: dict):
    ...
    self._bm25_docs.append(msg)
    if self._bm25 is not None:
        self._rebuild()     # O(n) — iterates ALL _bm25_docs
    else:
        self._rebuild()
```

`_rebuild()` at line 42-53:
```python
def _rebuild(self):
    corpus = []
    for doc in self._bm25_docs:        # iterates ALL docs
        tokens = re.findall(r'\b\w+\b', doc.get('content', '').lower())
        corpus.append(tokens)
    ...
```

For a session with N turns, `add_document` is called N times, each triggering `_rebuild()` which iterates k docs (k = 1, 2, 3, ..., N). Total iterations: 1+2+...+N = O(N²). For N=1000, that's ~500K iterations just for BM25 rebuilds.

**Note:** The original review's finding #14 flagged this as 🔴 CRITICAL and recommended incremental BM25 update. The `add_document` rename was a step forward, but `_rebuild` is still called on every turn.

**Fix:** Either:
- Only rebuild every Nth turn (e.g., every 10 turns)
- Use a BM25 implementation that supports incremental addition
- Accumulate raw token lists and extend the BM25 corpus without full rebuild

---

#### 🟠 Issue #5: `search_all_sessions` accesses `self.chroma_col` without None check

`manager.py:768-789`:
```python
async def search_all_sessions(self, query: str, top_k: int = 10) -> List[Dict]:
    ...
    try:
        results = self.chroma_col.query(   # chroma_col could be None!
```

When ChromaDB is unavailable (`_HAS_CHROMADB = False`), `self.chroma_col = None`. The `query()` call would raise `AttributeError: 'NoneType' object has no attribute 'query'`. The inner `try/except` catches this (line 786), but it's an accidental fix — the code was not designed to handle None.

Same issue in `clear()` (line 874: `self.chroma.delete_collection(...)`) — though `clear()` has an early return at line 868-869 if `self.chroma is None`.

**Fix:** Add explicit `if self.chroma_col is None: return []` guard.

---

### 🟡 MEDIUM (8)

#### 🟡 Issue #6: `hasattr(self.memory, ...)` dead code in `base.py` and `basic_agent.py`

`base.py:96-98`:
```python
"session_id": (
    getattr(self.memory, 'get_current_session', lambda: '')()
    if hasattr(self.memory, 'get_current_session')
    else ''
),
```

`basic_agent.py:149-152` (same pattern) and `basic_agent.py:197`:
```python
if hasattr(self.memory, "get_session_messages"):
```

`self.memory` is injected via `BaseAgent.__init__` and for all practical purposes is a `Memory` instance, which always has both methods. The `hasattr`/`getattr` guards are dead code that obscure the real type. The original review's finding #47 (agent/core.py line 237) was fixed, but the same pattern persists in two other files.

**Fix:** Remove `hasattr` guards and call methods directly.

---

#### 🟡 Issue #7: `vault._build_vault_section` path traversal check doesn't resolve `VAULT_DIR`

`context_builder.py:128-131`:
```python
vault_path = str(Path(vault_path).resolve())
if not vault_path.startswith(str(VAULT_DIR)):   # VAULT_DIR not resolved
```

The code resolves `vault_path` to resolve symlinks, but compares against unresolved `str(VAULT_DIR)`. If `VAULT_DIR` itself contains a symlink (e.g., `/data/vault → /mnt/storage/vault`), the comparison fails open — a path like `/mnt/storage/vault/../other_dir/../../etc/passwd` could bypass the check because `str(VAULT_DIR)` is `/data/vault` (unresolved) but the resolved path starts with `/mnt/storage/vault`.

**Fix:** Resolve both paths before comparing:
```python
vault_dir_resolved = str(Path(VAULT_DIR).resolve())
if not vault_path.startswith(vault_dir_resolved):
```

---

#### 🟡 Issue #8: Unhandled exceptions from `_fts.index_message` and `ep.add_episode` in `add_turn`

`manager.py:525,529`:
```python
self._fts.index_message(session_id, msg_id, role, content, timestamp)
...
ep.add_episode({"role": role, "content": content, "timestamp": timestamp})
```

Neither call is wrapped in `try/except`. If:
- FTS SQLite encounters a lock error or corruption → `OperationalError` propagates
- Episodic ChromaDB is unavailable → exception propagates

The message was already persisted to disk (line 490), but the exception would crash `add_turn`, preventing background summarization from being scheduled.

**Fix:** Wrap both in `try/except` with `logger.warning` (similar to the ChromaDB `add` call at line 517):
```python
try:
    self._fts.index_message(...)
except Exception as e:
    logger.warning(f"FTS index failed: {e}")
```

---

#### 🟡 Issue #9: `context_builder._build_vault_section` uses hardcoded Groq provider prefix

`context_builder.py:147`:
```python
model = f"groq/{model_raw}" if provider == "groq" and not model_raw.startswith("groq/") else model_raw
```

This Groq-specific prefix hack is hardcoded inside the vault section builder. If other providers need similar prefix logic (e.g., `openai/gpt-4`), each would need a separate conditional. This couples provider-specific logic into a generic context builder method.

**Fix:** Move provider-specific model name normalization to the settings layer or LLM router.

---

#### 🟡 Issue #10: `semantic._rebuild_bm25` imports `rank_bm25` inside the method on every rebuild

`semantic.py:86`:
```python
def _rebuild_bm25(self) -> None:
    ...
    from rank_bm25 import BM25Okapi
```

This import runs on every BM25 rebuild. Since `BM25Okapi` is already used elsewhere (in `hybrid.py` which imports at module level with a fallback), the re-import is redundant and adds a small overhead.

**Fix:** Import at module level with `try/except ImportError` (matching `hybrid.py`'s pattern).

---

#### 🟡 Issue #11: `store_semantic_fact` is synchronous but does I/O — blocks event loop from async context

`manager.py:655-657`:
```python
def store_semantic_fact(self, content: str, metadata: Optional[Dict] = None) -> str:
    return self._semantic.add_fact(content, metadata)
```

`add_fact` → `_save()` which writes a file atomically but synchronously. If called from async context (e.g., from `handle_user_input` flows), this blocks the event loop. There's no async variant or executor delegation.

**Fix:** Provide an async wrapper or use `loop.run_in_executor`.

---

#### 🟡 Issue #12: `context_builder` module-level `UserProfile()` singleton loads at import time

`context_builder.py:14`:
```python
_user_profile = UserProfile()  # module-level singleton
```

This is evaluated when `context_builder` is first imported. If `UserProfile.__init__` depends on settings that are configured later, it could load with stale/default data. The original review flagged this (#56), and it remains.

**Fix:** Use lazy initialization inside `_build_user_profile_section()`.

---

### ⚪ LOW (3)

#### ⚪ Issue #13: `BasicAgent.load_history` double-decodes `get_session_messages` return

`basic_agent.py:200-202`:
```python
msgs = self.memory.get_session_messages(session_id)
if asyncio.iscoroutine(msgs):
    msgs = await msgs
```

`get_session_messages` is a synchronous method (not async). The `iscoroutine` check is dead code — it will never be a coroutine. This masks the actual type and adds an unnecessary branch.

**Fix:** Remove the coroutine check.

---

#### ⚪ Issue #14: `vault.inject_to_context` approximates token budget with `max_tokens * 4` char estimate

`vault.py:348`:
```python
chars_budget = max_tokens * 4
```

Uses a fixed 4:1 character-to-token ratio, which varies by language (Chinese: ~1:1, code: ~2:1, English: ~3-5:1). This could over- or under-fill the actual token budget.

**Fix:** Use `estimate_tokens` from `backend.core.utils.tokens` to check the actual token count while building.

---

#### ⚪ Issue #15: `FACTCache._make_key` truncates SHA256 hash to 16 hex chars (64 bits)

`cache.py:28-29`:
```python
def _make_key(self, text: str) -> str:
    normalized = text.lower().strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]
```

SHA256 produces 256 bits. Truncating to 64 bits (16 hex chars) raises the collision probability. For a cache with 10⁶ entries, collision probability approaches ~10⁻⁷ (birthday bound ≈ 2^(n/2) = 2^32 ≈ 4B entries). For smaller caches (hundreds to thousands), risk is negligible. Minor concern, but truncating to at least 12 chars (48 bits) would be safer.

---

## 3. CROSS-CUTTING CONCERNS

### 3.1 `threading.Lock` vs `asyncio.Lock` Confusion

The codebase mixes `threading.Lock` and `asyncio.Lock` in complex ways:

| Lock | Purpose | Used In |
|------|---------|---------|
| `threading.Lock` | Per-session data protection | `manager.py:_session_locks` |
| `threading.Lock` | Session locks dict protection | `manager.py:_session_locks_lock` |
| `asyncio.Lock` | Summarization mutual exclusion | `manager.py:_summarize_lock` |
| `threading.Lock` | Session index access | `session_index.py:_lock` |
| `threading.Lock` | FACTCache access | `cache.py:_lock` |

When `threading.Lock` is used inside `async def` with `with lock:`, the event loop thread is blocked for the duration of the lock. This violates the async contract and can cause latency spikes.

**Affected methods:** `add_turn` (lines 464-490), `rename_session` (428-436), `delete_message` (663-680), `_prune_tool_outputs` (799-811), `check_and_summarize` final write (855-863).

### 3.2 `asyncio.create_task` Usage for Background Work

`manager.py:520` creates a fire-and-recall task:
```python
asyncio.create_task(self._safe_summarize())
```

This is fine for fire-and-forget, but:
- No reference is kept — the task is uncancellable and invisible to `asyncio.all_tasks()`
- On `shutdown()`, running tasks are abandoned
- Multiple summarization tasks can queue up (see #48 analysis)

Consider using a task group or tracking pending tasks for graceful shutdown.

### 3.3 `rename_session` Calls `get_sessions()` Inside Per-Session Lock

`manager.py:423-436`:
```python
async def rename_session(...):
    all_sessions = self.get_sessions()   # Reads all session files
    ...
    lock = self._get_session_lock(session_id)
    with lock:
        data = self._read_sync(session_id)
```

`get_sessions()` (line 538) iterates the session index and reads files. This happens BEFORE the lock is acquired, so it's not a concurrency issue. But `get_sessions()` is called from `rename_session` which is already potentially slow due to the lock pattern. Not a bug, but worth optimizing.

---

## 4. UNRESOLVED ISSUES FROM ROUND 1 (Intentional)

The following issues from the original review were noted but not addressed. They are either by design, out of immediate scope, or acceptable for the current architecture:

1. **`api/ws/handler.py:131`** — `pending_tasks` unbounded growth (out of scope)
2. **`api/routes/memory.py:31,41,47`** — Deprecated endpoints still live (out of scope)
3. **`api/ws/handler.py:428-429`** — `_handle_avatar_signal` swallows exceptions (out of scope)
4. **`context_builder.py:276`** — Skills injected via `to_prompt_injection()` (by design)
5. **`agent/core.py:128-132`** — Duplicate token estimation logic (acceptable for now)
6. **`session_index.py:13`** — `_index` grows unbounded (acceptable, entries are small)
7. **`manager.py:28`** — `get_recent` modifies `_working.capacity` as side effect (documented)

---

## 5. SUMMARY

| Severity | This Review | Previous Review (verified) |
|----------|-------------|---------------------------|
| 🔴 CRITICAL | 2 new | 4 (all fixed) |
| 🟠 HIGH | 3 new | 18 (16 fixed, 2 partial) |
| 🟡 MEDIUM | 8 new | 36 (28 fixed, 3 partial, 2 not fixed) |
| ⚪ LOW | 3 new | 5 (all fixed) |
| **Total new** | **16** | Previously 63 (53 fully fixed) |

### Top 3 Must-Fix Items

1. **🔴 `start_session()` called without `await` in 8 locations** — Data loss: session data is never written to disk. Every `/new`, `/clear`, and sub-agent creation is broken. Silently returns coroutine objects to callers.

2. **🔴 Cache key collision in `retrieve_for_context`** — All sessions in the same calendar month share cache entries. Cross-session data leakage. Fix: use full session_id in cache key.

3. **🟠 `threading.Lock` in async context blocks event loop** — 5 methods synchronously block the event loop while holding locks. Performance and latency issue.

---

## Appendix A: Files with `hasattr(self.memory, ...)` dead code

```bash
grep -rn 'hasattr.*memory' backend/core/agent/
backend/core/agent/base.py:97:            if hasattr(self.memory, 'get_current_session')
backend/core/agent/basic_agent.py:150:                if hasattr(self.memory, 'get_current_session')
backend/core/agent/basic_agent.py:197:        if hasattr(self.memory, "get_session_messages"):
```

## Appendix B: Files calling `start_session()` without `await`

```bash
grep -rn '\.start_session()' backend/ --include='*.py' | grep -v test | grep -v '.pyc'
backend/api/routes/memory.py:66:    memory().start_session()
backend/api/routes/memory.py:79:    sid = memory().start_session()
backend/api/ws/handler.py:607:            sid = memory().start_session()
backend/api/ws/handler.py:612:            sid = memory().start_session()
backend/cli/companion.py:155:        self._memory.start_session()
backend/cli/companion.py:159:        sid = self._memory.start_session()
backend/core/agent/core.py:110:            sub_memory.start_session()
backend/core/startup.py:46:        memory.start_session()
```

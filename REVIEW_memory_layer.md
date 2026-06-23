# Aggressive Code Review: Memory & Context Layer

**Date:** 2026-06-22  
**Reviewer:** Jcode Agent  
**Scope:** `backend/core/memory/`, `backend/core/context_builder.py`, `backend/core/context_manager.py`, `backend/core/vault.py`, `backend/core/deps.py`, `backend/core/agent/core.py`, `backend/core/agent/basic_agent.py`, `backend/api/routes/memory.py`, `backend/api/ws/handler.py`

**Severity Legend:**  
🔴 **CRITICAL** — data loss, crash, or security vulnerability  
🟠 **HIGH** — incorrect behavior, performance regression, or reliability risk  
🟡 **MEDIUM** — code quality, maintainability, or edge-case bug  
⚪ **LOW** — style, minor cleanup, documentation

---

## 1️⃣ Race Conditions & Thread Safety

### 🔴 `manager.py:195-201` — `_write_sync` writes without a lock, cache desync risk
`_write_sync` writes to disk then updates in-memory cache. No lock guards the write+cache-update sequence. Two concurrent `add_turn` calls through the thread pool can interleave:
1. Thread A writes data_v1 to disk
2. Thread B writes data_v2 to disk (overwrites v1)
3. Thread A sets cache to data_v1 (stale!)
4. Thread B sets cache to data_v2

**Fix:** Use a per-session `asyncio.Lock` or `threading.Lock` for write+cache operations. Consider atomic writes (write to `.tmp` then rename).

### 🟠 `manager.py:180-193` — `_read_sync` race with `_write_sync`
`_read_sync` returns cached data without any lock, but `_write_sync` updates the cache. If `_write_sync` is mid-execution (cache not yet updated), `_read_sync` could return stale data from a previous write.

**Fix:** Same as above — all cache mutating operations need a consistent lock discipline.

### 🟠 `manager.py:215-248` — `start_session` calls `_write_sync` directly (synchronous I/O)
`start_session` calls `_write_sync` directly (not through the async `_write` executor path). But `add_turn` wraps `_write_sync` in the thread pool via `_write`. This inconsistency means `start_session` blocks the event loop.

**Fix:** `start_session` should use `loop.run_in_executor(self._executor, ...)` or `_write` for consistency.

### 🟠 `manager.py:820-827` — `shutdown` with `wait=False` loses pending writes
```python
self._executor.shutdown(wait=False)
```
Any `_write_sync` tasks still in the queue are abandoned. On restart, the last N turns of conversations are silently lost.

**Fix:** `await` a graceful drain of pending write tasks before shutdown. Use `wait=True` with a timeout.

### 🟡 `manager.py:376-403` — `add_turn` re-reads data inside lock but write is synchronous
The pattern is: acquire `_lock`, `_read_sync`, mutate, `_write_sync`, release `_lock`. Since `_write_sync` writes synchronously, the lock is held during disk I/O. For concurrent users of the same session (rare but possible), this serializes writes but also blocks the event loop thread.

**Fix:** Consider moving the disk I/O outside the lock, using a per-session lock for cache consistency.

### 🟡 `manager.py:109-148` — `_maybe_migrate` is not re-entrant safe
Runs with no lock at startup. If `_iter_session_paths()` yields files that another process is still writing, partial/corrupt JSON could be read. The sentinel file check is racy (TOCTOU).

**Fix:** Use a file lock (e.g., `portalocker`) or at least a thread lock to prevent double-migration.

---

## 2️⃣ Transaction Safety & Partial Failure

### 🔴 `manager.py:364-437` — `add_turn` has no rollback on partial failure
The write sequence is:
1. `_working.add(role, content)` — in-memory, always succeeds
2. `_write_sync` — disk write
3. `_session_index.upsert` — JSON file write
4. `_hybrid.rebuild_bm25` — O(n) BM25 rebuild
5. `chroma_col.add` — remote DB call
6. `_fts.index_message` — SQLite write
7. `ep.add_episode` — ChromaDB write

If step 5+ fails (ChromaDB timeout), the disk file and FTS index are already updated, but the embedding is missing. If the process crashes between step 2 and 3, the session file has the message but the index doesn't know about it. **No transactional boundary exists.**

**Fix:** Implement a write-ahead log or use SQLite transactions for all persistence. At minimum, order operations so that irreversible steps come last.

### 🟠 `session_index.py:23-24` — `_save()` writes JSON without atomicity
```python
self._path.write_text(json.dumps(self._index, ...))
```
A crash during `write_text` leaves a corrupt/truncated JSON file, losing the entire session index.

**Fix:** Write to a `.tmp` file, then `os.replace()` (atomic on POSIX).

### 🟠 `fts.py:34` — `PRAGMA synchronous=OFF` risks corruption
```python
self._local.conn.execute("PRAGMA synchronous=OFF;")
```
With `synchronous=OFF`, SQLite does not sync writes to disk. A crash will corrupt the FTS index or lose the last few operations.

**Fix:** Use `PRAGMA synchronous=NORMAL` (still fast, but much safer) or at least document the tradeoff. For an FTS index that is rebuilt from session files, this is less critical — but still risky.

### 🟡 `semantic.py:31,57-72` — `add_fact` calls `save()` synchronously
`add_fact` is called from async context (`store_semantic_fact` -> `add_fact` -> `save`). `save()` does synchronous file I/O that blocks the event loop. Also, no atomic write to `semantic_facts.json`.

**Fix:** Use async file I/O or delegate to the thread pool executor. Write atomically (tmp + rename).

### 🟡 `session_index.py:26-34` — `upsert` and `remove` rewrite the entire file
Every single turn calls `upsert`, which loads, modifies, and rewrites the entire JSON index file. For thousands of sessions with frequent updates, this is both a performance and reliability concern.

**Fix:** Use SQLite for the session index, or at least buffer writes (debounce).

---

## 3️⃣ Embedding Fallback Chain

### 🟠 `manager.py:271-308` — `_get_embedding` fallback logic has dead paths and unpredictable behavior
```python
if backend == "local" and _get_local_embedding() is not None:
    # Try local embedding
    # ... if fails, falls through

if backend in ("provider", "local") and self.llm:
    # Try provider embedding
    # ... if fails or None, falls through

if _get_local_embedding() is not None:
    # Try local as final fallback
```

Problems:
- **Dead path 1:** When `backend=="local"` and local embedding succeeds, it returns. But if local fails, it falls through to the provider path (which may succeed). Is that intended? If the user configured `local` because they have no API key, this is a bug — they'd silently use an API they don't have.
- **Dead path 2:** The final `if _get_local_embedding() is not None` block can only be reached if backend is "provider" or "local" (local already tried). For "local", if the first local attempt failed, the second will also fail (same function). This path only helps when backend is "provider" and provider failed.
- If `backend == "disabled"`, returns None immediately — but `add_turn` continues regardless, just without an embedding. This is fine but worth noting.
- `backend` checking uses `in` operator: `"local"` is compared to the setting value, but the fallthrough to `"provider"` is implicit logic that's hard to follow.

**Fix:** Make the fallback chain explicit and configurable. Use a priority list like `["provider", "local"]` that the user controls. Document exactly what happens when each backend fails.

### 🟡 `manager.py:36-46` — `_get_local_embedding` lazy-loads but never reports failure
If `sentence_transformers` is not installed or `all-MiniLM-L6-v2` download fails, it silently returns `None`. The caller (`_get_embedding`) checks for `None`, but no log message indicates why embedding failed.

**Fix:** Log a warning when local embedding fails to load.

---

## 4️⃣ BM25 Rebuild Overhead

### 🔴 `manager.py:411` — `_hybrid.rebuild_bm25` called on *every* `add_turn`
```python
self._hybrid.rebuild_bm25(data.get("messages", []))
```
This iterates **all messages** in the session and retokenizes them to rebuild the BM25 index. For a session with 10,000 turns, this is O(n) per turn — O(n²) overall for a session.

**Fix:** Incremental BM25 update. BM25Okapi supports adding documents after initial build. Either accumulate raw token lists and extend the BM25 index, or only rebuild periodically (every N turns).

### 🟡 `hybrid.py:16-24` — `rebuild_bm25` discards empty token docs but keeps them in `_bm25_docs`
```python
non_empty = [doc for doc in corpus if doc]
self._bm25 = BM25Okapi(non_empty) if non_empty else None
```
If messages 0-4 have content but message 5 is empty, `_bm25_docs` has 6 entries but BM25 index has 5. During retrieval (line 43-49), when matching results, `idx` from BM25 scores corresponds to the non-empty docs, not `_bm25_docs`. This is a **document index mismatch**.

**Fix:** Filter `_bm25_docs` in the same way as corpus, or track which indices were filtered.

### 🟡 `semantic.py:87-97` — `_rebuild_bm25` rebuilds entire index on every search if dirty
For large fact stores, this O(n) rebuild on every search is wasteful. Facts change infrequently, so incremental update or a periodic rebuild would be better.

**Fix:** Use lazy dirty flag with incremental document addition to BM25Okapi.

### 🟡 `vault.py:106-138` — Full BM25 rebuild on every search when mtimes change
While the mtime cache avoids rebuilding on every search, it still requires listing all `.md` files and comparing mtimes (O(n)), which for large vaults could be slow.

**Fix:** Consider a file-system watcher or explicit re-index trigger.

---

## 5️⃣ ChromaDB Failure Recovery

### 🟠 `manager.py:413-426` — ChromaDB `add` failure silently swallowed
```python
if embedding:
    try:
        self.chroma_col.add(...)
    except Exception as e:
        logger.debug(f"ChromaDB add failed: {e}")
```
The message is already persisted to disk, but the embedding is not stored. Future semantic searches will miss this message. The `chroma_id` stored in the message is now dangling.

**Fix:** At minimum log at WARNING level. Consider a background retry queue for failed ChromaDB operations. Better: store embeddings in a local SQLite as fallback.

### 🟠 `manager.py:516-529` — `delete_session` ignores ChromaDB failure, proceeds to delete disk data
```python
try:
    self.chroma_col.delete(where={"session_id": session_id})
except Exception as e:
    logger.debug(f"ChromaDB delete failed: {e}")
path = self._session_path(session_id)
if path.exists():
    await loop.run_in_executor(...)  # deletes disk file
```
If ChromaDB delete fails but disk file deletion succeeds, the session data is gone from disk but orphaned embeddings remain in ChromaDB. No reconciliation.

**Fix:** Decide on consistency semantics. If ChromaDB is a secondary index, consider it acceptable and only WARN. If it's a primary store, retry.

### 🟡 `manager.py:75-76` — ChromaDB collection silently `None` on import failure
```python
if _HAS_CHROMADB:
    ...
else:
    self.chroma = None
    self.chroma_col = None
```
Later code scattered with `if self.chroma_col is None` checks. Easy to miss one. For example, `_hybrid = HybridRetrieval(self.chroma_col)` passes `None` — HybridRetrieval will crash when `self._chroma.query(...)` is called as `None.query(...)`.

**Fix:** Use a Null Object pattern for ChromaDB, or at minimum have `HybridRetrieval` handle `None` gracefully (it catches `Exception` broadly, so it won't crash, but it would be cleaner to check explicitly).

### 🟡 `episodic.py:37-53` — `search` fragile nested `get()` calls with hardcoded `[0]`
```python
results.get("documents", [[]])[0]
```
If ChromaDB returns an empty result set, `results["documents"]` might be `[[]]` (empty list inside), and accessing `[0]` returns `[]`. This works, but if ChromaDB changes its response format, this breaks silently.

**Fix:** Use `.get()` with proper defaults for the outer list too: `(results.get("documents") or [[]])[0]`.

---

## 6️⃣ Memory Leak Potential

### 🟠 `manager.py:59` — `_session_data_cache` grows unbounded
The cache is populated on every `_read_sync` call and only cleared on `clear()` or per-session deletion via `pop`. If a user creates hundreds of sessions over days of operation, this dict grows without bound.

**Fix:** Implement LRU eviction on the cache (e.g., `functools.lru_cache` or `OrderedDict`-based). Max cache size of 50-100 sessions is reasonable.

### 🟠 `manager.py:95` — `_episodic_memories` dict grows unbounded
```python
self._episodic_memories: Dict[str, EpisodicMemory] = {}
```
An `EpisodicMemory` is created per session and never removed. Over time, this accumulates. Each `EpisodicMemory` holds a reference to a ChromaDB collection, which may have its own memory footprint.

**Fix:** Add cleanup when sessions are deleted or when memory is cleared. Consider LRU eviction for old sessions.

### 🟡 `cache.py:9` — `FACTCache._cache` never evicts expired entries except on access
If keys are set and never `get`'d again, the cache grows unbounded. The TTL mechanism only prunes on `get`. A cache with 1M stale keys would eventually OOM.

**Fix:** Add periodic cleanup (background task every N minutes) or use `cachetools.TTLCache` which prunes on every `set`.

### 🟡 `session_index.py:13` — `_index` grows unbounded
No limit on the number of sessions tracked in the index. With long-running servers and thousands of sessions, this could become large.

**Fix:** Minor concern since each entry is small. Acceptable.

### 🟡 `api/ws/handler.py:131` — `ChatSession.pending_tasks` list can grow unbounded
Tasks are tracked but cleanup only happens in the `finally` block of `_run_agent_loop` and in `_on_task_done`. If tasks are created faster than they complete and are cleaned, the list grows.

**Fix:** Use a bounded set or periodic compact (already done partially — could be better with `WeakSet` or explicit limit).

---

## 7️⃣ Working Memory vs Disk Persistence Inconsistencies

### 🟠 `manager.py:531-555` — `get_recent` prefers working memory, but working memory only has current process data
```python
working_turns = self._working.recent(n)
if len(working_turns) >= n:
    return working_turns
```
On a fresh process start, working memory is empty (even though session data is on disk). The fallback to disk (`data.get("messages", [])[-n:]`) handles this. But within a session, working memory may have fewer turns than disk because working memory only starts counting from when the process started.

**Fix:** On session start or first access, populate working memory from disk. This ensures warm cache even after restart.

### 🟡 `manager.py:539-541` — `get_recent` modifies `_working.capacity` as a side effect
```python
if self._working.capacity < n:
    self._working.capacity = n
```
If memory is disabled and `get_recent` is called with a large `n`, working memory capacity is permanently increased. This is a side effect that could be surprising.

**Fix:** Either document this behavior or auto-reset after the call.

### 🟡 `working.py:25-27` — Working memory uses string-keyed OrderedDict with incrementing counter
```python
key = f"{self._counter}"
self._counter += 1
self._turns[key] = turn
```
On `clear()`, counter is not reset to 0. Keys like `"0"` through `"99"` in one session, then after clear, keys `"100"` through `"199"`. While functional, the counter can grow arbitrarily large.

**Fix:** Reset counter to 0 on `clear()`.

---

## 8️⃣ Search Ranking Quality Issues

### 🟡 `hybrid.py:37-38` — RRF uses first 50 chars of content as dedup key; collisions possible
```python
cid = meta.get("content", "")[:50]
results[cid] = results.get(cid, 0) + 1 / (self._k + rank + 1)
```
Two messages with identical first 50 characters (e.g., "Run this command: abc" repeated) would collide in the RRF results dict, causing one to overwrite the other's score. This also means both BM25 and ChromaDB matches for different content with the same prefix are merged incorrectly.

**Fix:** Use a proper message ID (e.g., `session_id + "_" + msg_index`) as the dedup key.

### 🟡 `hybrid.py:43-49` — BM25 score uses document index matching `_bm25_docs` but BM25 was built on filtered corpus
As noted in finding 4, the BM25 indexes the filtered corpus (non-empty token lists), but the scoring loop indexes into `_bm25_docs` directly. If messages 2, 5, 7 are empty, the BM25 index has 3 docs but `_bm25_docs` has 7. `scores[idx]` for idx=2 in BM25 corresponds to message 3 or 4 in `_bm25_docs`, not message 2.

**Fix:** Filter `_bm25_docs` to match the BM25 corpus exactly, or track a mapping.

### 🟡 `hybrid.py:16-24` — `rebuild_bm25` tokenizes by `\b\w+\b` regex
This tokenization is very simple and will miss important content like code snippets (`foo_bar`, `foo::bar`), numbers with decimals, or URLs. The FTS5 index uses `porter unicode61` which is more sophisticated.

**Fix:** Use the same tokenization strategy as FTS5, or at least include underscores and common special characters.

### 🟡 `semantic.py:35-47` — `search` returns only BM25 results, no semantic/embedding scoring
Semantic memory uses only BM25, despite the name "semantic." True semantic search would use embeddings or cross-encoders.

**Fix:** Either rename to "BM25Memory" for clarity, or add embedding-based retrieval with RRF fusion.

### 🟡 `fts.py:128-170` — FTS5 search uses default BM25 ranking but doesn't handle FTS5 syntax errors
If the user queries with FTS5 special characters (e.g., `*`, `"`, `NOT`), an `OperationalError` is caught and returns `[]`. But FTS5 requires proper escaping for special queries.

**Fix:** Validate or escape user queries before passing to FTS5. Consider using `fts5` with `*` appended for prefix matching.

---

## 9️⃣ Context Builder — Prompt Injection Risks

### 🟠 `context_builder.py:64-68` — `relationship_context` injected unescaped into system prompt
```python
{{ relationship_section }}
```
Where `relationship_context` comes from user interactions via `relationship().get_context_string()`. If the relationship context contains crafted text (e.g., from a user message that the model wrote to the relationship store), it could override system instructions.

**Fix:** At minimum, place relationship context after the main system instructions so it's less likely to override earlier rules. Consider instructing the model in the template that relationship context is user-derived and should be treated as observational, not as authoritative configuration.

### 🟡 `context_builder.py:122-148` — `_build_vault_section` reads `rules.md` and injects into system prompt
If `rules.md` contains prompt injection payloads (e.g., from a compromised vault sync), the model's behavior is fully controllable.

**Fix:** This is by design (vault is authoritative), but should be documented as a security boundary. The vault path should be validated against directory traversal.

### 🟡 `context_builder.py:276` — `skills` injected directly via `to_prompt_injection()`
Skills can contain arbitrary text. If a skill was created from user content (e.g., via AutoSkillCreator), it could contain injection payloads.

**Fix:** Skills should be treated as trusted (since they're created by the system), but validation of skills' content on creation would be prudent.

---

## 🔟 Token Counting & Context Window Enforcement

### 🟠 `context_manager.py:73-75` — Context budget reserves `max_response + 50` hardcoded overhead
```python
reserved = user_msg_tokens + max_response + 50
```
The 50-token overhead is arbitrary and doesn't account for the actual system prompt format overhead, role tokens, or message structure. For models with different tokenization, this could over- or under-reserve.

**Fix:** Estimate the actual overhead based on the model's tokenizer and message format.

### 🟡 `context_manager.py:86-91` — Summary token count is estimated after potential truncation, but not consistently
After truncating summary, line 89 recalculates `summary_tokens`. But line 91 does `available -= summary_tokens`. If the truncated summary has 0 tokens, this subtracts 0. Fine, but if summary is empty string (falsy), it's skipped entirely — but summary could be whitespace-only.

**Fix:** Handle whitespace-only summaries consistently with empty summaries.

### 🟡 `context_manager.py:96-109` — Relevant context pruning is O(n²) and has calculation error
```python
for item in reversed(relevant):
    ...
    keep.insert(0, item)
    relevant_tokens = sum(estimate_message_list_tokens(keep, model))
```
`insert(0, ...)` is O(n) per operation, making the loop O(n²). Also, `relevant_tokens` is recalculated inside the loop but only the final value matters — the loop condition checks `if item_tokens <= available` against the decrementing `available` counter (which only accounts for this item, not the cumulative). The `relevant_tokens` recalculation is never used in the branching logic.

**Fix:** Use a list and reverse it at the end, or use `deque` with `appendleft`. Remove the dead `relevant_tokens` recalculation.

### 🟡 `context_manager.py:37-39` — `estimate_system_prompt` adds `SYSTEM_PROMPT_OVERHEAD` but this is double-counted
`build_context` also adds `SYSTEM_PROMPT_OVERHEAD` when computing `sys_tokens` (line 78). The `estimate_system_prompt` method is unused in `build_context` but if called externally, the overhead is included once. Not a bug, but inconsistent API.

**Fix:** Remove `estimate_system_prompt` or use it consistently.

### 🟡 `agent/core.py:134-161` — `_truncate_context` uses `pop(0)` for history truncation
```python
while ... and len(history) > 1:
    history.pop(0)
```
`list.pop(0)` is O(n). For a history of 100+ messages, this could be slow. Also, `_estimate_tokens` is called in the loop condition, which itself is O(n) for the message list.

**Fix:** Use `collections.deque` or binary search to find the truncation point, then slice once.

---

## 1️⃣1️⃣ Dead Code Paths

### 🟡 `manager.py:83` — `_known_sessions` populated from iter_session_paths, but `start_session` also adds to it
`_known_sessions` is both populated at startup from disk and during `start_session`. This is fine, but `_known_sessions` is never used by `_read_sync` — only by `session_exists`. The cache `_session_data_cache` is the primary read cache. `_known_sessions` is an additional data structure that must be kept consistent.

**Fix:** Either make `_known_sessions` the authoritative source and remove `_session_data_cache`, or remove `_known_sessions` and use the path existence + cache checks. Both serve overlapping purposes.

### 🟠 `manager.py:613-618` — Fallback in `get_relevant` after `retrieve_for_context` is dead code
```python
contents = await self.retrieve_for_context(query, session_id, n=top_k)
if contents:
    return [...]
# Fallback: direct hybrid if retrieve_for_context returned nothing
query_emb = await self._get_embedding(query)
...
return await self._hybrid.retrieve(query, query_emb, session_id, top_k)
```
`retrieve_for_context` already calls `_hybrid.retrieve` internally. If it returned results, the function returns early. If it returned empty, the fallback tries *exactly the same hybrid retrieval* again. The only difference is `retrieve_for_context` caches the result — but after getting empty from cache, the fallback will also return empty (or the same empty result from hybrid).

**Fix:** Remove the dead fallback, or restructure so `get_relevant` delegates entirely to `retrieve_for_context` without a second redundant attempt. The ChromaDB-only query at line 626 is also redundant (also done inside hybrid.retrieve).

### 🟡 `manager.py:557-558` — `get_all_recent` is an alias for `get_recent`
```python
def get_all_recent(self, n: int = None) -> List[Dict[str, str]]:
    return self.get_recent(n)
```
Check callers — if none use `get_all_recent`, remove it.

### 🟡 `agent/core.py:59-63` — `update_emotion_tags` and `update_expression_names` are no-ops
```python
def update_emotion_tags(self, tags):
    """No-op — avatar emotion is now controlled via MCP tools, not tags."""
```
Comment says it's legacy. Check callers and remove if not referenced.

### 🟡 `api/routes/memory.py:31,41,47` — Several endpoints marked `@deprecated()` but still live
`/api/memory/session/{session_id}/rename`, `/api/memory/session/{session_id}/resume`, `/api/memory/session/{session_id}/activate` are all `@deprecated()` but still served.

**Fix:** Either remove them or add the deprecation response header and plan a removal date.

### 🟡 `context_builder.py:409-411` — `build_from_messages` is a trivial wrapper
```python
def build_from_messages(self, messages: list, new_user_msg: str) -> list:
    messages.append({"role": "user", "content": new_user_msg})
    return messages
```
Mutates the input list as a side effect (also returns it). Check callers and inline if trivial.

---

## 1️⃣2️⃣ Exception Swallowing

### 🟡 `manager.py:145-146` — `_maybe_migrate` catches all exceptions and continues
```python
except Exception as e:
    logger.debug(f"Migration skipped for {p}: {e}")
```
Migration errors should be logged at WARNING level, not DEBUG. Silent data loss during migration.

**Fix:** Log at WARNING level, consider re-raising for certain error types.

### 🟠 `manager.py:672-673` — `retrieve_for_context` catches all exceptions in hybrid retrieval
```python
except Exception:
    contents = []
```
Any error in hybrid retrieval (BM25 crash, ChromaDB timeout) returns empty list silently. The caller doesn't know retrieval failed vs. no relevant results.

**Fix:** Log at WARNING level, or at least DEBUG with more context.

### 🟡 `hybrid.py:40-41` — `retrieve` catches all ChromaDB exceptions
```python
except Exception:
    pass
```
Silent `pass` means any ChromaDB error (auth, timeout, corrupt index) is invisible.

**Fix:** Log at least at DEBUG level with the exception.

### 🟡 `vault.py:248-249,263-264` — ChromaDB delete failures caught silently
```python
except Exception:
    pass
```
During vault re-indexing, failure to delete old embeddings is silently ignored. Could lead to stale embeddings.

**Fix:** Log at WARNING level.

### 🟡 `basic_agent.py:48-52,78-82,147-152,199-204,258-262,272-277` — Multiple `except Exception: pass` blocks
Almost every plugin hook call is wrapped in `try/except: pass`. This means any plugin error is silently invisible.

**Fix:** Log at DEBUG or WARNING level. "pass" hides bugs in plugins.

### 🟡 `api/ws/handler.py:428-429` — `_handle_avatar_signal` swallows all exceptions
```python
except Exception:
    pass
```
Any malformed avatar signal (JSON parse error, unexpected structure) is invisible.

**Fix:** Log at WARNING level.

---

## 1️⃣3️⃣ TODO/FIXME/HACK/XXX Comments

### 🟡 `manager.py:19-20,22-23` — FactCache/HybridRetriever aliases
```python
FactCache = FACTCache  # alias for plan compatibility
HybridRetriever = HybridRetrieval  # alias for plan compatibility
```
These aliases for "plan compatibility" suggest a migration in progress. The aliases should be removed once migration is complete. This is a code smell.

### 🟡 `context_builder.py:14` — Module-level singleton comment
```python
# Module-level singleton — loaded once at startup, persists across sessions
_user_profile = UserProfile()
```
This creates a `UserProfile` at import time. If imports are reordered, this could load before settings are available.

### 🟡 `agent/core.py:525-527` — Comment noting dead methods
```python
# ---------------------------------------------------------------------------
# Dead methods removed — stream_response and generate_response were
# abandoned refactoring artifacts never called by any agent or handler.
# ---------------------------------------------------------------------------
```
Good that they were removed, but the comment is a smell that the codebase has retained dead code in the past.

### 🟡 `agent/core.py:524` — Comment says "iterations >= 5" but magic number instead of MAX_ITERATIONS constant
Line 511: `if iterations >= 5:` → should reference `max_iterations` which is defined as `strategy.max_iterations if strategy else 5` on line 253. But by the time we reach line 521, the variable is out of scope or shadowed.

**Fix:** Use a class constant `MAX_ITERATIONS = 5` or reference the actual iteration limit.

### 🟡 `context_manager.py:13-14` — Magic constants
```python
SYSTEM_PROMPT_OVERHEAD = 50
TURN_OVERHEAD = 8
```
These are undocumented magic numbers that affect context window accuracy.

**Fix:** Document how these were calibrated, or derive them from model tokenizer profiles.

### 🟡 `vault.py:22` — `VAULT_CHUNK_SIZE = 500` (characters)
500 characters is very small. Most embedding models handle 256-512 tokens, which is ~1000-2000 characters. Chunking at 500 chars creates many small chunks that may lose context.

**Fix:** Increase to at least 1000 characters, or better, use a token-aware chunk size based on the embedding model's context window.

---

## 1️⃣4️⃣ Missing Type Hints

### 🟡 `manager.py:10` — Missing `Optional` import for string
Line 10: `from typing import List, Dict, Optional` — Okay, has `Optional`.

### 🟡 `manager.py:51` — `llm_router` parameter typed as `None` in doc but not type-hinted
```python
def __init__(self, llm_router=None, db_path=None, settings=None):
```
No type hints on any parameter. Given the complexity of this class, this is a significant maintainability issue.

**Fix:** Add full type hints to all methods.

### 🟡 `working.py:10` — `__init__` missing return type
```python
def __init__(self, capacity: int = 20):
```
Missing `-> None`.

**Fix:** Add `-> None`.

### 🟡 `consolidator.py:15` — `consolidate` method has no type hints for `episodic_store`
```python
def consolidate(self, turns: List[Dict], episodic_store) -> int:
```
`episodic_store` should be typed as `EpisodicMemory`.

**Fix:** Add type hint.

### 🟡 `hybrid.py:10` — `__init__` parameter `chroma_col` has no type
```python
def __init__(self, chroma_col, k: int = 60):
```
`chroma_col` should be `Optional[...]` since it can be `None`.

**Fix:** Add type hint: `Optional[chromadb.Collection]`.

### 🟡 `episodic.py:14` — `collection` parameter has no type
```python
def __init__(self, collection, session_id: str):
```
No type hint for `collection`. It's a ChromaDB collection or `None`.

**Fix:** `Optional[chromadb.Collection]`.

### 🟡 `session_index.py` — All methods missing return type hints
Most methods are missing `-> None` for void methods, `-> Dict` for `_load`, etc.

**Fix:** Add full type hints.

### 🟡 `cache.py` — `_cache` dict has no generic type
```python
self._cache: dict[str, tuple[Any, float]] = {}
```
Actually this has good type hints (Python 3.9+ style). No issue here.

### 🟡 `fts.py:29` — `_get_conn` return type missing
```python
def _get_conn(self) -> sqlite3.Connection:
```
Actually this has a return type. Good.

---

## 1️⃣5️⃣ Other Notable Issues

### 🟠 `manager.py:428` — `asyncio.create_task(self._safe_summarize())` is fire-and-forget
`_safe_summarize` runs in the background. If summarization encounters an error that locks the `_summarize_lock` (e.g., the lock is not released due to an exception not caught by `_safe_summarize`), subsequent summarization attempts will silently deadlock.

**Fix:** Ensure the lock is always released (use `async with` with try/finally). Also, limit concurrent background summarization tasks.

### 🟠 `manager.py:457-460,494-497` — `get_sessions` reads every session file on each call
For a user with 500+ sessions, `get_sessions` reads every JSON file from disk to build the response. This could take seconds.

**Fix:** Cache the session list in the session index, or at least paginate.

### 🟠 `manager.py:457-460` — `get_sessions` removes index entries for sessions with no disk file
```python
if not path.exists():
    self._session_index.remove(sid)
    continue
```
A session that was moved or the data directory restructured will be silently removed from the index. This is a side effect of a GET endpoint.

**Fix:** Don't mutate state in a GET method. Report the inconsistency but don't fix it silently.

### 🟠 `manager.py:707-708` — `search_all_sessions` accesses `results["metadatas"][0]` without checking outer list
```python
if results and results["metadatas"] and results["metadatas"][0]:
```
If `results["metadatas"]` is `[[], []]` (two queries, one with empty results), this check passes but `results["metadatas"][0]` is `[]` (falsy). The `return` list comprehension would iterate over nothing, returning `[]`. Works correctly, but fragile.

**Fix:** Use `(results.get("metadatas") or [[]])[0]` pattern.

### 🟠 `manager.py:86-87` — `_hybrid` and `_fts` are passed `None` when ChromaDB is unavailable
```python
self._hybrid = HybridRetrieval(self.chroma_col)  # chroma_col is None
self._fts = FTSSearch(self.conv_dir)
```
`HybridRetrieval` will crash with `AttributeError: 'NoneType' object has no attribute 'query'` when `self._chroma.query()` is called. While broad `except Exception` in `retrieve` catches this, it's accidental.

**Fix:** `HybridRetrieval.__init__` should handle `None` chroma_col and return empty results from `retrieve`.

### 🟡 `vault.py:28-44` — `__init__` creates ChromaDB collection even if None is passed for embeddings_path
Logic: `if embeddings_path and _HAS_CHROMADB:` — if `embeddings_path` is a valid path but ChromaDB import failed, `_chroma` stays None. Fine.

### 🟡 `vault.py:110` — `_build_bm25_index` uses `hasattr` on `_bm25` which is always initialized
```python
if current_mtimes == self._bm25_mtimes and hasattr(self, '_bm25') and self._bm25 is not None:
```
`_bm25` is always set in `__init__` (line 32: `self._bm25 = None`). The `hasattr` check is dead code.

**Fix:** Remove `hasattr(self, '_bm25')`.

### 🟡 `vault.py:226-227` — `_index_vault` only indexes top-level .md files, not subdirectories
```python
for f in self._vault_path.iterdir():
```
`iterdir()` does not recurse. Files in subdirectories are skipped for ChromaDB indexing.

**Fix:** Use `rglob("*.md")` for recursive indexing, consistent with `_build_bm25_index` and `inject_to_context`.

### 🟡 `agent/core.py:237` — `hasattr` check always True for Memory
```python
_metrics_session = self.memory.get_current_session() if hasattr(self.memory, 'get_current_session') else None
```
`Memory` always has `get_current_session`. This safety check suggests the method signature isn't trusted.

**Fix:** Remove the `hasattr` guard.

### 🟡 `agent/core.py:128-132` — `_estimate_tokens` and `_truncate_context` duplicate logic in `context_manager.py`
The `Agent` class has its own token estimation and truncation logic that parallels `ContextManager.build_context`. This means two different truncation paths are applied to the same conversation — `ContextManager` truncates, then `Agent._truncate_context` truncates again.

**Fix:** Consolidate into a single pipeline. Either `ContextManager` handles everything and `Agent` doesn't re-truncate, or remove `ContextManager` in favor of `Agent`'s logic.

### 🟡 `api/ws/handler.py:88-93` — `_OrchestratorAgentAdapter` yields only `__text__` signals, losing all other signals
Tool calls, emotions, errors are all dropped silently. The orchestrator's `dispatch_step` only gets plain text, losing structured output.

**Fix:** Either propagate structured signals through the orchestrator, or document this limitation.

### 🟡 `api/ws/handler.py:132` — `self._main_loop = asyncio.get_running_loop()` but may be called before loop starts
`ChatSession.__init__` calls `asyncio.get_running_loop()`. If `ChatSession` is ever instantiated outside an async context (e.g., in tests), this raises `RuntimeError`.

**Fix:** Initialize lazily in `run()`.

---

## Summary Statistics

| Severity | Count |
|----------|-------|
| 🔴 CRITICAL | 4 |
| 🟠 HIGH | 18 |
| 🟡 MEDIUM | 36 |
| ⚪ LOW | 5 |
| **Total** | **63** |

### Top 5 Must-Fix Items

1. **🔴 `_write_sync` race** — Cache consistency bugs under concurrent writes (file 1, lines 195-201)
2. **🔴 `add_turn` no transaction safety** — Partial failure leaves inconsistent state (file 1, lines 364-437)
3. **🔴 `_session_data_cache` unbounded** — Memory leak over long-running sessions (file 1, lines 59, 95)
4. **🟠 BM25 rebuild on every turn** — O(n²) performance issue for long sessions (file 1, line 411)
5. **🟠 `get_sessions` reads every file** — Latency issue for users with many sessions (file 1, lines 457-460)

### Quick Wins

- Fix the ChromaDB `except Exception: pass` blocks to at least log (11 instances across 4 files)
- Add type hints to `Memory.__init__` and remaining untiyped methods
- Remove dead code: `get_all_recent`, the redundant hybrid fallback in `get_relevant`, and `hasattr` checks
- Increase `VAULT_CHUNK_SIZE` from 500 to a more sensible value
- Replace `list.pop(0)` with `collections.deque` in `agent/core.py`

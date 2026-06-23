# REVIEW 3 — Memory Layer: Zero-Issue Verification

**Scope:** 12 files across `backend/core/memory/` and `backend/core/`
**Reviewer:** Automated static analysis
**Goal:** Confirm zero actionable issues remain after 17 Round 2 fixes.

---

## Result: 9 findings — 1 medium-high, 3 medium, 5 low

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | 🔴 **MED-HIGH** | `vault.py:18` | Unguarded `rank_bm25` import — crashes if package absent |
| 2 | 🟡 **MEDIUM** | `manager.py:193-199` | `_iter_session_paths()` matches `sessions_index.json`, creating phantom session in fallback path |
| 3 | 🟡 **MEDIUM** | `hybrid.py:57-60` | `rebuild_bm25()` (dead code) doesn't sync `_tokenized_corpus` |
| 4 | 🟡 **MEDIUM** | `manager.py:683-700` | `delete_message()` never calls FTS `remove_message()` — stale FTS entries |
| 5 | 🔵 **LOW** | `episodic.py:18-35` | `add_episode()` discards turn timestamp, generates a new one |
| 6 | 🔵 **LOW** | `context_manager.py:119` | `truncated` list gets duplicate `"relevant_context"` entries when skipping multiple items |
| 7 | 🔵 **LOW** | `manager.py:816` | `search_all_sessions_fts()` accesses private `self._fts._get_conn()` |
| 8 | 🔵 **LOW** | `manager.py` (multiple) | Synchronous `_write_sync`/`_read_sync` I/O inside async methods blocks event loop |
| 9 | 🔵 **LOW** | `vault.py:335-376` | `inject_to_context()` doesn't count formatting overhead tokens |

---

## 🔴 #1 — vault.py: Unguarded `rank_bm25` import (medium-high)

**File:** `backend/core/vault.py`, line 18

```python
try:
    import chromadb
    ...
    _HAS_CHROMADB = True
except ImportError:
    _HAS_CHROMADB = False
from rank_bm25 import BM25Okapi        # <-- NO GUARD
```

`hybrid.py` and `semantic.py` both guard this import:
```python
try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None
```

If `rank_bm25` is missing (or removed in a minimal deployment), importing `vault.py` raises `ModuleNotFoundError`, crashing the module before any code runs. The other two files degrade gracefully.

**Fix:** Wrap the import in try/except:
```python
try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None
```

---

## 🟡 #2 — `_iter_session_paths()` picks up sessions_index.json (medium)

**File:** `manager.py`, lines 193-199

```python
def _iter_session_paths(self):
    seen = set()
    for pattern in ("*/*/*/*.json", "*.json"):
        for p in sorted(self.conv_dir.glob(pattern), ...):
```

The glob `"*.json"` at root level matches `sessions_index.json`. In the `get_sessions()` fallback path (when the in-memory index is empty), this file is parsed as a session file. `_path_to_session_id()` returns `"sessions_index"`, and the file is read via `_read_sync()`. Since `sessions_index.json` is a `dict[str, dict]` (not a session with `"id"`/`"messages"`), a phantom entry appears:

```python
{"id": "sessions_index", "message_count": 0, "preview": "", ...}
```

**Impact:** Low in practice because the index path is preferred, but the fallback pollutes the session list. The cached entry for key `"sessions_index"` also caches the index data structure, not session data.

**Fix:** Skip `sessions_index.json` explicitly:
```python
for p in sorted(...):
    if p.name == SessionIndex.INDEX_FILE:
        continue
```

---

## 🟡 #3 — `hybrid.rebuild_bm25()` doesn't sync tokenized corpus (medium)

**File:** `hybrid.py`, lines 57-60

```python
def rebuild_bm25(self, messages: list[dict]):
    self._bm25_docs = messages
    self._rebuild()        # Uses self._tokenized_corpus — NOT updated!
```

`_rebuild()` builds BM25 from `self._tokenized_corpus` (maintained by `add_document()`). But `rebuild_bm25()` replaces `_bm25_docs` without rebuilding the tokenized corpus, so the index is built from stale token data.

**De-risking:** `rebuild_bm25()` is **dead code** — grep shows zero callers in the current codebase. It was previously called in every `add_turn()` (Round 1 issue), and that was removed in Round 2. If never called, this is harmless but still a trap.

**Fix:** Delete the method or fix it to rebuild `_tokenized_corpus`:
```python
def rebuild_bm25(self, messages: list[dict]):
    self._bm25_docs = messages
    self._tokenized_corpus = [
        re.findall(r'\w+(?:[.:_]\w+)*', m.get('content', '').lower())
        for m in messages
    ]
    self._rebuild()
    self._docs_since_rebuild = 0
```

---

## 🟡 #4 — `delete_message()` orphans FTS index entries (medium)

**File:** `manager.py`, lines 683-700

```python
async def delete_message(self, msg_id: int) -> bool:
    ...
    msg = data["messages"].pop(msg_id)
    ...
    # <-- No call to self._fts.remove_message(...)
```

After removing the message, the FTS5 index still contains `msg_id = f"{session_id}_{msg_id}"`. Subsequent reuse of that msg_id index (due to shifting positions) could overwrite with unrelated content. `grep` confirms `remove_message()` is never called anywhere in the codebase.

**Fix:** Add FTS cleanup after successful removal:
```python
fts_msg_id = f"{session_id}_{msg_id}"
self._fts.remove_message(fts_msg_id)
```

---

## 🔵 #5 — `episodic.add_episode()` discards turn timestamp (low)

**File:** `episodic.py`, lines 18-35

```python
def add_episode(self, turn: Dict) -> str:
    ...
    metadata = {
        "session_id": self._session_id,
        "role": turn.get("role", "user"),
        "timestamp": datetime.now(timezone.utc).isoformat(),  # <-- new timestamp
    }
```

The `turn` dict already contains a `"timestamp"` key (set in `manager.add_turn()`), but it's ignored. The stored timestamp reflects storage time, not turn time — a ~microsecond-to-millisecond skew. Minor inconsistency for audit/logging.

**Fix:**
```python
"timestamp": turn.get("timestamp", datetime.now(timezone.utc).isoformat()),
```

---

## 🔵 #6 — Duplicate `truncated` entries in context_manager (low)

**File:** `context_manager.py`, line 119

```python
for item in relevant:
    ...
    if item_tokens <= available:
        available -= item_tokens
        keep.append(item)
    else:
        truncated.append("relevant_context")   # appended per-skipped-item
```

When multiple relevant items are skipped, `truncated` becomes `["relevant_context", "relevant_context"]`. The `truncated` list is an implementation detail used only for logging, so duplicates are cosmetic. The log message reads: `"Context truncated: relevant_context, relevant_context"`.

**Fix:** Use a set or deduplicate before appending.

---

## 🔵 #7 — Private member access in `search_all_sessions_fts()` (low)

**File:** `manager.py`, line 816

```python
conn = self._fts._get_conn()    # accesses private method
```

`_get_conn()` is a private method on `FTSSearch`. The manager should use `self._fts.search()` only, not reach into internals. The sole purpose of this line is to check if the FTS table is empty before calling `rebuild_from_sessions()`.

**Fix:** Add a `count()` method to `FTSSearch`:
```python
# In FTSSearch:
def count(self) -> int:
    conn = self._get_conn()
    return conn.execute("SELECT COUNT(*) FROM message_fts;").fetchone()[0]

# In manager:
if self._fts.count() == 0:
    self._fts.rebuild_from_sessions(self.conv_dir)
return self._fts.search(query, top_k)
```

---

## 🔵 #8 — Blocking I/O inside async methods (low)

**File:** `manager.py`, multiple locations

`_write_sync()` and `_read_sync()` are called directly inside async methods (`add_turn`, `check_and_summarize`, `_prune_tool_outputs`, `delete_message`), blocking the event loop thread for file I/O:

```python
async def add_turn(self, ...):
    ...
    with lock:
        data = self._read_sync(session_id)      # blocking
        ...
        self._write_sync(session_id, data)      # blocking
```

These are generally fast (local SSD, small JSON files), but still violate the async principle. The async `_read`/`_write` methods exist but aren't used here because the RLock pattern requires running on the same thread.

**Impact:** Low in practice — typical I/O is <1ms. But under heavy concurrent access or slow storage, this could stall the event loop.

**Note:** This is an acknowledged design tradeoff (RLock + inline I/O for simplicity). Not blocking for this review.

---

## 🔵 #9 — `inject_to_context()` formatting overhead not counted (low)

**File:** `vault.py`, lines 335-376

```python
section_name = f.stem.replace("_", " ").title()
sections.append(f"\n\n### {section_name}\n{content}")
token_usage += estimate_tokens(content)    # counts content only
```

The `\n\n### Section Name\n` prefix adds ~5-15 tokens per file that are not counted against `max_tokens`. When many small vault files are injected, the cumulative overhead could exceed the budget by a small amount.

**Fix:** Include the header in token estimation:
```python
header = f"\n\n### {section_name}\n"
header_tokens = estimate_tokens(header)
if token_usage + header_tokens + file_tokens > max_tokens:
    ...adjust...
sections.append(f"{header}{content}")
token_usage += header_tokens + file_tokens
```

---

## Summary

| Metric | Count |
|--------|-------|
| Files clean (0 issues) | 5 / 12 |
| Medium-high findings | 1 |
| Medium findings | 3 |
| Low findings | 5 |
| **Total findings** | **9** |

**Clean files:** `working.py`, `semantic.py`, `fts.py`, `cache.py`, `consolidator.py`, `session_index.py`

**Verification methodology:**
- Static analysis of all 12 files for 17+ bug classes (race conditions, resource leaks, path traversal, import safety, async correctness, encapsulation, token accounting, consistency)
- Cross-referenced imports and callers across the full codebase
- Verified all Round 2 reported fixes are present (BM25 dirty flag, per-session locks, atomic writes, FTS5 escaping, etc.)
- No reproduction runtime testing performed (black-box)

The most impactful finding is #1 (`vault.py` unguarded `rank_bm25` import), which is the only one that can actually crash the process. All others are correctness/cleanliness issues with limited blast radius.

import json
import os
import asyncio
import concurrent.futures
import threading
import logging
import uuid
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from pathlib import Path
from collections import OrderedDict

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    _HAS_CHROMADB = True
except ImportError:
    _HAS_CHROMADB = False
from backend.core.memory.cache import FACTCache
from backend.core.memory.hybrid import HybridRetrieval
from backend.core.memory.session_index import SessionIndex
from backend.core.memory.fts import FTSSearch
from backend.core.memory.working import WorkingMemory
from backend.core.memory.episodic import EpisodicMemory
from backend.core.memory.semantic import SemanticMemory
from backend.core.memory.consolidator import Consolidator

logger = logging.getLogger(__name__)

_LOCAL_EMBEDDING = None
_LOCAL_EMBEDDING_LOADED = False

# Maximum number of session data cache entries before LRU eviction
_MAX_CACHED_SESSIONS = 100


def _get_local_embedding():
    """Lazy-load SentenceTransformer on first use (saves ~18s at startup)."""
    global _LOCAL_EMBEDDING, _LOCAL_EMBEDDING_LOADED
    if not _LOCAL_EMBEDDING_LOADED:
        _LOCAL_EMBEDDING_LOADED = True
        try:
            from sentence_transformers import SentenceTransformer
            _LOCAL_EMBEDDING = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            logger.warning("sentence_transformers not installed; local embedding unavailable")
        except Exception as e:
            logger.warning(f"Failed to load local embedding model: {e}")
    return _LOCAL_EMBEDDING


class Memory:
    def __init__(self, llm_router: Any = None, db_path: Optional[str] = None, settings: Any = None):
        from backend.core.paths import CONVERSATIONS_DIR, EMBEDDINGS_DIR
        self.llm = llm_router
        self.settings = settings
        self.conv_dir = Path(db_path) if db_path else CONVERSATIONS_DIR
        self.conv_dir.mkdir(parents=True, exist_ok=True)
        self._summarize_lock = asyncio.Lock()
        self._current_session: Optional[str] = None
        # Per-session locks for thread-safe write+cache operations
        self._session_locks: Dict[str, threading.RLock] = {}
        self._session_locks_lock = threading.Lock()
        self._session_data_cache: OrderedDict[str, Dict] = OrderedDict()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(os.cpu_count() or 4, 2),
            thread_name_prefix="mem_io"
        )

        EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
        if _HAS_CHROMADB:
            self.chroma = chromadb.PersistentClient(
                path=str(EMBEDDINGS_DIR),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self.chroma_col = self.chroma.get_or_create_collection(
                name="conversations",
                metadata={"hnsw:space": "cosine"},
            )
            self._maybe_migrate()
        else:
            self.chroma = None
            self.chroma_col = None
            logger.warning("ChromaDB not available; some memory features disabled")

        self._fact_cache = FACTCache()
        self._session_index = SessionIndex(self.conv_dir)
        self._hybrid = HybridRetrieval(self.chroma_col)
        self._fts = FTSSearch(self.conv_dir)

        # Memory tiers — default capacity matches memory.context_window (50)
        window = self._setting("memory.context_window", 50)
        self._working = WorkingMemory(capacity=window)
        self._semantic = SemanticMemory(str(EMBEDDINGS_DIR / "semantic_facts.json"))
        self._consolidator = Consolidator(importance_threshold=0.3)
        # EpisodicMemory is created per-session lazily (needs session_id)
        self._episodic_memories: Dict[str, EpisodicMemory] = {}

    def _get_session_lock(self, session_id: str) -> threading.RLock:
        """Get or create a per-session lock for thread-safe operations."""
        with self._session_locks_lock:
            if session_id not in self._session_locks:
                self._session_locks[session_id] = threading.RLock()
            return self._session_locks[session_id]

    async def _run_session_mutation(self, session_id: str, mutator):
        """Run a read-mutate-write session critical section in the executor.

        Keeps blocking file I/O off the event loop. The entire
        lock-acquire → read → mutate → write → lock-release sequence runs
        in a worker thread, which is safe because :class:`threading.RLock`
        serialises concurrent access from any thread.
        """
        lock = self._get_session_lock(session_id)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: mutator(lock))

    def _cache_get(self, session_id: str) -> Optional[Dict]:
        """Get from LRU cache; promotes accessed entry."""
        if session_id in self._session_data_cache:
            data = self._session_data_cache.pop(session_id)
            self._session_data_cache[session_id] = data
            return data
        return None

    def _cache_put(self, session_id: str, data: Dict):
        """Put into LRU cache with eviction of oldest entry if over limit."""
        if session_id in self._session_data_cache:
            self._session_data_cache.pop(session_id)
        self._session_data_cache[session_id] = data
        if len(self._session_data_cache) > _MAX_CACHED_SESSIONS:
            # Remove oldest entry (LRU eviction)
            self._session_data_cache.popitem(last=False)

    def _cache_remove(self, session_id: str):
        """Remove a session from cache."""
        self._session_data_cache.pop(session_id, None)

    def _memory_enabled(self) -> bool:
        """Check if memory persistence is enabled in settings. Defaults to True."""
        if self.settings:
            return bool(self.settings.get("memory.enabled", True))
        return True

    def _fact_extraction_enabled(self) -> bool:
        """Check if long-term fact extraction is enabled in settings. Defaults to True."""
        if self.settings:
            return bool(self.settings.get("memory.fact_extraction", True))
        return True

    def _maybe_migrate(self):
        """Migrate legacy session embeddings to ChromaDB (runs once).

        A sentinel file (``.migrated``) is created on completion to prevent
        re-running on every startup.
        """
        from backend.core.paths import EMBEDDINGS_DIR

        sentinel = EMBEDDINGS_DIR / ".migrated"
        if sentinel.exists():
            return

        existing = set(self.chroma_col.get()["ids"])
        if existing:
            sentinel.touch()
            return

        for p in self._iter_session_paths():
            try:
                data = json.loads(p.read_text())
                sid = data.get("id", self._path_to_session_id(p) or p.stem)
                ids, embs, metas = [], [], []
                for i, msg in enumerate(data.get("messages", [])):
                    emb = msg.get("embedding")
                    if emb is not None:
                        cid = f"{sid}_migrated_{i}"
                        ids.append(cid)
                        embs.append(emb)
                        metas.append({
                            "session_id": sid,
                            "role": msg["role"],
                            "content": msg["content"],
                            "timestamp": msg.get("timestamp", ""),
                        })
                if ids:
                    self.chroma_col.add(ids=ids, embeddings=embs, metadatas=metas)
            except Exception as e:
                logger.warning(f"Migration skipped for {p}: {e}")

        sentinel.touch()

    def _session_path(self, session_id: str) -> Path:
        if not session_id:
            return self.conv_dir / "_invalid.json"
        if '_' in session_id:
            parts = session_id.split('_', 2)
            if len(parts) >= 2 and re.match(r'^\d{4}-\d{2}-\d{2}$', parts[0]) and re.match(r'^\d{6}$', parts[1][:6]):
                date_part, time_part = parts[0], parts[1]
                y, m, d = date_part.split('-')
                return self.conv_dir / y / m / d / f"{time_part}.json"
        safe = session_id.replace('/', '_').replace('\\', '_')
        return self.conv_dir / f"{safe}.json"

    def _iter_session_paths(self):
        seen = set()
        for pattern in ("*/*/*/*.json", "*.json"):
            for p in sorted(self.conv_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
                if p.name == SessionIndex.INDEX_FILE:
                    continue
                if p not in seen:
                    seen.add(p)
                    yield p

    def _path_to_session_id(self, path: Path) -> Optional[str]:
        parts = path.relative_to(self.conv_dir).parts
        if len(parts) == 1 and parts[0].endswith('.json'):
            return parts[0][:-5]
        if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit() and parts[3].endswith('.json'):
            y, m, d, fname = parts
            time_part = fname[:-5]
            return f"{y}-{m}-{d}_{time_part}"
        return None

    def _read_sync(self, session_id: str) -> Optional[Dict]:
        """Read session data from memory cache or disk. Thread-safe via per-session lock."""
        lock = self._get_session_lock(session_id)
        with lock:
            # Return cached copy if available (avoids full-file I/O every turn)
            cached = self._cache_get(session_id)
            if cached is not None:
                return cached
            path = self._session_path(session_id)
            if not path.exists():
                return None
            try:
                data = json.loads(path.read_text())
                self._cache_put(session_id, data)
                return data
            except (json.JSONDecodeError, OSError):
                return None

    def _write_sync(self, session_id: str, data: Dict):
        """Write session data to disk atomically and update in-memory cache.
        Thread-safe via per-session lock.
        """
        lock = self._get_session_lock(session_id)
        with lock:
            path = self._session_path(session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: write to tmp then rename
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.replace(path)
            # Update cache so subsequent reads avoid disk I/O
            self._cache_put(session_id, data)

    async def _read(self, session_id: str) -> Optional[Dict]:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._read_sync, session_id)

    async def _write(self, session_id: str, data: Dict):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._write_sync, session_id, data)

    async def start_session(self) -> str:
        """Start a new session using async write to avoid blocking the event loop."""
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%d_%H%M%S")
        session_id = ts
        character = self._setting("character.active", "default") if self.settings else None
        provider = self._setting("provider.active", None) if self.settings else None
        model = None
        if provider and self.settings:
            model = self._setting(f"provider.{provider}.model", None)
        data = {
            "id": session_id,
            "created": now.isoformat(),
            "updated": now.isoformat(),
            "title": "New Session",
            "character": character,
            "provider": provider,
            "model": model,
            "messages": [],
            "summary": None,
        }
        await self._write(session_id, data)
        self._session_index.upsert(session_id, {
            "id": session_id,
            "created": now.isoformat(),
            "updated": now.isoformat(),
            "title": "New Session",
            "character": character,
            "provider": provider,
            "model": model,
        })
        self._current_session = session_id
        return session_id

    def _start_session_sync(self) -> str:
        """Synchronous session creation used by get_current_session() for backwards compatibility."""
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%d_%H%M%S")
        session_id = ts
        character = self._setting("character.active", "default") if self.settings else None
        provider = self._setting("provider.active", None) if self.settings else None
        model = None
        if provider and self.settings:
            model = self._setting(f"provider.{provider}.model", None)
        data = {
            "id": session_id,
            "created": now.isoformat(),
            "updated": now.isoformat(),
            "title": "New Session",
            "character": character,
            "provider": provider,
            "model": model,
            "messages": [],
            "summary": None,
        }
        self._write_sync(session_id, data)
        self._session_index.upsert(session_id, {
            "id": session_id,
            "created": now.isoformat(),
            "updated": now.isoformat(),
            "title": "New Session",
            "character": character,
            "provider": provider,
            "model": model,
        })
        self._current_session = session_id
        return session_id

    def session_exists(self, session_id: str) -> bool:
        exists = self._session_path(session_id).exists()
        return exists

    def has_active_session(self) -> bool:
        """Return True if a conversation session is already active."""
        return self._current_session is not None

    def set_current_session(self, session_id: str):
        self._current_session = session_id

    def get_current_session(self) -> str:
        if not self._current_session:
            self._start_session_sync()
        return self._current_session

    def _setting(self, key: str, default):
        if self.settings:
            return self.settings.get(key, default)
        return default

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        cached = self._fact_cache.get(text)
        if cached is not None:
            return cached

        backend = self._setting("memory.embedding_backend", "provider")

        if backend == "disabled":
            return None

        # Build priority list: prefer configured backend, fall back to local
        if backend == "local":
            backends = ["local"]
            # Add provider as fallback only if the user explicitly configured it too
            if self.llm:
                backends.append("provider")
        elif backend == "provider":
            backends = ["provider", "local"]
        else:
            backends = ["provider", "local"]

        last_error = None
        for b in backends:
            if b == "local":
                local_emb = _get_local_embedding()
                if local_emb is not None:
                    try:
                        emb = local_emb.encode(text)
                        result = emb.tolist()
                        self._fact_cache.set(text, result)
                        return result
                    except Exception as e:
                        last_error = e
                        logger.debug(f"Local embedding failed: {e}")
                else:
                    logger.debug("Local embedding not available (sentence_transformers not installed)")
            elif b == "provider" and self.llm:
                try:
                    emb = await self.llm.get_embedding(text)
                    if emb:
                        self._fact_cache.set(text, emb)
                        return emb
                except Exception as e:
                    last_error = e
                    logger.debug(f"Provider embedding failed: {e}")

        if last_error:
            logger.debug(f"All embedding backends failed: {last_error}")
        return None

    def _get_episodic(self, session_id: str) -> EpisodicMemory:
        """Get or create EpisodicMemory for the given session."""
        if session_id not in self._episodic_memories:
            if self.chroma is not None:
                ep_collection = self.chroma.get_or_create_collection(
                    name="episodic",
                    metadata={"hnsw:space": "cosine"},
                )
            else:
                ep_collection = None
            self._episodic_memories[session_id] = EpisodicMemory(ep_collection, session_id)
        return self._episodic_memories[session_id]

    def _generate_title(self, messages: List[Dict]) -> str:
        for msg in messages:
            if msg.get("role") == "user":
                words = msg.get("content", "").strip().split()
                if words:
                    return " ".join(words[:4])
        return "New Session"

    def _get_unique_title(self, title: str) -> str:
        all_sessions = self.get_sessions()
        existing_titles = [s.get("title") for s in all_sessions if s.get("title")]

        if title not in existing_titles:
            return title

        counter = 1
        while f"{title} ({counter})" in existing_titles:
            counter += 1
        return f"{title} ({counter})"

    async def rename_session(self, session_id: str, new_title: str) -> str:
        all_sessions = self.get_sessions()
        if any(s.get("title") == new_title and s.get("id") != session_id for s in all_sessions):
            raise ValueError(f"Session title '{new_title}' already exists.")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._rename_session_sync, session_id, new_title)

    def _rename_session_sync(self, session_id: str, new_title: str) -> str:
        """Synchronous rename helper — runs in executor to avoid blocking event loop."""
        lock = self._get_session_lock(session_id)
        with lock:
            data = self._read_sync(session_id)
            if data:
                data["title"] = new_title
                self._write_sync(session_id, data)
                self._session_index.upsert(session_id, {"title": new_title})
                return new_title
        return ""

    def get_session_turns(self, session_id: str, turns: int = 5) -> List[Dict]:
        data = self._read_sync(session_id)
        if data is None:
            return []
        msgs = data.get("messages", [])
        return msgs[-(turns * 2):]

    async def add_turn(self, role: str, content: str):
        session_id = self.get_current_session()

        # Add to working memory (always — needed for conversation flow)
        self._working.add(role, content)

        # If memory persistence is disabled, skip disk/embedding/ChromaDB writes
        if not self._memory_enabled():
            return

        # 1. Compute embedding early (async, may be slow)
        embedding = await self._get_embedding(content)

        # 2. Prepare chroma_id if we have an embedding
        cid = None
        if embedding:
            cid = f"{session_id}_{uuid.uuid4().hex[:8]}"

        # 3. Mutate and persist session data — offloaded to executor via _run_session_mutation
        msg = None
        timestamp = None
        data = None

        def _do_add_turn(lock):
            nonlocal msg, timestamp, data
            with lock:
                data = self._read_sync(session_id)
                if data is None:
                    data = {
                        "id": session_id,
                        "created": datetime.now(timezone.utc).isoformat(),
                        "messages": [],
                        "summary": None,
                        "title": "New Session",
                    }
                timestamp = datetime.now(timezone.utc).isoformat()
                msg = {
                    "role": role,
                    "content": content,
                    "timestamp": timestamp,
                }
                if cid:
                    msg["chroma_id"] = cid

                if role == "user" and data.get("title", "New Session") == "New Session" and content.strip():
                    raw_title = self._generate_title([msg])
                    data["title"] = self._get_unique_title(raw_title)

                data["messages"].append(msg)
                data["updated"] = timestamp
                self._write_sync(session_id, data)

        await self._run_session_mutation(session_id, _do_add_turn)

        # 4. Update session index (idempotent, lightweight)
        self._session_index.upsert(session_id, {
            "id": session_id,
            "updated": timestamp,
            "message_count": len(data.get("messages", [])),
            "title": data.get("title", "New Session"),
        })

        # 5. Incremental BM25 update (avoid O(n) full rebuild on every turn)
        self._hybrid.add_document(msg)

        # 6. Store in ChromaDB embedding (non-critical; failure is logged)
        if embedding:
            try:
                self.chroma_col.add(
                    ids=[cid],
                    embeddings=[embedding],
                    metadatas=[{
                        "session_id": session_id,
                        "role": role,
                        "content": content,
                        "timestamp": timestamp,
                    }],
                )
            except Exception as e:
                logger.warning(f"ChromaDB add failed for {session_id}: {e}")

        # 7. Background summarization (fire-and-forget with safe lock)
        asyncio.create_task(self._safe_summarize())

        # 8. Index into FTS5 for keyword search
        msg_index = len(data["messages"]) - 1
        msg_id = f"{session_id}_{msg_index}"
        try:
            self._fts.index_message(session_id, msg_id, role, content, timestamp)
        except Exception as e:
            logger.warning(f"FTS index failed for {session_id}: {e}")

        # 9. Store in episodic memory for per-session recall
        ep = self._get_episodic(session_id)
        try:
            ep.add_episode({"role": role, "content": content, "timestamp": timestamp})
        except Exception as e:
            logger.warning(f"Episodic add_episode failed for {session_id}: {e}")

    async def _safe_summarize(self):
        """Wrapper that catches and logs summarization errors."""
        try:
            await self.check_and_summarize()
        except Exception as e:
            logger.error(f"Background summarization failed: {e}", exc_info=True)

    def get_sessions(self) -> List[Dict]:
        sessions = []
        index_sessions = self._session_index.list_all()
        if index_sessions:
            for entry in index_sessions:
                sid = entry.get("id", "")
                if not sid:
                    continue
                path = self._session_path(sid)
                if not path.exists():
                    # Don't silently remove; just skip
                    logger.debug(f"Session {sid} in index but file not found; skipping")
                    continue
                data = self._read_sync(sid)
                if data is None:
                    continue
                msgs = data.get("messages", [])
                preview = ""
                for m in msgs:
                    if m.get("role") == "user":
                        preview = m["content"][:80]
                        break
                sessions.append({
                    "id": data["id"],
                    "started": data.get("created"),
                    "last_active": data.get("updated"),
                    "message_count": len(msgs),
                    "preview": preview,
                    "title": data.get("title", ""),
                    "character": data.get("character", ""),
                    "provider": data.get("provider", ""),
                    "model": data.get("model", ""),
                })
            return sessions

        # Fallback: iterate disk if index is empty
        for path in self._iter_session_paths():
            sid = self._path_to_session_id(path)
            if not sid:
                continue
            data = self._read_sync(sid)
            if data is None:
                continue
            msgs = data.get("messages", [])
            preview = ""
            for m in msgs:
                if m.get("role") == "user":
                    preview = m["content"][:80]
                    break
            sessions.append({
                "id": data.get("id", sid),
                "started": data.get("created"),
                "last_active": data.get("updated"),
                "message_count": len(msgs),
                "preview": preview,
                "title": data.get("title", ""),
                "character": data.get("character", ""),
                "provider": data.get("provider", ""),
                "model": data.get("model", ""),
            })
        return sessions

    def get_session_messages(self, session_id: str) -> List[Dict]:
        data = self._read_sync(session_id)
        if data is None:
            return []
        return [
            {"id": i, "role": m["role"], "content": m["content"], "timestamp": m.get("timestamp")}
            for i, m in enumerate(data.get("messages", []))
        ]

    async def delete_session(self, session_id: str) -> bool:
        try:
            if self.chroma_col is not None:
                self.chroma_col.delete(where={"session_id": session_id})
        except Exception as e:
            logger.warning(f"ChromaDB delete failed for {session_id}: {e}")
        path = self._session_path(session_id)
        if path.exists():
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, path.unlink)
            self._cache_remove(session_id)
            self._session_index.remove(session_id)
            # Cleanup per-session resources
            with self._session_locks_lock:
                self._session_locks.pop(session_id, None)
            self._episodic_memories.pop(session_id, None)
            return True
        return False

    def get_recent(self, n: Optional[int] = None) -> List[Dict[str, str]]:
        if n is None:
            n = self._setting("memory.context_window", 50)
        if n <= 0:
            return []

        # If memory persistence is disabled, ensure working memory can hold enough
        if not self._memory_enabled():
            if self._working.capacity < n:
                self._working.capacity = n
            return self._working.recent(n)

        # Prefer working memory (always in memory, most recent turns)
        working_turns = self._working.recent(n)
        if len(working_turns) >= n:
            return working_turns

        # Fall back to disk for older messages
        session_id = self._current_session
        if not session_id:
            return working_turns or []
        data = self._read_sync(session_id)
        if data is None:
            return working_turns or []
        msgs = data.get("messages", [])
        return msgs[-n:]

    def store_semantic_fact(self, content: str, metadata: Optional[Dict] = None) -> str:
        """Store a cross-session fact in semantic memory. Returns fact ID."""
        return self._semantic.add_fact(content, metadata)

    async def store_semantic_fact_async(self, content: str, metadata: Optional[Dict] = None) -> str:
        """Async wrapper for store_semantic_fact — offloads I/O to executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.store_semantic_fact, content, metadata)

    def search_semantic(self, query: str, k: int = 5) -> List[Dict]:
        """Search semantic memory for relevant facts (BM25)."""
        return self._semantic.search(query, k)

    async def delete_message(self, msg_id: int) -> bool:
        session_id = self.get_current_session()
        chroma_id = None

        def _do_delete(lock):
            nonlocal chroma_id
            with lock:
                data = self._read_sync(session_id)
                if data is None or msg_id >= len(data.get("messages", [])):
                    return False
                msg = data["messages"].pop(msg_id)
                chroma_id = msg.get("chroma_id")
                self._write_sync(session_id, data)
                return True

        if not await self._run_session_mutation(session_id, _do_delete):
            return False
        if chroma_id:
            try:
                if self.chroma_col is not None:
                    self.chroma_col.delete(ids=[chroma_id])
            except Exception as e:
                logger.warning(f"ChromaDB delete failed for message {msg_id}: {e}")
        # Clean up FTS index
        try:
            fts_msg_id = f"{session_id}_{msg_id}"
            self._fts.remove_message(fts_msg_id)
        except Exception as e:
            logger.warning(f"FTS delete failed for message {msg_id}: {e}")
        return True

    def get_summary(self) -> str:
        session_id = self.get_current_session()
        lock = self._get_session_lock(session_id)
        with lock:
            data = self._read_sync(session_id)
        if data is None:
            return ""
        return data.get("summary") or ""

    def get_session_summary(self, session_id: str) -> str:
        data = self._read_sync(session_id)
        if data is None:
            return ""
        return data.get("summary") or ""

    def get_session_summary_id(self, session_id: str) -> int:
        data = self._read_sync(session_id)
        if data is None:
            return 0
        return len(data.get("messages", []))

    async def get_relevant(self, query: str, top_k: Optional[int] = None) -> List[Dict[str, str]]:
        if top_k is None:
            top_k = self._setting("memory.retrieval_k", 3)
        if not self.llm and _get_local_embedding() is None:
            return []

        session_id = self.get_current_session()

        # Use retrieve_for_context for caching + hybrid retrieval
        contents = await self.retrieve_for_context(query, session_id, n=top_k)
        if contents:
            return [{"role": "assistant", "content": c} for c in contents]

        return []

    async def retrieve_for_context(
        self,
        query: str,
        session_id: Optional[str] = None,
        n: int = 5,
    ) -> list[str]:
        """
        Retrieve relevant memory for the current query.
        Uses: FACT cache → RRF hybrid (BM25 + ChromaDB) → return top-N.
        """
        if not query or not query.strip():
            return []

        if session_id is None:
            session_id = self.get_current_session()

        # 1. Check FACT cache first — instant, no DB call
        cache_key = f"{session_id}:{query[:80]}"
        cached = self._fact_cache.get_key(cache_key)
        if cached is not None:
            return cached

        # 2. RRF hybrid retrieval
        query_emb = await self._get_embedding(query)
        if not query_emb:
            return []
        try:
            results = await self._hybrid.retrieve(query, query_emb, session_id, n)
            contents = [r.get("content", "") for r in results if r.get("content")]
        except Exception as e:
            logger.warning(f"Hybrid retrieval failed: {e}")
            contents = []

        # 3. Cache the result for 5 minutes
        self._fact_cache.set_key(cache_key, contents, ttl=300)

        return contents

    async def search_all_sessions(self, query: str, top_k: int = 10) -> List[Dict]:
        """Semantic search across ALL sessions (no session_id filter).

        Returns list of dicts with session_id, role, content, timestamp, distance.
        """
        if self.chroma_col is None:
            return []

        if not self.llm and _get_local_embedding() is None:
            return []

        query_emb = await self._get_embedding(query)
        if not query_emb:
            return []

        try:
            results = self.chroma_col.query(
                query_embeddings=[query_emb],
                n_results=top_k,
            )
            metadatas = (results.get("metadatas") or [[]])[0]
            distances = (results.get("distances") or [[]])[0] if results.get("distances") else [None] * len(metadatas)
            if metadatas:
                return [
                    {
                        "session_id": m.get("session_id", ""),
                        "role": m.get("role", ""),
                        "content": m.get("content", ""),
                        "timestamp": m.get("timestamp", ""),
                        "distance": d,
                    }
                    for m, d in zip(metadatas, distances)
                ]
        except Exception as e:
            logger.warning(f"ChromaDB cross-session query failed: {e}")

        return []

    async def search_all_sessions_fts(self, query: str, top_k: int = 10) -> List[Dict]:
        """Keyword search across ALL sessions via FTS5."""
        if self._fts.count() == 0:
            self._fts.rebuild_from_sessions(self.conv_dir)
        return self._fts.search(query, top_k)

    async def _prune_tool_outputs(self, session_id: str, max_chars: int = 2000):
        def _do_prune(lock):
            with lock:
                data = self._read_sync(session_id)
                if data is None:
                    return
                changed = False
                for msg in data["messages"]:
                    if msg["role"] == "system" and len(msg["content"]) > max_chars:
                        msg["content"] = msg["content"][:max_chars] + "\n[...truncated]"
                        changed = True
                if changed:
                    self._write_sync(session_id, data)

        await self._run_session_mutation(session_id, _do_prune)

    def _do_save_summary(self, session_id: str, keep: int, summary: str):
        """Synchronous save of summarization result — runs in executor to avoid blocking event loop."""
        lock = self._get_session_lock(session_id)
        with lock:
            data = self._read_sync(session_id)
            if data:
                if keep < len(data["messages"]):
                    data["messages"] = data["messages"][-keep:]
                data["summary"] = summary
                self._write_sync(session_id, data)

    async def check_and_summarize(self):
        if not self.llm:
            return
        if self._summarize_lock.locked():
            return

        async with self._summarize_lock:
            try:
                threshold = self._setting("memory.summarize_threshold", 40)
                keep = self._setting("memory.summarize_keep", 15)
                session_id = self.get_current_session()

                data = self._read_sync(session_id)
                if data is None:
                    return

                count = len(data.get("messages", []))
                if count <= threshold:
                    return

                await self._prune_tool_outputs(session_id)

                data = self._read_sync(session_id)
                msgs = data["messages"]
                to_summarize = msgs[:-keep] if keep < len(msgs) else msgs

                existing = data.get("summary") or ""
                context_hint = f"\nPrevious summary:\n{existing}" if existing else ""

                chat_log = "\n".join(f"{m['role']}: {m['content']}" for m in to_summarize)
                prompt = (
                    "Analyze the following conversation history and produce a structured compaction summary. "
                    "Focus on preserving actionable information: decisions, file paths, commands, user preferences, and next steps. "
                    "Use these sections:\n"
                    "# Decisions\n# File Paths\n# Commands\n# Preferences\n# Next Steps\n"
                    f"Conversation:\n{chat_log}\n{context_hint}\n\nCompacted summary:"
                )
                summary = await self.llm.generate([{"role": "user", "content": prompt}])

                from backend.core.plugin import get_registry as get_plugin_registry
                summary = await get_plugin_registry().hook_compaction(summary or "")

                if summary and not summary.startswith("Error"):
                    async def _save_summary():
                        loop = asyncio.get_running_loop()
                        return await loop.run_in_executor(
                            self._executor, self._do_save_summary, session_id, keep, summary
                        )
                    await _save_summary()
            except Exception as e:
                logger.error(f"Compaction failed: {e}", exc_info=True)

    async def clear(self):
        if not self.chroma:
            logger.warning("ChromaDB not available — skipping collection operations")
            return
        try:
            self.chroma.delete_collection("conversations")
        except Exception:
            pass
        self.chroma_col = self.chroma.create_collection(
            name="conversations",
            metadata={"hnsw:space": "cosine"},
        )
        loop = asyncio.get_running_loop()
        for path in list(self._iter_session_paths()):
            await loop.run_in_executor(self._executor, path.unlink)
        with self._session_locks_lock:
            self._session_locks.clear()
        self._session_data_cache.clear()
        self._session_index._index.clear()
        self._session_index._save()
        self._hybrid = HybridRetrieval(self.chroma_col)
        # Reset all memory tiers
        self._working.clear()
        self._semantic.clear()
        self._episodic_memories.clear()

    async def shutdown(self):
        """Clean up executor and release resources."""
        # Graceful drain: wait for pending tasks with timeout
        self._executor.shutdown(wait=True)
        if self.chroma:
            try:
                self.chroma.clear_system_cache()
            except Exception:
                pass

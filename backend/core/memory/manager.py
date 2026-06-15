import json
import asyncio
import concurrent.futures
import threading
import logging
import uuid
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional
from pathlib import Path

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
try:
    from sentence_transformers import SentenceTransformer
    _LOCAL_EMBEDDING = SentenceTransformer("all-MiniLM-L6-v2")
except ImportError:
    pass


class Memory:
    def __init__(self, llm_router=None, db_path=None, settings=None):
        from backend.core.paths import CONVERSATIONS_DIR, EMBEDDINGS_DIR
        self.llm = llm_router
        self.settings = settings
        self.conv_dir = Path(db_path) if db_path else CONVERSATIONS_DIR
        self.conv_dir.mkdir(parents=True, exist_ok=True)
        self._summarize_lock = asyncio.Lock()
        self._current_session: Optional[str] = None
        self._known_sessions: set = set()
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="mem_io")

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

            for p in self._iter_session_paths():
                sid = self._path_to_session_id(p)
                if sid:
                    self._known_sessions.add(sid)

            self._maybe_migrate()
        else:
            self.chroma = None
            self.chroma_col = None

        self._fact_cache = FACTCache()
        self._session_index = SessionIndex(self.conv_dir)
        self._hybrid = HybridRetrieval(self.chroma_col)
        self._fts = FTSSearch(self.conv_dir)

        # Memory tiers
        self._working = WorkingMemory(capacity=20)
        self._semantic = SemanticMemory(str(EMBEDDINGS_DIR / "semantic_facts.json"))
        self._consolidator = Consolidator(importance_threshold=0.3)
        # EpisodicMemory is created per-session lazily (needs session_id)
        self._episodic_memories: Dict[str, EpisodicMemory] = {}

    def _maybe_migrate(self):
        existing = set(self.chroma_col.get()["ids"])
        if existing:
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
                logger.debug(f"Migration skipped for {p}: {e}")

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
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _write_sync(self, session_id: str, data: Dict):
        path = self._session_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str))

    async def _read(self, session_id: str) -> Optional[Dict]:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._read_sync, session_id)

    async def _write(self, session_id: str, data: Dict):
        path = self._session_path(session_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._write_sync, session_id, data)

    def start_session(self) -> str:
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%d_%H%M%S")
        session_id = ts
        with self._lock:
            self._current_session = session_id
            self._known_sessions.add(session_id)
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
        return session_id

    def session_exists(self, session_id: str) -> bool:
        if session_id in self._known_sessions:
            return True
        exists = self._session_path(session_id).exists()
        if exists:
            self._known_sessions.add(session_id)
        return exists

    def set_current_session(self, session_id: str):
        self._current_session = session_id

    def get_current_session(self) -> str:
        if not self._current_session:
            self.start_session()
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

        if backend == "local" and _LOCAL_EMBEDDING is not None:
            try:
                emb = _LOCAL_EMBEDDING.encode(text)
                result = emb.tolist()
                self._fact_cache.set(text, result)
                return result
            except Exception as e:
                logger.debug(f"Local embedding failed: {e}")

        if backend in ("provider", "local") and self.llm:
            try:
                emb = await self.llm.get_embedding(text)
                if emb:
                    self._fact_cache.set(text, emb)
                    return emb
            except Exception as e:
                logger.debug(f"Provider embedding failed: {e}")

        if _LOCAL_EMBEDDING is not None:
            try:
                emb = _LOCAL_EMBEDDING.encode(text)
                result = emb.tolist()
                self._fact_cache.set(text, result)
                return result
            except Exception:
                pass

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
            
        with self._lock:
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
        embedding = await self._get_embedding(content)

        # Add to working memory (in-memory ring buffer)
        self._working.add(role, content)

        with self._lock:
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
            if embedding:
                cid = f"{session_id}_{uuid.uuid4().hex[:8]}"
                msg["chroma_id"] = cid

            if role == "user" and data.get("title", "New Session") == "New Session" and content.strip():
                # Generate initial title from first 4 words of first user message
                raw_title = self._generate_title([msg])
                data["title"] = self._get_unique_title(raw_title)

            data["messages"].append(msg)
            data["updated"] = timestamp
            self._write_sync(session_id, data)

        self._session_index.upsert(session_id, {
            "id": session_id,
            "updated": timestamp,
            "message_count": len(data.get("messages", [])),
            "title": data.get("title", "New Session"),
        })
        self._hybrid.rebuild_bm25(data.get("messages", []))

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
                logger.debug(f"ChromaDB add failed: {e}")

        asyncio.create_task(self._safe_summarize())

        # Index into FTS5 for keyword search
        msg_index = len(data["messages"]) - 1
        msg_id = f"{session_id}_{msg_index}"
        self._fts.index_message(session_id, msg_id, role, content, timestamp)

        # Store in episodic memory for per-session recall
        ep = self._get_episodic(session_id)
        ep.add_episode({"role": role, "content": content, "timestamp": timestamp})

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
                    self._session_index.remove(sid)
                    continue
                data = self._read_sync(sid)
                if data is None:
                    self._session_index.remove(sid)
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
            self.chroma_col.delete(where={"session_id": session_id})
        except Exception as e:
            logger.debug(f"ChromaDB delete failed: {e}")
        path = self._session_path(session_id)
        if path.exists():
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, path.unlink)
            self._known_sessions.discard(session_id)
            self._session_index.remove(session_id)
            return True
        return False

    def get_recent(self, n: int = None) -> List[Dict[str, str]]:
        if n is None:
            n = self._setting("memory.context_window", 50)

        # Prefer working memory (always in memory, most recent turns)
        working_turns = self._working.recent(n)
        if len(working_turns) >= n:
            return working_turns

        # Fall back to disk for older messages
        session_id = self.get_current_session()
        with self._lock:
            data = self._read_sync(session_id)
        if data is None:
            return working_turns or []
        msgs = data.get("messages", [])
        return msgs[-n:]

    def get_all_recent(self, n: int = None) -> List[Dict[str, str]]:
        return self.get_recent(n)

    def store_semantic_fact(self, content: str, metadata: Optional[Dict] = None) -> str:
        """Store a cross-session fact in semantic memory. Returns fact ID."""
        return self._semantic.add_fact(content, metadata)

    def search_semantic(self, query: str, k: int = 5) -> List[Dict]:
        """Search semantic memory for relevant facts (BM25)."""
        return self._semantic.search(query, k)

    async def delete_message(self, msg_id: int) -> bool:
        session_id = self.get_current_session()
        chroma_id = None
        with self._lock:
            data = self._read_sync(session_id)
            if data is None or msg_id >= len(data.get("messages", [])):
                return False
            msg = data["messages"].pop(msg_id)
            chroma_id = msg.get("chroma_id")
            self._write_sync(session_id, data)
        if chroma_id:
            try:
                self.chroma_col.delete(ids=[chroma_id])
            except Exception as e:
                logger.debug(f"ChromaDB delete failed: {e}")
        return True

    def get_summary(self) -> str:
        session_id = self.get_current_session()
        with self._lock:
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

    async def get_relevant(self, query: str, top_k: int = None) -> List[Dict[str, str]]:
        if top_k is None:
            top_k = self._setting("memory.retrieval_k", 3)
        if not self.llm and _LOCAL_EMBEDDING is None:
            return []

        query_emb = await self._get_embedding(query)
        if not query_emb:
            return []

        session_id = self.get_current_session()
        try:
            return await self._hybrid.retrieve(query, query_emb, session_id, top_k)
        except Exception as e:
            logger.debug(f"Hybrid retrieval failed, falling back: {e}")
            try:
                results = self.chroma_col.query(
                    query_embeddings=[query_emb],
                    n_results=top_k,
                    where={"session_id": session_id},
                )
                if results and results["metadatas"] and results["metadatas"][0]:
                    return [
                        {"role": m["role"], "content": m["content"]}
                        for m in results["metadatas"][0]
                    ]
            except Exception as e2:
                logger.debug(f"ChromaDB query failed: {e2}")

        return []

    async def search_all_sessions(self, query: str, top_k: int = 10) -> List[Dict]:
        """Semantic search across ALL sessions (no session_id filter).

        Returns list of dicts with session_id, role, content, timestamp, distance.
        """
        if not self.llm and _LOCAL_EMBEDDING is None:
            return []

        query_emb = await self._get_embedding(query)
        if not query_emb:
            return []

        try:
            results = self.chroma_col.query(
                query_embeddings=[query_emb],
                n_results=top_k,
            )
            if results and results["metadatas"] and results["metadatas"][0]:
                distances = results["distances"][0] if results.get("distances") else [None] * len(results["metadatas"][0])
                return [
                    {
                        "session_id": m.get("session_id", ""),
                        "role": m.get("role", ""),
                        "content": m.get("content", ""),
                        "timestamp": m.get("timestamp", ""),
                        "distance": d,
                    }
                    for m, d in zip(results["metadatas"][0], distances)
                ]
        except Exception as e:
            logger.debug(f"ChromaDB cross-session query failed: {e}")

        return []

    async def search_all_sessions_fts(self, query: str, top_k: int = 10) -> List[Dict]:
        """Keyword search across ALL sessions via FTS5.

        Complements :meth:`search_all_sessions` (semantic search).
        If the FTS index is empty, it auto-populates from existing session files.
        """
        # Lazy build — only scan existing sessions when FTS is first queried
        conn = self._fts._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM message_fts;").fetchone()[0]
        if count == 0:
            self._fts.rebuild_from_sessions(self.conv_dir)
        return self._fts.search(query, top_k)

    async def _prune_tool_outputs(self, session_id: str, max_chars: int = 2000):
        with self._lock:
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

    async def check_and_summarize(self):
        if not self.llm:
            return
        if self._summarize_lock.locked():
            return

        async with self._summarize_lock:
            threshold = self._setting("memory.summarize_threshold", 40)
            keep = self._setting("memory.summarize_keep", 15)
            session_id = self.get_current_session()

            with self._lock:
                data = self._read_sync(session_id)
            if data is None:
                return

            count = len(data.get("messages", []))
            if count <= threshold:
                return

            try:
                await self._prune_tool_outputs(session_id)

                with self._lock:
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
                    with self._lock:
                        data = self._read_sync(session_id)
                        if data:
                            if keep < len(data["messages"]):
                                data["messages"] = data["messages"][-keep:]
                            data["summary"] = summary
                            self._write_sync(session_id, data)
            except Exception as e:
                logger.error(f"Compaction failed: {e}")

    async def clear(self):
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
        self._known_sessions.clear()
        self._session_index._index.clear()
        self._session_index._save()
        self._hybrid = HybridRetrieval(self.chroma_col)
        # Reset all memory tiers
        self._working.clear()
        self._semantic.clear()
        self._episodic_memories.clear()

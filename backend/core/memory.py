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

import chromadb
from chromadb.config import Settings as ChromaSettings

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
        self.summarizing = False
        self._current_session: Optional[str] = None
        self._known_sessions: set = set()
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="mem_io")

        EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
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
        return self.conv_dir / f"{session_id.replace('/', '_').replace('\\', '_')}.json"

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
        backend = self._setting("memory.embedding_backend", "provider")

        if backend == "disabled":
            return None

        if backend == "local" and _LOCAL_EMBEDDING is not None:
            try:
                emb = _LOCAL_EMBEDDING.encode(text)
                return emb.tolist()
            except Exception as e:
                logger.debug(f"Local embedding failed: {e}")

        if backend in ("provider", "local") and self.llm:
            try:
                emb = await self.llm.get_embedding(text)
                if emb:
                    return emb
            except Exception as e:
                logger.debug(f"Provider embedding failed: {e}")

        if _LOCAL_EMBEDDING is not None:
            try:
                emb = _LOCAL_EMBEDDING.encode(text)
                return emb.tolist()
            except Exception:
                pass

        return None

    async def add_turn(self, role: str, content: str):
        session_id = self.get_current_session()
        embedding = await self._get_embedding(content)

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
                title = content.strip()[:60]
                if len(content) > 60:
                    title += "..."
                data["title"] = title

            data["messages"].append(msg)
            data["updated"] = timestamp
            self._write_sync(session_id, data)

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

        asyncio.create_task(self.check_and_summarize())

    def get_sessions(self) -> List[Dict]:
        sessions = []
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
            return True
        return False

    def get_recent(self, n: int = None) -> List[Dict[str, str]]:
        if n is None:
            n = self._setting("memory.context_window", 50)
        session_id = self.get_current_session()
        with self._lock:
            data = self._read_sync(session_id)
        if data is None:
            return []
        msgs = data.get("messages", [])
        return msgs[-n:]

    def get_all_recent(self, n: int = None) -> List[Dict[str, str]]:
        return self.get_recent(n)

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
        except Exception as e:
            logger.debug(f"ChromaDB query failed: {e}")

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
        if self.summarizing or not self.llm:
            return

        threshold = self._setting("memory.summarize_threshold", 40)
        keep = self._setting("memory.summarize_keep", 15)
        session_id = self.get_current_session()

        data = self._read_sync(session_id)
        if data is None:
            return

        count = len(data.get("messages", []))
        if count <= threshold:
            return

        self.summarizing = True
        try:
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
                "#
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
        finally:
            self.summarizing = False

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

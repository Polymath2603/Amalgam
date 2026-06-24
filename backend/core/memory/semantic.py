"""Semantic memory — cross-session BM25 retrieval."""

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

logger = logging.getLogger(__name__)


class SemanticMemory:
    """Cross-session semantic storage using BM25 over a local document store.

    Facts are persisted to a JSON file so they survive process restarts.
    Thread-safe (all public methods acquire ``_lock``).
    """

    def __init__(self, storage_path: str) -> None:
        self._path = Path(storage_path)
        self._lock = threading.Lock()
        self._documents: List[Dict] = []
        self._bm25 = None
        self._dirty = False
        self._load()

    def add_fact(self, content: str, metadata: Optional[Dict] = None) -> str:
        """Store a fact (cross-session). Returns fact ID."""
        fid = str(uuid.uuid4())
        entry = {"id": fid, "content": content, "metadata": metadata or {}}
        with self._lock:
            self._documents.append(entry)
            self._dirty = True
        self.save()
        logger.debug(f"SemanticMemory: added fact {fid}")
        return fid

    def search(self, query: str, k: int = 5) -> List[Dict]:
        """BM25 search across all stored facts."""
        with self._lock:
            if not self._documents:
                return []
            self._rebuild_bm25()
            if self._bm25 is None:
                return []
            tokenized_query = query.lower().split()
            scores = self._bm25.get_scores(tokenized_query)
            top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
            return [
                {**self._documents[i], "score": float(scores[i])}
                for i in top_indices
                if scores[i] > 0
            ]

    def count(self) -> int:
        with self._lock:
            return len(self._documents)

    def clear(self) -> None:
        with self._lock:
            self._documents.clear()
            self._bm25 = None
            self._dirty = False

    def save(self) -> None:
        """Persist documents to disk atomically."""
        with self._lock:
            if not self._dirty:
                return
            snapshot = list(self._documents)
            self._dirty = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(snapshot, indent=2, default=str))
            tmp.replace(self._path)
        except Exception as e:
            logger.error(f"SemanticMemory: failed to save facts: {e}")

    def _load(self) -> None:
        """Load documents from disk (caller must hold _lock)."""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            if isinstance(data, list):
                self._documents = data
                self._dirty = False
                logger.debug(f"SemanticMemory: loaded {len(data)} facts")
        except Exception as e:
            logger.warning(f"SemanticMemory: failed to load facts: {e}")

    def _rebuild_bm25(self) -> None:
        """Rebuild BM25 index (caller must hold _lock)."""
        if not self._dirty and self._bm25 is not None:
            return
        if BM25Okapi is None:
            logger.warning("rank_bm25 not installed; semantic search degraded")
            self._bm25 = None
            return
        try:
            tokenized = [d["content"].lower().split() for d in self._documents]
            self._bm25 = BM25Okapi(tokenized)
            self._dirty = False
        except Exception as e:
            logger.warning(f"BM25 rebuild failed: {e}")
            self._bm25 = None

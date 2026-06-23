"""Semantic memory — cross-session BM25 retrieval."""

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SemanticMemory:
    """Cross-session semantic storage using BM25 over a local document store.

    Facts are persisted to a JSON file so they survive process restarts.
    """

    def __init__(self, storage_path: str) -> None:
        self._path = Path(storage_path)
        self._documents: List[Dict] = []
        self._bm25 = None
        self._dirty = False
        self._load()

    def add_fact(self, content: str, metadata: Optional[Dict] = None) -> str:
        """Store a fact (cross-session). Returns fact ID."""
        fid = str(uuid.uuid4())
        entry = {"id": fid, "content": content, "metadata": metadata or {}}
        self._documents.append(entry)
        self._dirty = True
        self._save()
        logger.debug(f"SemanticMemory: added fact {fid}")
        return fid

    def search(self, query: str, k: int = 5) -> List[Dict]:
        """BM25 search across all stored facts."""
        if not self._documents:
            return []
        self._rebuild_bm25()
        tokenized_query = query.lower().split()
        scores = self._bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        return [
            {**self._documents[i], "score": float(scores[i])}
            for i in top_indices
            if scores[i] > 0
        ]

    def count(self) -> int:
        return len(self._documents)

    def clear(self) -> None:
        self._documents.clear()
        self._bm25 = None
        self._dirty = False

    def save(self) -> None:
        """Persist documents to disk atomically."""
        if not self._dirty:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._documents, indent=2, default=str))
            tmp.replace(self._path)
        except Exception as e:
            logger.error(f"SemanticMemory: failed to save facts: {e}")

    def _load(self) -> None:
        """Load documents from disk."""
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
        if not self._dirty and self._bm25 is not None:
            return
        try:
            from rank_bm25 import BM25Okapi
            tokenized = [d["content"].lower().split() for d in self._documents]
            self._bm25 = BM25Okapi(tokenized)
            self._dirty = False
        except ImportError:
            logger.warning("rank_bm25 not installed; semantic search degraded")
            self._bm25 = None

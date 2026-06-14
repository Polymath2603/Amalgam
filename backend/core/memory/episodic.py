"""Episodic memory — session-scoped ChromaDB storage."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """Stores and retrieves conversation episodes within a session."""

    def __init__(self, collection, session_id: str):
        self._collection = collection
        self._session_id = session_id

    def add_episode(self, turn: Dict) -> str:
        """Store a single turn as an episode. Returns the episode ID."""
        eid = str(uuid.uuid4())
        if self._collection is None:
            logger.debug(f"EpisodicMemory: chromadb unavailable, skipping episode {eid}")
            return eid
        metadata = {
            "session_id": self._session_id,
            "role": turn.get("role", "user"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._collection.add(
            documents=[turn.get("content", "")],
            metadatas=[metadata],
            ids=[eid],
        )
        logger.debug(f"EpisodicMemory: added episode {eid}")
        return eid

    def search(self, query: str, k: int = 5) -> List[Dict]:
        """Query episodes by semantic similarity."""
        if self._collection is None:
            return []
        results = self._collection.query(query_texts=[query], n_results=k)
        episodes = []
        for i, doc in enumerate(results.get("documents", [[]])[0]):
            episodes.append({
                "content": doc,
                "metadata": (results.get("metadatas", [[]])[0] or [{}])[i] if i < len(results.get("metadatas", [[]])[0] or []) else {},
                "score": (results.get("distances", [[]])[0] or [0])[i] if i < len(results.get("distances", [[]])[0] or []) else 0,
            })
        return episodes

    def count(self) -> int:
        if self._collection is None:
            return 0
        return self._collection.count()

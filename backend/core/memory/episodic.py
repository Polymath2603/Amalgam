"""Episodic memory — session-scoped ChromaDB storage."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """Stores and retrieves conversation episodes within a session."""

    def __init__(self, collection: Any, session_id: str) -> None:
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
            "timestamp": turn.get("timestamp", datetime.now(timezone.utc).isoformat()),
        }
        self._collection.add(
            documents=[turn.get("content", "")],
            metadatas=[metadata],
            ids=[eid],
        )
        logger.debug(f"EpisodicMemory: added episode {eid}")
        return eid

    def search(self, query: str, k: int = 5) -> List[Dict]:
        """Query episodes by semantic similarity, scoped to this session."""
        if self._collection is None:
            return []
        results = self._collection.query(
            query_texts=[query],
            n_results=k,
            where={"session_id": self._session_id},
        )
        episodes = []
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0] or []
        distances = (results.get("distances") or [[]])[0] or []
        for i, doc in enumerate(documents):
            episodes.append({
                "content": doc,
                "metadata": metadatas[i] if i < len(metadatas) else {},
                "score": distances[i] if i < len(distances) else 0,
            })
        return episodes

    def count(self) -> int:
        if self._collection is None:
            return 0
        return self._collection.count()

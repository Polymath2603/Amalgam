"""Consolidator — transfers working→episodic memory with importance scoring."""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Consolidator:
    """Periodically consolidates working memory into episodic storage."""

    def __init__(self, importance_threshold: float = 0.3):
        self._threshold = importance_threshold

    def consolidate(self, turns: List[Dict], episodic_store) -> int:
        """Score each working-memory turn and store important ones.

        Returns the number of episodes stored.
        """
        stored = 0
        for turn in turns:
            importance = self._score_importance(turn)
            if importance >= self._threshold:
                episodic_store.add_episode(turn)
                stored += 1
        logger.debug(f"Consolidator: stored {stored}/{len(turns)} episodes")
        return stored

    def _score_importance(self, turn: Dict) -> float:
        """Heuristic importance score 0..1 based on content signals."""
        content = turn.get("content", "")
        if not content:
            return 0.0

        score = 0.0

        # Length signal: longer turns are often more substantive
        if len(content) > 200:
            score += 0.2
        elif len(content) > 100:
            score += 0.1

        # Key-phrase signal
        important_phrases = ["remember", "important", "critical", "my name is",
                             "I am", "never", "always", "must", "plan", "goal"]
        for phrase in important_phrases:
            if phrase in content.lower():
                score += 0.15
                break

        # Question signal: assistant answers to questions are important
        if turn.get("role") == "assistant" and "?" in content:
            score += 0.1

        return min(score, 1.0)

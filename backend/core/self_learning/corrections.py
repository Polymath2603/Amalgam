"""
CorrectionStore — persistent learning from user corrections.

Detects when a user corrects the agent's behavior or output, stores the
correction with surrounding context, and retrieves relevant corrections
for similar future queries so the agent avoids repeating mistakes.

Patterns detected as corrections:
- Explicit: "no, I meant...", "that's wrong", "actually it's..."
- Behavioral: "don't do that", "stop...", "never mind"
- Preference: "I prefer...", "I'd rather..."
"""

import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.core.paths import DATA_DIR

logger = logging.getLogger(__name__)

# Phrases that strongly suggest a correction is happening
# Frozen so it cannot be mutated at runtime
_CORRECTION_PATTERNS = (
    re.compile(r"\bno[,.]?\s+(that|this|it|i)", re.I),
    re.compile(r"\bthat('s| is)\s+(wrong|incorrect|not|inaccurate)", re.I),
    re.compile(r"\bactually[,.]?\s+(it|that|i)", re.I),
    re.compile(r"\byou('re| are)\s+(wrong|incorrect|mistaken)", re.I),
    re.compile(r"\bi\s+(meant|meant to say)", re.I),
    re.compile(r"\bdon't\s+(do|use|say|assume)", re.I),
    re.compile(r"\bnever\s+(mind|do that)", re.I),
    re.compile(r"\bi'd?\s+(rather|prefer|like)", re.I),
    re.compile(r"\bplease\s+(don't|stop|correct)", re.I),
    re.compile(r"\bcorrection[: ]", re.I),
    re.compile(r"\bnot\s+what\s+i\s+(meant|wanted|asked)", re.I),
    re.compile(r"\bwrong\b", re.I),
    re.compile(r"\bmistake\b", re.I),
    re.compile(r"\bincorrect\b", re.I),
    re.compile(r"\bthat\s+doesn't\s+(make sense|work|help)", re.I),
    re.compile(r"\bno[,.]?\s+that('s| is)\s+not", re.I),
)

# Behavioral cues that suggest the user is correcting a behavior pattern
_BEHAVIOR_PATTERNS = (
    re.compile(r"\bstop\s+(using|doing|saying|being)", re.I),
    re.compile(r"\bdon't\s+(say|tell|ask|assume)", re.I),
    re.compile(r"\b(i'd|i would)\s+(rather|prefer)", re.I),
    re.compile(r"\bcan you\s+(not|stop)", re.I),
)


class CorrectionStore:
    """Stores and retrieves user corrections with contextual matching.

    Persists to a JSON file in the data directory.

    Responsibility boundaries:
    - Detection:  regex-based pattern matching
    - Storage:    JSON file persistence with deferred batched writes
    - Retrieval:  token-overlap scoring with deferred applied_count updates
    """

    CORRECTIONS_FILENAME = "corrections.json"

    def __init__(self, data_dir: Optional[str] = None):
        self._path = Path(data_dir or str(DATA_DIR)) / self.CORRECTIONS_FILENAME
        self._corrections: list[dict] = []
        self._pending_applied_updates: dict[str, int] = defaultdict(int)
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_correction(self, user_message: str, assistant_message: str = "") -> bool:
        """Check if a user message looks like a correction.

        Returns True if any correction pattern matches. For better precision,
        the caller should also consider message context (e.g., position in dialogue).
        """
        for pattern in _CORRECTION_PATTERNS:
            if pattern.search(user_message):
                return True
        # Short follow-up messages that contain behavioral cues
        if assistant_message and len(user_message) < 100:
            for pattern in _BEHAVIOR_PATTERNS:
                if pattern.search(user_message):
                    return True
        return False

    def extract_correction(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> Optional[dict]:
        """Extract and store a correction record. Returns the record or None on failure."""
        about = self._extract_about(user_message)

        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_message": user_message,
            "assistant_message": assistant_message[:500],
            "about": about,
            "applied_count": 0,
        }
        self._corrections.append(record)
        self._save()  # persist immediately — record durability is important
        logger.info(f"Stored correction: {about} (id={record['id'][:8]})")
        return record

    def find_relevant(self, query: str, max_results: int = 3) -> list[dict]:
        """Find corrections relevant to the current query by keyword matching.

        This is a read-only query except for deferred applied_count tracking.
        Writes are batched via _flush_if_needed() instead of synchronous per-call.
        """
        if not self._corrections:
            return []
        query_lower = query.lower()
        query_tokens = set(re.findall(r'\b\w{3,}\b', query_lower))
        if not query_tokens:
            return []

        scored: list[tuple[float, dict]] = []
        for c in self._corrections:
            about_lower = c.get("about", "").lower()
            msg_lower = c.get("user_message", "").lower()
            tokens = set(re.findall(r'\b\w{3,}\b', about_lower + " " + msg_lower))
            overlap = len(query_tokens & tokens)
            if overlap > 0:
                score = overlap / len(query_tokens)
                scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [dict(r) for _, r in scored[:max_results]]

        # Apply pending count updates and persist via batched flush
        for r in results:
            self._pending_applied_updates[r["id"]] += 1
        self._flush_if_needed()

        return results

    def to_context_string(self, query: str, max_results: int = 2) -> str:
        """Generate a compact string of relevant corrections for the system prompt.

        Returns empty string if no relevant corrections found.
        """
        relevant = self.find_relevant(query, max_results=max_results)
        if not relevant:
            return ""
        parts = ["## Corrections from previous sessions"]
        for c in relevant:
            about = c.get("about", "")
            msg = c.get("user_message", "")[:120]
            parts.append(f"- {about}: \"{msg}\"")
        return "\n".join(parts)

    def count(self) -> int:
        """Total stored corrections."""
        return len(self._corrections)

    def clear(self):
        """Clear all corrections."""
        self._corrections.clear()
        self._pending_applied_updates.clear()
        self._dirty = True
        self._save()

    def flush(self):
        """Force pending changes to disk."""
        if self._dirty:
            self._save()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _flush_if_needed(self):
        """Flush to disk when there are pending changes."""
        if self._dirty or self._pending_applied_updates:
            self._save()

    @staticmethod
    def _extract_about(user_message: str) -> str:
        """Extract what the correction is about from the user message."""
        # Remove leading correction markers
        text = re.sub(r"^(no|actually|correction)[,.\s]*", "", user_message, flags=re.I)
        text = text.strip()
        # Truncate to first sentence or 100 chars
        # Uses find with fallback instead of naive .find(".") to handle abbreviations
        for delim in (". ", "! ", "? "):
            idx = text.find(delim)
            if 10 < idx < 150:
                text = text[:idx]
                break
        return text[:100].strip()

    def _apply_pending_updates(self):
        """Apply all pending applied_count increments to the in-memory store."""
        if not self._pending_applied_updates:
            return
        id_to_idx = {c["id"]: i for i, c in enumerate(self._corrections)}
        for corr_id, inc in self._pending_applied_updates.items():
            idx = id_to_idx.get(corr_id)
            if idx is not None:
                self._corrections[idx]["applied_count"] = (
                    self._corrections[idx].get("applied_count", 0) + inc
                )
        self._pending_applied_updates.clear()

    def _load(self):
        if self._path.exists():
            try:
                self._corrections = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load corrections from {self._path}: {e}")
                self._corrections = []

    def _save(self):
        self._apply_pending_updates()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create corrections directory: {e}")
            return
        try:
            self._path.write_text(
                json.dumps(self._corrections, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error(f"Failed to save corrections: {e}")
            return
        self._dirty = False

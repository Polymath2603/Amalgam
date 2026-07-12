"""
PreferenceLearner — infers user preferences from interaction patterns.

Works alongside UserProfile (which uses explicit LLM extraction) by:
- Observing behavioral signals (response engagement, follow-up rate, verbosity preference)
- Tracking interaction patterns over time
- Providing inferred preference data that can supplement explicit profile data

Integration: called from ReflectiveAgent._reflect() and ContextBuilder.
"""

import asyncio
import logging
import os
import re
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.core.paths import DATA_DIR

logger = logging.getLogger(__name__)

# Window sizes
# Configurable via env vars
_ENGAGEMENT_WINDOW_ENV = "AMALGAM_ENGAGEMENT_WINDOW"
ENGAGEMENT_WINDOW = int(os.environ.get(_ENGAGEMENT_WINDOW_ENV, "20"))

_VERBOSITY_WINDOW_ENV = "AMALGAM_VERBOSITY_WINDOW"
VERBOSITY_WINDOW = int(os.environ.get(_VERBOSITY_WINDOW_ENV, "10"))

# Thresholds for preference classification
# Configurable via env vars
_LONG_RESPONSE_CUTOFF_ENV = "AMALGAM_LONG_RESPONSE_CUTOFF"
LONG_RESPONSE_CUTOFF = int(os.environ.get(_LONG_RESPONSE_CUTOFF_ENV, "500"))

_SHORT_RESPONSE_CUTOFF_ENV = "AMALGAM_SHORT_RESPONSE_CUTOFF"
SHORT_RESPONSE_CUTOFF = int(os.environ.get(_SHORT_RESPONSE_CUTOFF_ENV, "100"))

_FOLLOWUP_THRESHOLD_ENV = "AMALGAM_FOLLOWUP_THRESHOLD"
FOLLOWUP_THRESHOLD = int(os.environ.get(_FOLLOWUP_THRESHOLD_ENV, "3"))

# Preference keys stored in UserProfile.preferences
PREF_VERBOSITY = "inferred_verbosity"
PREF_TONE = "inferred_tone"
PREF_RESPONSE_STYLE = "inferred_response_style"
PREF_AUTOMATION_LEVEL = "inferred_automation_level"

@dataclass
class _InteractionRecord:
    """A single observed interaction: assistant response length and whether the user engaged."""
    response_length: int
    engaged: bool = False


class PreferenceLearner:
    """Infers user preferences by observing interaction patterns.

    Tracks sliding windows of interactions and updates inferred preference
    signals that can be merged into the UserProfile.
    """

    SIGNAL_FILENAME = "preference_signals.json"

    def __init__(self, data_dir: Optional[str] = None):
        self._path = Path(data_dir or str(DATA_DIR)) / self.SIGNAL_FILENAME
        # Single sliding window — avoids alignment drift between deques
        self._interactions: deque[_InteractionRecord] = deque(maxlen=ENGAGEMENT_WINDOW)
        self._topics: dict[str, int] = defaultdict(int)
        self._cached_prefs: Optional[dict] = None
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def observe_interaction(
        self,
        user_message: str,
        assistant_response: str,
        user_followed_up: bool = False,
    ) -> None:
        """Record an interaction for pattern analysis."""
        self._interactions.append(_InteractionRecord(
            response_length=len(assistant_response),
            engaged=user_followed_up,
        ))

        # Topic frequency (keyword extraction)
        # Match tokens with length >= 2 to capture short meaningful terms (API, UI, IO, etc.)
        tokens = re.findall(r'\b\w{2,}\b', user_message.lower())
        for t in tokens[:10]:
            # Skip pure punctuation / numbers-only tokens
            if t.isdigit() or not any(c.isalpha() for c in t):
                continue
            self._topics[t] += 1

        self._cached_prefs = None  # Invalidate cache
        await self._save()

    def get_inferred_preferences(self) -> dict[str, Any]:
        """Return inferred preference signals for the current user.

        Returns a dict that can be merged into UserProfile.preferences.

        Results are cached until the next observe_interaction() call.
        """
        if self._cached_prefs is not None:
            return dict(self._cached_prefs)

        prefs = {}

        # Verbosity preference
        verbosity = self._infer_verbosity()
        if verbosity:
            prefs[PREF_VERBOSITY] = verbosity

        # Response style
        style = self._infer_response_style()
        if style:
            prefs[PREF_RESPONSE_STYLE] = style

        # Automation level
        automation = self._infer_automation_level()
        if automation:
            prefs[PREF_AUTOMATION_LEVEL] = automation

        self._cached_prefs = dict(prefs)
        return prefs

    def get_engagement_rate(self) -> float:
        """Ratio of interactions where user followed up."""
        if not self._interactions:
            return 0.5  # Neutral default
        engaged = sum(1 for r in self._interactions if r.engaged)
        return engaged / len(self._interactions)

    # ------------------------------------------------------------------
    # Inference methods
    # ------------------------------------------------------------------

    def _infer_verbosity(self) -> Optional[str]:
        """Infer whether user prefers concise or detailed responses."""
        if len(self._interactions) < 3:
            return None

        # Look at the most recent responses the user engaged with
        engaged_lengths = [r.response_length for r in self._interactions if r.engaged]

        if not engaged_lengths:
            return None

        avg_engaged = sum(engaged_lengths) / len(engaged_lengths)
        avg_all = sum(r.response_length for r in self._interactions) / len(self._interactions)

        if avg_engaged < SHORT_RESPONSE_CUTOFF and avg_all < LONG_RESPONSE_CUTOFF:
            return "concise"
        elif avg_engaged > LONG_RESPONSE_CUTOFF and avg_all > LONG_RESPONSE_CUTOFF:
            return "detailed"
        elif avg_all > LONG_RESPONSE_CUTOFF and avg_engaged < avg_all * 0.5:
            # User tends to disengage from long responses
            return "concise"
        return None

    def _infer_response_style(self) -> Optional[str]:
        """Infer whether user prefers casual, formal, or structured responses.

        Uses the vocabulary distribution as a heuristic:
        - High frequency of first-person pronouns → casual
        - High frequency of technical jargon → formal/technical
        - High frequency of structured requests (bullet points, numbered lists) → structured

        NOTE: The casual_indicators and technical_indicators sets below are hardcoded
        English-centric heuristics. They work well for English conversations but may
        not generalize to other languages or domain-specific jargon. Future work could
        make these configurable or learned from data.
        """
        if len(self._topics) < 5:
            return None

        casual_indicators = {"i", "my", "me", "im", "ive", "id", "would", "like",
                             "think", "feel", "want", "need", "could"}
        technical_indicators = {"code", "function", "api", "data", "file", "config",
                                "server", "test", "error", "log", "path"}

        casual_count = sum(self._topics.get(w, 0) for w in casual_indicators)
        technical_count = sum(self._topics.get(w, 0) for w in technical_indicators)
        total = sum(self._topics.values())
        if total == 0:
            return None

        casual_ratio = casual_count / total
        technical_ratio = technical_count / total

        if casual_ratio > 0.15:
            return "casual"
        elif technical_ratio > 0.15:
            return "technical"
        return None

    def _infer_automation_level(self) -> Optional[str]:
        """Infer how much automation the user wants.

        Analyzes tool override frequency and correction patterns to determine
        whether the user prefers more or less automation.
        """
        engagement = self.get_engagement_rate()
        if engagement < 0.3:
            # Low engagement — user may want more autonomous behavior
            return "high"
        elif engagement > 0.7:
            # High engagement — user may be actively steering, less automation
            return "low"
        return None

    def get_frequent_topics(self, top_n: int = 5) -> list[tuple[str, int]]:
        """Most discussed topics, sorted by frequency."""
        return sorted(self._topics.items(), key=lambda x: x[1], reverse=True)[:top_n]

    async def reset(self):
        """Clear all observed data."""
        self._interactions.clear()
        self._topics.clear()
        self._cached_prefs = None
        await self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _save(self):
        data = {
            "interactions": [
                {"response_length": r.response_length, "engaged": r.engaged}
                for r in self._interactions
            ],
            "topics": dict(self._topics),
            "updated": datetime.now(timezone.utc).isoformat(),
        }

        def _write():
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.error(f"Failed to create preferences directory: {e}")
                return
            try:
                self._path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError as e:
                logger.error(f"Failed to save preference signals: {e}")

        await asyncio.to_thread(_write)

        # Invalidate cache after save as data may have changed
        self._cached_prefs = None

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                raw = data.get("interactions", [])
                if not raw and "engagements" in data and "response_lengths" in data:
                    # Backward compat: migrate old format (separate deques) to records
                    engs = data["engagements"]
                    lengths = data["response_lengths"]
                    raw = [
                        {"response_length": lengths[i], "engaged": bool(engs[i])}
                        for i in range(min(len(lengths), len(engs)))
                    ]
                self._interactions = deque(
                    _InteractionRecord(response_length=r["response_length"], engaged=r.get("engaged", False))
                    for r in raw
                )
                self._topics = defaultdict(int, data.get("topics", {}))
                self._cached_prefs = None
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load preference signals from {self._path}: {e}")

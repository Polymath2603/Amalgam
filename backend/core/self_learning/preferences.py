"""
PreferenceLearner — infers user preferences from interaction patterns.

Works alongside UserProfile (which uses explicit LLM extraction) by:
- Observing behavioral signals (response engagement, follow-up rate, verbosity preference)
- Tracking interaction patterns over time
- Providing inferred preference data that can supplement explicit profile data

Integration: called from ReflectiveAgent._reflect() and ContextBuilder.
"""

import logging
import re
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Window sizes
ENGAGEMENT_WINDOW = 20  # Last N interactions for engagement tracking
VERBOSITY_WINDOW = 10   # Last N assistant responses for verbosity analysis

# Thresholds for preference classification
LONG_RESPONSE_CUTOFF = 500    # chars — "long" response
SHORT_RESPONSE_CUTOFF = 100   # chars — "short" response
FOLLOWUP_THRESHOLD = 3        # min user message length to count as engagement

# Preference keys stored in UserProfile.preferences
PREF_VERBOSITY = "inferred_verbosity"
PREF_TONE = "inferred_tone"
PREF_RESPONSE_STYLE = "inferred_response_style"
PREF_AUTOMATION_LEVEL = "inferred_automation_level"


class PreferenceLearner:
    """Infers user preferences by observing interaction patterns.

    Tracks sliding windows of interactions and updates inferred preference
    signals that can be merged into the UserProfile.
    """

    SIGNAL_FILENAME = "preference_signals.json"

    def __init__(self, data_dir: str = "data"):
        self._path = Path(data_dir) / self.SIGNAL_FILENAME
        # Sliding windows
        self._engagements: deque = deque(maxlen=ENGAGEMENT_WINDOW)
        self._response_lengths: deque = deque(maxlen=VERBOSITY_WINDOW)
        self._topics: dict[str, int] = defaultdict(int)
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe_interaction(
        self,
        user_message: str,
        assistant_response: str,
        user_followed_up: bool = False,
    ) -> None:
        """Record an interaction for pattern analysis."""
        # Response length tracking
        self._response_lengths.append(len(assistant_response))

        # Engagement: did the user follow up meaningfully?
        self._engagements.append(1 if user_followed_up else 0)

        # Topic frequency (simple keyword extraction from user message)
        tokens = re.findall(r'\b\w{4,}\b', user_message.lower())
        for t in tokens[:10]:
            self._topics[t] += 1

        self._save()

    def get_inferred_preferences(self) -> dict[str, Any]:
        """Return inferred preference signals for the current user.

        Returns a dict that can be merged into UserProfile.preferences.
        """
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

        return prefs

    def get_engagement_rate(self) -> float:
        """Ratio of interactions where user followed up."""
        if not self._engagements:
            return 0.5  # Neutral default
        return sum(self._engagements) / len(self._engagements)

    # ------------------------------------------------------------------
    # Inference methods
    # ------------------------------------------------------------------

    def _infer_verbosity(self) -> Optional[str]:
        """Infer whether user prefers concise or detailed responses."""
        if len(self._response_lengths) < 3:
            return None

        # Look at the most recent responses the user engaged with
        engaged_lengths = []
        for i in range(min(len(self._engagements), len(self._response_lengths))):
            if self._engagements[i]:
                engaged_lengths.append(self._response_lengths[i])

        if not engaged_lengths:
            return None

        avg_engaged = sum(engaged_lengths) / len(engaged_lengths)
        avg_all = sum(self._response_lengths) / len(self._response_lengths)

        if avg_engaged < SHORT_RESPONSE_CUTOFF and avg_all < LONG_RESPONSE_CUTOFF:
            return "concise"
        elif avg_engaged > LONG_RESPONSE_CUTOFF and avg_all > LONG_RESPONSE_CUTOFF:
            return "detailed"
        elif avg_all > LONG_RESPONSE_CUTOFF and avg_engaged < avg_all * 0.5:
            # User tends to disengage from long responses
            return "concise"
        return None

    def _infer_response_style(self) -> Optional[str]:
        """Infer whether user prefers casual, formal, or structured responses."""
        if len(self._response_lengths) < 5:
            return None
        # Placeholder — in practice, this would use topic + engagement analysis
        # For now, return neutral if we don't have enough signal
        return None

    def _infer_automation_level(self) -> Optional[str]:
        """Infer how much automation the user wants."""
        if len(self._response_lengths) < 5:
            return None
        # If user frequently corrects or overrides tool usage,
        # they may prefer less automation. Placeholder for now.
        return None

    def get_frequent_topics(self, top_n: int = 5) -> list[tuple[str, int]]:
        """Most discussed topics, sorted by frequency."""
        return sorted(self._topics.items(), key=lambda x: x[1], reverse=True)[:top_n]

    def reset(self):
        """Clear all observed data."""
        self._engagements.clear()
        self._response_lengths.clear()
        self._topics.clear()
        self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self):
        data = {
            "engagements": list(self._engagements),
            "response_lengths": list(self._response_lengths),
            "topics": dict(self._topics),
            "updated": datetime.now(timezone.utc).isoformat(),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error(f"Failed to save preference signals: {e}")

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._engagements = deque(data.get("engagements", []), maxlen=ENGAGEMENT_WINDOW)
                self._response_lengths = deque(data.get("response_lengths", []), maxlen=VERBOSITY_WINDOW)
                self._topics = defaultdict(int, data.get("topics", {}))
            except (json.JSONDecodeError, OSError):
                pass

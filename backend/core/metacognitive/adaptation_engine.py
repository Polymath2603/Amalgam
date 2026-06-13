"""Long-term adaptation based on accumulated delta history."""

from collections import deque
from typing import Optional


class AdaptationEngine:
    """Maintains strategy state from rolling-window delta scores."""

    STRATEGIES = ("default", "conservative", "creative", "precise")

    def __init__(self, window: int = 10):
        self._history: deque[dict] = deque(maxlen=window)
        self._strategy = "default"

    def ingest(self, delta: dict) -> dict:
        """Record a turn delta and return adaptation recommendations."""
        self._history.append(delta)
        avg = self._rolling_avg()

        recommendations = []

        if avg["aggregate"] < 0.4:
            self._strategy = "conservative"
            recommendations.append("Reduce tool parallelisation; increase context window")
        elif avg["aggregate"] > 0.85:
            self._strategy = "creative"
            recommendations.append("Increase tool access; allow longer completions")
        elif avg["response_time"] < 0.5 and avg["tool_success"] > 0.8:
            self._strategy = "precise"
            recommendations.append("Prefer smaller models; tighten token budget")
        else:
            self._strategy = "default"
            recommendations.append("Maintain current configuration")

        return {
            "strategy": self._strategy,
            "average_delta": avg,
            "recommendations": recommendations,
        }

    def current_strategy(self) -> str:
        return self._strategy

    def reset(self):
        self._history.clear()
        self._strategy = "default"

    # --- Internal ---

    def _rolling_avg(self) -> dict:
        if not self._history:
            return {k: 0.5 for k in ("response_time", "coherence", "relevance",
                                     "tool_success", "token_efficiency", "aggregate")}
        n = len(self._history)
        sums: dict[str, float] = {}
        for d in self._history:
            for k, v in d.items():
                sums[k] = sums.get(k, 0.0) + v
        return {k: v / n for k, v in sums.items()}

"""Long-term adaptation based on accumulated delta history."""

from collections import deque
from typing import Any


# ── Strategy constants ───────────────────────────────────────────
STRATEGY_DEFAULT = "default"
STRATEGY_CONSERVATIVE = "conservative"
STRATEGY_CREATIVE = "creative"
STRATEGY_PRECISE = "precise"

# ── Thresholds (calibrated empirically) ──────────────────────────
LOW_AGGREGATE_THRESHOLD = 0.4       # below this → conservative
HIGH_AGGREGATE_THRESHOLD = 0.85     # above this → creative
PRECISE_RESPONSE_TIME_MAX = 0.5     # fast response → eligible for precise
PRECISE_TOOL_SUCCESS_MIN = 0.8      # high tool success → eligible for precise
DEFAULT_ROLLING_WINDOW = 10


class AdaptationEngine:
    """Maintains strategy state from rolling-window delta scores."""

    STRATEGIES = (STRATEGY_DEFAULT, STRATEGY_CONSERVATIVE, STRATEGY_CREATIVE, STRATEGY_PRECISE)

    def __init__(self, window: int = DEFAULT_ROLLING_WINDOW):
        self._history: deque[dict[str, Any]] = deque(maxlen=window)
        self._strategy = STRATEGY_DEFAULT

    def ingest(self, delta: dict) -> dict:
        """Record a turn delta and return adaptation recommendations.

        Raises TypeError if *delta* is not a dict.
        Raises ValueError if *delta* is missing required keys.
        """
        if not isinstance(delta, dict):
            raise TypeError(f"Expected dict for delta, got {type(delta).__name__}")

        # Validate required keys
        required = ("aggregate", "response_time", "tool_success")
        missing = [k for k in required if k not in delta]
        if missing:
            raise ValueError(f"Delta missing required keys: {missing}")

        self._history.append(delta)
        avg = self._rolling_avg()

        recommendations: list[str] = []

        # Evaluate precise conditions first (operational signals) before
        # aggregate-level quality signals, so the precise branch is not
        # shadowed by conservative/creative.
        if avg["response_time"] < PRECISE_RESPONSE_TIME_MAX and avg["tool_success"] > PRECISE_TOOL_SUCCESS_MIN:
            self._strategy = STRATEGY_PRECISE
            recommendations.append("Prefer smaller models; tighten token budget")
        elif avg["aggregate"] < LOW_AGGREGATE_THRESHOLD:
            self._strategy = STRATEGY_CONSERVATIVE
            recommendations.append("Reduce tool parallelisation; increase context window")
        elif avg["aggregate"] > HIGH_AGGREGATE_THRESHOLD:
            self._strategy = STRATEGY_CREATIVE
            recommendations.append("Increase tool access; allow longer completions")
        else:
            self._strategy = STRATEGY_DEFAULT
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
        self._strategy = STRATEGY_DEFAULT

    # --- Internal ---

    def _rolling_avg(self) -> dict[str, float]:
        """Compute per-key rolling average over stored history.

        Returns the same 6 keys (with default 0.5) regardless of whether
        history is empty, ensuring downstream code never sees a KeyError.
        """
        default_keys = ("response_time", "coherence", "relevance",
                        "tool_success", "token_efficiency", "aggregate")
        if not self._history:
            return {k: 0.5 for k in default_keys}

        n = len(self._history)
        sums: dict[str, float] = {}
        for d in self._history:
            for k in default_keys:
                v = d.get(k, 0.5)
                sums[k] = sums.get(k, 0.0) + v
        return {k: v / n for k, v in sums.items()}

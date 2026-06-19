"""Meta-cognitive engine — orchestrates strategy selection, delta evaluation, and adaptation."""

import logging
from typing import Any

from backend.core.metacognitive.strategy_selector import StrategySelector, Intent
from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
from backend.core.metacognitive.adaptation_engine import AdaptationEngine

logger = logging.getLogger(__name__)


class MetaCognitiveEngine:
    """Wraps strategy selection, per-turn evaluation, and adaptation into one coordinator.

    Accepts optional dependency injection for all three sub-components to enable
    testing with mocks and alternative implementations.
    """

    def __init__(
        self,
        window: int = 10,
        strategy_selector: StrategySelector | None = None,
        delta_evaluator: DeltaEvaluator | None = None,
        adaptation: AdaptationEngine | None = None,
    ):
        self.strategy_selector = strategy_selector or StrategySelector()
        self.delta_evaluator = delta_evaluator or DeltaEvaluator()
        self.adaptation = adaptation or AdaptationEngine(window=window)

    def select(self, intent: Intent, delta_history: list[float] | None = None) -> Any:
        """Pick a strategy for the given intent, factoring in recent deltas."""
        logger.debug("Selecting strategy for intent=%s with %d deltas",
                     intent, len(delta_history) if delta_history else 0)
        return self.strategy_selector.select(intent, delta_history)

    def evaluate(self, turn: dict) -> dict:
        """Score a single turn across all quality axes.

        Raises TypeError if *turn* is not a dict.
        """
        if not isinstance(turn, dict):
            raise TypeError(f"Expected dict for turn, got {type(turn).__name__}")
        logger.debug("Evaluating turn with %d keys", len(turn))
        return self.delta_evaluator.score(turn)

    def adapt(self, delta: dict) -> dict:
        """Feed a delta into the adaptation engine and return recommendations.

        Raises TypeError if *delta* is not a dict.
        """
        if not isinstance(delta, dict):
            raise TypeError(f"Expected dict for delta, got {type(delta).__name__}")
        logger.debug("Adapting with delta aggregate=%s", delta.get("aggregate", "unknown"))
        return self.adaptation.ingest(delta)

    def record_outcome(self, intent: Intent, delta: float, strategy: Any):
        """Log an outcome so the selector can adjust future choices."""
        logger.debug("Recording outcome: intent=%s delta=%s", intent, delta)
        self.strategy_selector.record_outcome(intent, delta, strategy)

    def current_strategy(self) -> str:
        """Return the current adaptation strategy label."""
        return self.adaptation.current_strategy()

    def reset(self):
        """Clear all recorded state across sub-components."""
        self.strategy_selector.reset()
        self.adaptation.reset()

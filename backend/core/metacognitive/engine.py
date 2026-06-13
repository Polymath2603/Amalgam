"""Meta-cognitive engine — orchestrates strategy selection, delta evaluation, and adaptation."""

import logging
from typing import Any

from backend.core.metacognitive.strategy_selector import StrategySelector, Intent
from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
from backend.core.metacognitive.adaptation_engine import AdaptationEngine

logger = logging.getLogger(__name__)


class MetaCognitiveEngine:
    """Wraps strategy selection, per-turn evaluation, and adaptation into one coordinator."""

    def __init__(self, window: int = 10):
        self.strategy_selector = StrategySelector()
        self.delta_evaluator = DeltaEvaluator()
        self.adaptation = AdaptationEngine(window=window)

    def select(self, intent: Intent, delta_history: list[float] | None = None):
        """Pick a strategy for the given intent, factoring in recent deltas."""
        return self.strategy_selector.select(intent, delta_history)

    def evaluate(self, turn: dict) -> dict:
        """Score a single turn across all quality axes."""
        return self.delta_evaluator.score(turn)

    def adapt(self, delta: dict) -> dict:
        """Feed a delta into the adaptation engine and return recommendations."""
        return self.adaptation.ingest(delta)

    def record_outcome(self, intent: Intent, delta: float, strategy: Any):
        """Log an outcome so the selector can adjust future choices."""
        self.strategy_selector.record_outcome(intent, delta, strategy)

    def current_strategy(self) -> str:
        return self.adaptation.current_strategy()

    def reset(self):
        self.strategy_selector._history.clear()
        self.adaptation.reset()

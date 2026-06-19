"""Strategy selection — maps intents to LLM configurations and adapts based on outcome history."""

from collections import deque
from dataclasses import dataclass
from typing import Literal

Intent = Literal["conversation", "tool_execution", "code", "reflection", "memory_op", "vault_op"]

# ── Named constants ──────────────────────────────────────────────
LOW_DELTA_THRESHOLD = -0.1          # average below this triggers adaptation
TEMPERATURE_PENALTY = 0.2           # amount to reduce temperature on low deltas
MIN_TEMPERATURE = 0.1               # floor after penalty
HISTORY_CAP = 100                   # max recorded outcomes
DELTA_HISTORY_MIN = 3               # min recent deltas needed before adapting


@dataclass
class LLMStrategy:
    temperature: float
    max_iterations: int
    use_chain_of_thought: bool
    max_output_tokens: int


STRATEGIES: dict[Intent, LLMStrategy] = {
    "tool_execution":  LLMStrategy(0.2, 5,  False, 2048),
    "conversation":    LLMStrategy(0.8, 1,  False, 2048),
    "code":            LLMStrategy(0.3, 3,  True,  4096),
    "reflection":      LLMStrategy(0.6, 1,  True,  1024),
    "memory_op":       LLMStrategy(0.4, 2,  False, 512),
    "vault_op":        LLMStrategy(0.3, 2,  False, 1024),
}


class StrategySelector:
    """Selects an LLMStrategy for a given intent, adapting based on recent delta history."""

    def __init__(self):
        self._history: deque[dict] = deque(maxlen=HISTORY_CAP)

    def select(self, intent: Intent, delta_history: list[float] | None = None) -> LLMStrategy:
        """Return the best strategy for *intent*, optionally adjusting via recent deltas."""
        base = STRATEGIES.get(intent, STRATEGIES["conversation"])

        # Defensive: ensure delta_history is usable
        if delta_history is None:
            return base

        # Filter out None / non-float entries silently
        cleaned = [d for d in delta_history if isinstance(d, (int, float))]
        if len(cleaned) < DELTA_HISTORY_MIN:
            return base

        recent_avg = sum(cleaned[-DELTA_HISTORY_MIN:]) / DELTA_HISTORY_MIN
        if recent_avg < LOW_DELTA_THRESHOLD:
            return LLMStrategy(
                temperature=max(MIN_TEMPERATURE, base.temperature - TEMPERATURE_PENALTY),
                max_iterations=base.max_iterations,
                use_chain_of_thought=True,
                max_output_tokens=base.max_output_tokens,
            )
        return base

    def record_outcome(self, intent: Intent, delta: float, strategy: LLMStrategy):
        """Record a turn outcome for future adaptation."""
        # Guard against invalid inputs
        if not isinstance(delta, (int, float)):
            delta = 0.0
        self._history.append({
            "intent": intent,
            "delta": delta,
            "temperature": strategy.temperature,
            "max_iterations": strategy.max_iterations,
            "use_chain_of_thought": strategy.use_chain_of_thought,
            "max_output_tokens": strategy.max_output_tokens,
        })

    def reset(self):
        """Clear all recorded outcome history."""
        self._history.clear()

from dataclasses import dataclass
from typing import Literal

Intent = Literal["conversation", "tool_execution", "code", "reflection", "memory_op", "vault_op"]


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
    def __init__(self):
        self._history: list[dict] = []

    def select(self, intent: Intent, delta_history: list[float] | None = None) -> LLMStrategy:
        base = STRATEGIES.get(intent, STRATEGIES["conversation"])
        if delta_history and len(delta_history) >= 3:
            recent_avg = sum(delta_history[-3:]) / 3
            if recent_avg < -0.1:
                return LLMStrategy(
                    temperature=max(0.1, base.temperature - 0.2),
                    max_iterations=base.max_iterations,
                    use_chain_of_thought=True,
                    max_output_tokens=base.max_output_tokens,
                )
        return base

    def record_outcome(self, intent: Intent, delta: float, strategy: LLMStrategy):
        self._history.append({
            "intent": intent,
            "delta": delta,
            "temperature": strategy.temperature,
        })
        if len(self._history) > 100:
            self._history.pop(0)

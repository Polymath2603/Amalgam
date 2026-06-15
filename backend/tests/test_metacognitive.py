"""Tests for the metacognitive engine (StrategySelector, DeltaEvaluator)."""

import pytest
from backend.core.metacognitive.strategy_selector import StrategySelector, STRATEGIES


class TestStrategySelector:
    def test_select_returns_base_strategy(self):
        selector = StrategySelector()
        for intent in ("conversation", "tool_execution", "code", "reflection", "memory_op", "vault_op"):
            strategy = selector.select(intent)
            assert strategy is not None
            assert hasattr(strategy, "temperature")
            assert hasattr(strategy, "max_iterations")
            assert hasattr(strategy, "use_chain_of_thought")
            assert hasattr(strategy, "max_output_tokens")

    def test_select_defaults_to_conversation(self):
        selector = StrategySelector()
        strategy = selector.select("unknown_intent")  # type: ignore
        assert strategy.temperature == STRATEGIES["conversation"].temperature

    def test_delta_history_adapts_low_delta(self):
        selector = StrategySelector()
        # 3 consistently negative deltas should lower temperature
        strategy = selector.select("tool_execution", delta_history=[-0.2, -0.3, -0.25])
        assert strategy.temperature < STRATEGIES["tool_execution"].temperature
        assert strategy.use_chain_of_thought is True

    def test_delta_history_ignores_short_history(self):
        selector = StrategySelector()
        strategy = selector.select("conversation", delta_history=[-0.2])
        assert strategy.temperature == STRATEGIES["conversation"].temperature

    def test_delta_history_ignores_mild_delta(self):
        selector = StrategySelector()
        strategy = selector.select("tool_execution", delta_history=[-0.05, 0.0, -0.02])
        assert strategy.temperature == STRATEGIES["tool_execution"].temperature

    def test_record_outcome_caps_history(self):
        selector = StrategySelector()
        for _ in range(150):
            selector.record_outcome("conversation", 0.1, STRATEGIES["conversation"])
        assert len(selector._history) <= 100

    def test_record_outcome_stores_data(self):
        selector = StrategySelector()
        selector.record_outcome("code", 0.5, STRATEGIES["code"])
        assert len(selector._history) == 1
        assert selector._history[0]["intent"] == "code"
        assert selector._history[0]["delta"] == 0.5

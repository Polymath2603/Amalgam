"""
BRUTAL TESTS for Metacognitive engine — boundary values, extreme histories,
concurrent access, and overflow conditions.

Catches: empty histories, extreme deltas, history overflow, concurrent
strategy selection, and NaN/Inf in metrics.
"""
import threading
import pytest
from backend.core.metacognitive.strategy_selector import StrategySelector, LLMStrategy, STRATEGIES
from backend.core.metacognitive.delta_evaluator import DeltaEvaluator


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
        strategy = selector.select("unknown_intent")
        assert strategy.temperature == STRATEGIES["conversation"].temperature

    def test_delta_history_adapts_low_delta(self):
        selector = StrategySelector()
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


class TestStrategySelectorBrutal:
    def test_select_empty_string_intent(self):
        selector = StrategySelector()
        strategy = selector.select("")
        assert strategy is not None
        assert strategy.temperature == STRATEGIES["conversation"].temperature

    def test_select_extreme_positive_delta(self):
        selector = StrategySelector()
        strategy = selector.select("conversation", delta_history=[0.5, 0.5, 0.5])
        assert strategy is not None

    def test_select_extreme_negative_delta(self):
        selector = StrategySelector()
        strategy = selector.select("conversation", delta_history=[-1.0, -1.0, -1.0])
        assert strategy is not None
        assert strategy.temperature <= STRATEGIES["conversation"].temperature

    def test_select_with_nan_delta(self):
        selector = StrategySelector()
        import math
        strategy = selector.select("conversation", delta_history=[float("nan")] * 3)
        assert strategy is not None

    def test_select_with_inf_delta(self):
        selector = StrategySelector()
        import math
        strategy = selector.select("conversation", delta_history=[float("inf")] * 3)
        assert strategy is not None

    def test_record_1000_outcomes(self):
        selector = StrategySelector()
        for i in range(1000):
            selector.record_outcome("conversation", (i % 10) / 10, STRATEGIES["conversation"])
        assert len(selector._history) <= 100

    def test_record_negative_delta(self):
        selector = StrategySelector()
        selector.record_outcome("code", -0.5, STRATEGIES["code"])
        assert selector._history[0]["delta"] == -0.5

    def test_concurrent_record(self):
        selector = StrategySelector()
        errors = []
        def record(i):
            try:
                selector.record_outcome("conversation", i / 10, STRATEGIES["conversation"])
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=record, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0

    def test_all_intents_have_strategy(self):
        """Every intent type should map to a strategy."""
        for intent in STRATEGIES:
            selector = StrategySelector()
            strategy = selector.select(intent)
            assert strategy is not None, f"No strategy for intent: {intent}"

    def test_strategy_has_required_fields(self):
        selector = StrategySelector()
        strategy = selector.select("conversation")
        assert isinstance(strategy.temperature, (int, float))
        assert isinstance(strategy.max_iterations, int)
        assert isinstance(strategy.use_chain_of_thought, bool)
        assert isinstance(strategy.max_output_tokens, int)

    def test_concurrent_select(self):
        selector = StrategySelector()
        errors = []
        results = []
        def select_strategy(intent):
            try:
                s = selector.select(intent)
                results.append(s)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=select_strategy, args=("conversation",)) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert len(results) == 50


class TestDeltaEvaluator:
    def test_score_returns_all_axes(self):
        evaluator = DeltaEvaluator()
        result = evaluator.score({"latency_ms": 1000, "coherence": 0.8, "relevance": 0.9,
                                  "tool_errors": 0, "prompt_tokens": 100, "completion_tokens": 50})
        for axis in ("response_time", "coherence", "relevance", "tool_success",
                     "token_efficiency", "aggregate"):
            assert axis in result
            assert 0.0 <= result[axis] <= 1.0

    def test_score_response_time_fast(self):
        assert DeltaEvaluator()._score_response_time(500) == 1.0
        assert DeltaEvaluator()._score_response_time(1999) == 1.0

    def test_score_response_time_slow(self):
        assert DeltaEvaluator()._score_response_time(5000) < 1.0
        assert DeltaEvaluator()._score_response_time(5000) > 0.0
        assert DeltaEvaluator()._score_response_time(10000) == 0.0

    def test_score_response_time_zero(self):
        assert DeltaEvaluator()._score_response_time(0) == 1.0

    def test_score_coherence_and_relevance_clamped(self):
        e = DeltaEvaluator()
        assert e._score_coherence(1.5) == 1.0
        assert e._score_coherence(-0.5) == 0.0
        assert e._score_relevance(0.7) == 0.7

    def test_score_tool_success_no_errors(self):
        assert DeltaEvaluator()._score_tool_success(0) == 1.0

    def test_score_tool_success_with_errors(self):
        assert pytest.approx(DeltaEvaluator()._score_tool_success(1), abs=0.01) == 0.67


class TestDeltaEvaluatorBrutal:
    def test_score_negative_latency(self):
        e = DeltaEvaluator()
        result = e._score_response_time(-1000)
        assert isinstance(result, (int, float))

    def test_score_huge_latency(self):
        e = DeltaEvaluator()
        result = e._score_response_time(1_000_000)
        assert result == 0.0

    def test_score_tool_success_many_errors(self):
        e = DeltaEvaluator()
        result = e._score_tool_success(100)
        assert result == 0.0

    def test_score_with_nan_metrics(self):
        import math
        e = DeltaEvaluator()
        result = e.score({
            "latency_ms": float("nan"),
            "coherence": 0.5,
            "relevance": 0.5,
            "tool_errors": 0,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        })
        assert isinstance(result, dict)
        for v in result.values():
            assert isinstance(v, (int, float))

    def test_score_with_zero_tokens(self):
        e = DeltaEvaluator()
        result = e.score({
            "latency_ms": 1000,
            "coherence": 0.5,
            "relevance": 0.5,
            "tool_errors": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        })
        assert "token_efficiency" in result

    def test_score_all_axes_in_0_1_range(self):
        """For any reasonable input, all axes should be in [0, 1]."""
        e = DeltaEvaluator()
        for latency in [100, 500, 1000, 5000, 10000]:
            result = e.score({
                "latency_ms": latency,
                "coherence": 0.5,
                "relevance": 0.5,
                "tool_errors": 0,
                "prompt_tokens": 1000,
                "completion_tokens": 500,
            })
            for axis, val in result.items():
                assert 0.0 <= val <= 1.0, f"{axis}={val} out of range for latency={latency}"

    def test_empty_metrics(self):
        e = DeltaEvaluator()
        result = e.score({})
        assert isinstance(result, dict)

    def test_concurrent_score(self):
        e = DeltaEvaluator()
        errors = []
        def score():
            try:
                e.score({"latency_ms": 1000, "coherence": 0.8, "relevance": 0.9,
                         "tool_errors": 0, "prompt_tokens": 100, "completion_tokens": 50})
            except Exception as ex:
                errors.append(ex)
        threads = [threading.Thread(target=score) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
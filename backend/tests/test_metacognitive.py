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


class TestDeltaEvaluator:
    def test_score_returns_all_axes(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        evaluator = DeltaEvaluator()
        result = evaluator.score({"latency_ms": 1000, "coherence": 0.8, "relevance": 0.9, "tool_errors": 0, "prompt_tokens": 100, "completion_tokens": 50})
        for axis in ("response_time", "coherence", "relevance", "tool_success", "token_efficiency", "aggregate"):
            assert axis in result
            assert 0.0 <= result[axis] <= 1.0

    def test_score_response_time_fast(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        assert DeltaEvaluator()._score_response_time(500) == 1.0
        assert DeltaEvaluator()._score_response_time(1999) == 1.0

    def test_score_response_time_slow(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        assert DeltaEvaluator()._score_response_time(5000) < 1.0
        assert DeltaEvaluator()._score_response_time(5000) > 0.0
        assert DeltaEvaluator()._score_response_time(10000) == 0.0

    def test_score_response_time_zero(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        assert DeltaEvaluator()._score_response_time(0) == 1.0

    def test_score_coherence_and_relevance_clamped(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        e = DeltaEvaluator()
        assert e._score_coherence(1.5) == 1.0
        assert e._score_coherence(-0.5) == 0.0
        assert e._score_relevance(0.7) == 0.7

    def test_score_tool_success_no_errors(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        assert DeltaEvaluator()._score_tool_success(0) == 1.0

    def test_score_tool_success_with_errors(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        assert pytest.approx(DeltaEvaluator()._score_tool_success(1), abs=0.01) == 0.67
        assert pytest.approx(DeltaEvaluator()._score_tool_success(3), abs=0.01) == 0.01
        assert DeltaEvaluator()._score_tool_success(10) == 0.0

    def test_score_token_efficiency_balanced(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        assert DeltaEvaluator()._score_token_efficiency(100, 100) == 1.0

    def test_score_token_efficiency_extreme_ratio(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        assert DeltaEvaluator()._score_token_efficiency(1000, 10) == 0.3
        assert DeltaEvaluator()._score_token_efficiency(10, 1000) == 0.5

    def test_score_token_efficiency_zero_total(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        assert DeltaEvaluator()._score_token_efficiency(0, 0) == 1.0

    def test_integration_score_aggregate(self):
        from backend.core.metacognitive.delta_evaluator import DeltaEvaluator
        result = DeltaEvaluator().score({
            "latency_ms": 1000, "coherence": 0.9, "relevance": 0.8,
            "tool_errors": 0, "prompt_tokens": 100, "completion_tokens": 150,
        })
        assert result["aggregate"] == pytest.approx((1.0 + 0.9 + 0.8 + 1.0 + 1.0) / 5, rel=0.01)


class TestAdaptationEngine:
    def test_init_default_strategy(self):
        from backend.core.metacognitive.adaptation_engine import AdaptationEngine
        engine = AdaptationEngine(window=5)
        assert engine.current_strategy() == "default"
        assert len(engine._history) == 0

    def test_ingest_sets_conservative_on_low_delta(self):
        from backend.core.metacognitive.adaptation_engine import AdaptationEngine
        engine = AdaptationEngine(window=5)
        low_delta = {"aggregate": 0.3, "response_time": 0.2, "tool_success": 0.5,
                     "coherence": 0.4, "relevance": 0.3, "token_efficiency": 0.5}
        result = engine.ingest(low_delta)
        assert result["strategy"] == "conservative"
        assert engine.current_strategy() == "conservative"

    def test_ingest_sets_creative_on_high_delta(self):
        from backend.core.metacognitive.adaptation_engine import AdaptationEngine
        engine = AdaptationEngine(window=5)
        high_delta = {"aggregate": 0.9, "response_time": 0.9, "tool_success": 0.9,
                      "coherence": 0.9, "relevance": 0.9, "token_efficiency": 0.9}
        result = engine.ingest(high_delta)
        assert result["strategy"] == "creative"

    def test_ingest_sets_precise_on_fast_high_tool_success(self):
        from backend.core.metacognitive.adaptation_engine import AdaptationEngine
        engine = AdaptationEngine(window=5)
        delta = {"aggregate": 0.6, "response_time": 0.3, "tool_success": 0.9,
                 "coherence": 0.7, "relevance": 0.7, "token_efficiency": 0.7}
        result = engine.ingest(delta)
        assert result["strategy"] == "precise"

    def test_rolling_avg_empty(self):
        from backend.core.metacognitive.adaptation_engine import AdaptationEngine
        avg = AdaptationEngine(window=5)._rolling_avg()
        for k in ("response_time", "coherence", "relevance", "tool_success", "token_efficiency", "aggregate"):
            assert avg[k] == 0.5

    def test_rolling_avg_single_entry(self):
        from backend.core.metacognitive.adaptation_engine import AdaptationEngine
        engine = AdaptationEngine(window=5)
        d = {"aggregate": 0.8, "response_time": 0.7, "tool_success": 0.9,
             "coherence": 0.8, "relevance": 0.8, "token_efficiency": 0.7}
        engine.ingest(d)
        avg = engine._rolling_avg()
        assert avg["aggregate"] == 0.8

    def test_rolling_avg_multiple_entries(self):
        from backend.core.metacognitive.adaptation_engine import AdaptationEngine
        engine = AdaptationEngine(window=10)
        for i in range(4):
            engine.ingest({"aggregate": 0.5 + i * 0.1, "response_time": 0.5, "tool_success": 0.5,
                           "coherence": 0.5, "relevance": 0.5, "token_efficiency": 0.5})
        assert engine._rolling_avg()["aggregate"] == 0.65

    def test_window_caps_history(self):
        from backend.core.metacognitive.adaptation_engine import AdaptationEngine
        engine = AdaptationEngine(window=3)
        for i in range(10):
            engine.ingest({"aggregate": 0.5, "response_time": 0.5, "tool_success": 0.5,
                           "coherence": 0.5, "relevance": 0.5, "token_efficiency": 0.5})
        assert len(engine._history) == 3

    def test_reset_clears(self):
        from backend.core.metacognitive.adaptation_engine import AdaptationEngine
        engine = AdaptationEngine(window=5)
        engine.ingest({"aggregate": 0.3, "response_time": 0.2, "tool_success": 0.5,
                       "coherence": 0.4, "relevance": 0.3, "token_efficiency": 0.5})
        engine.reset()
        assert engine.current_strategy() == "default"
        assert len(engine._history) == 0

    def test_recommendations_in_result(self):
        from backend.core.metacognitive.adaptation_engine import AdaptationEngine
        engine = AdaptationEngine(window=5)
        d = {"aggregate": 0.3, "response_time": 0.2, "tool_success": 0.5,
             "coherence": 0.4, "relevance": 0.3, "token_efficiency": 0.5}
        result = engine.ingest(d)
        assert "recommendations" in result
        assert len(result["recommendations"]) >= 1


class TestMetaCognitiveEngine:
    def test_init_wires_components(self):
        from backend.core.metacognitive.engine import MetaCognitiveEngine
        mce = MetaCognitiveEngine(window=5)
        assert mce.strategy_selector is not None
        assert mce.delta_evaluator is not None
        assert mce.adaptation is not None

    def test_select_delegates(self):
        from backend.core.metacognitive.engine import MetaCognitiveEngine
        mce = MetaCognitiveEngine()
        strategy = mce.select("code")
        assert strategy is not None

    def test_evaluate_delegates(self):
        from backend.core.metacognitive.engine import MetaCognitiveEngine
        mce = MetaCognitiveEngine()
        result = mce.evaluate({"latency_ms": 0, "coherence": 1.0, "relevance": 1.0,
                                "tool_errors": 0, "prompt_tokens": 100, "completion_tokens": 100})
        assert "aggregate" in result
        assert result["aggregate"] == 1.0

    def test_adapt_delegates(self):
        from backend.core.metacognitive.engine import MetaCognitiveEngine
        mce = MetaCognitiveEngine(window=5)
        d = {"aggregate": 0.3, "response_time": 0.2, "tool_success": 0.5,
             "coherence": 0.4, "relevance": 0.3, "token_efficiency": 0.5}
        result = mce.adapt(d)
        assert result["strategy"] == "conservative"

    def test_record_outcome_delegates(self):
        from backend.core.metacognitive.engine import MetaCognitiveEngine
        from backend.core.metacognitive.strategy_selector import STRATEGIES
        mce = MetaCognitiveEngine()
        mce.record_outcome("conversation", 0.5, STRATEGIES["conversation"])
        assert len(mce.strategy_selector._history) == 1

    def test_current_strategy(self):
        from backend.core.metacognitive.engine import MetaCognitiveEngine
        mce = MetaCognitiveEngine()
        assert mce.current_strategy() == "default"

    def test_reset(self):
        from backend.core.metacognitive.engine import MetaCognitiveEngine
        mce = MetaCognitiveEngine(window=5)
        mce.record_outcome("code", 0.5, type("s", (), {"temperature": 0.7})())
        assert len(mce.strategy_selector._history) >= 1
        mce.reset()
        assert len(mce.strategy_selector._history) == 0
        assert mce.current_strategy() == "default"

    def test_full_pipeline(self):
        from backend.core.metacognitive.engine import MetaCognitiveEngine
        mce = MetaCognitiveEngine(window=5)
        # Simulate a full turn: select → evaluate → adapt → record
        strategy = mce.select("tool_execution")
        score = mce.evaluate({
            "latency_ms": 3000, "coherence": 0.7, "relevance": 0.6,
            "tool_errors": 0, "prompt_tokens": 200, "completion_tokens": 100,
        })
        delta = {"aggregate": score["aggregate"], "response_time": score["response_time"],
                 "coherence": score["coherence"], "relevance": score["relevance"],
                 "tool_success": score["tool_success"], "token_efficiency": score["token_efficiency"]}
        adapt_result = mce.adapt(delta)
        mce.record_outcome("tool_execution", score["aggregate"], strategy)
        assert adapt_result["strategy"] in ("default", "conservative", "creative", "precise")
        assert len(mce.strategy_selector._history) == 1

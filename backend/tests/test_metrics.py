"""Tests for the MetricsCollector and cost estimation."""

import pytest
from backend.core.metrics import MetricsCollector, TurnMetrics, estimate_cost, COST_TABLE


class TestCostEstimation:
    def test_known_model_cost(self):
        cost = estimate_cost("anthropic", "claude-sonnet-4-6", 1000, 500)
        assert cost > 0
        # 1000 input tokens * $3/1M + 500 output * $15/1M
        expected = (1000 / 1_000_000 * 3.0) + (500 / 1_000_000 * 15.0)
        assert abs(cost - expected) < 0.001

    def test_unknown_model_returns_zero(self):
        cost = estimate_cost("unknown", "model", 100, 100)
        assert cost == 0.0

    def test_local_model_zero_cost(self):
        cost = estimate_cost("ollama", "llama2", 5000, 500)
        assert cost == 0.0

    def test_openai_gpt4o(self):
        cost = estimate_cost("openai", "gpt-4o", 1000, 1000)
        expected = (1000 / 1_000_000 * 2.5) + (1000 / 1_000_000 * 10.0)
        assert abs(cost - expected) < 0.001

    def test_deepseek_chat(self):
        cost = estimate_cost("deepseek", "deepseek-chat", 1_000_000, 0)
        assert cost == 0.27

    def test_zero_tokens(self):
        cost = estimate_cost("openai", "gpt-4o", 0, 0)
        assert cost == 0.0

    def test_provider_prefix_matching(self):
        """Unknown model with known provider prefix should match by provider."""
        cost = estimate_cost("ollama", "custom-model", 100, 100)
        assert cost == 0.0


class TestTurnMetrics:
    def test_minimal_creation(self):
        tm = TurnMetrics(session_id="test-session")
        assert tm.session_id == "test-session"
        assert tm.model == ""
        assert tm.input_tokens == 0
        assert tm.output_tokens == 0

    def test_custom_values(self):
        tm = TurnMetrics(session_id="s1", model="m1", provider="p1",
                         input_tokens=10, output_tokens=5, latency_ms=100,
                         tool_calls=2, memory_hits=1)
        assert tm.session_id == "s1"
        assert tm.model == "m1"
        assert tm.provider == "p1"
        assert tm.input_tokens == 10
        assert tm.output_tokens == 5
        assert tm.latency_ms == 100
        assert tm.tool_calls == 2
        assert tm.memory_hits == 1


class TestMetricsCollector:
    def test_init_fallback_no_aiosqlite(self, monkeypatch):
        monkeypatch.setattr("backend.core.metrics.aiosqlite", None)
        mc = MetricsCollector(":memory:")
        import asyncio
        result = asyncio.run(mc._ensure_init())
        assert result is None

    def test_record_disabled(self, monkeypatch):
        monkeypatch.setattr("backend.core.metrics.aiosqlite", None)
        mc = MetricsCollector(":memory:")
        import asyncio
        result = asyncio.run(mc.record(TurnMetrics(session_id="s1")))
        assert result is None

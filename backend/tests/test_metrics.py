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


class TestMetricsSQLite:
    @pytest.mark.asyncio
    async def test_ensure_init_creates_table(self, tmp_path):
        db_path = str(tmp_path / "test_metrics.db")
        mc = MetricsCollector(db_path)
        await mc._ensure_init()
        assert mc._initialized is True
        assert mc.db_path.exists()

    @pytest.mark.asyncio
    async def test_record_and_query(self, tmp_path):
        db_path = str(tmp_path / "test_metrics.db")
        mc = MetricsCollector(db_path)
        await mc.record(TurnMetrics(
            session_id="s1", model="gemini/gemini-2.5-flash", provider="gemini",
            input_tokens=100, output_tokens=50, latency_ms=500,
            tool_calls=2, memory_hits=3,
        ))

        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM turns")).fetchone()
            assert row is not None
            assert row["session_id"] == "s1"
            assert row["model"] == "gemini/gemini-2.5-flash"
            assert row["provider"] == "gemini"
            assert row["input_tokens"] == 100
            assert row["output_tokens"] == 50
            assert row["latency_ms"] == 500.0
            assert row["tool_calls"] == 2
            assert row["memory_hits"] == 3
            # cost should be auto-calculated
            assert row["cost_usd"] > 0

    @pytest.mark.asyncio
    async def test_record_multiple_turns(self, tmp_path):
        db_path = str(tmp_path / "multi.db")
        mc = MetricsCollector(db_path)
        for i in range(5):
            await mc.record(TurnMetrics(
                session_id=f"s{i}", model="openai/gpt-4o", provider="openai",
                input_tokens=100, output_tokens=100,
            ))

        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            count = await (await db.execute("SELECT COUNT(*) FROM turns")).fetchone()
            assert count[0] == 5

    @pytest.mark.asyncio
    async def test_weekly_report_returns_structure(self, tmp_path):
        db_path = str(tmp_path / "weekly.db")
        mc = MetricsCollector(db_path)
        await mc.record(TurnMetrics(
            session_id="s1", model="gemini/gemini-2.5-flash", provider="gemini",
            input_tokens=1000, output_tokens=500, latency_ms=1000,
            tool_calls=3, memory_hits=2,
        ))
        report = await mc.weekly_report()
        assert report["total_turns"] >= 1
        assert report["total_tokens"] > 0
        assert report["total_cost_usd"] > 0
        assert report["avg_latency_ms"] > 0
        assert report["total_tool_calls"] >= 3
        assert len(report["top_models"]) >= 1

    @pytest.mark.asyncio
    async def test_weekly_report_empty_no_aiosqlite(self, monkeypatch):
        monkeypatch.setattr("backend.core.metrics.aiosqlite", None)
        mc = MetricsCollector(":memory:")
        report = await mc.weekly_report()
        assert report["total_turns"] == 0
        assert report["total_cost_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_record_gracefully_handles_error(self, tmp_path):
        mc = MetricsCollector(str(tmp_path / "metrics.db"))
        # Should not raise
        await mc.record(TurnMetrics(session_id="s1"))

    @pytest.mark.asyncio
    async def test_cost_auto_calculated(self, tmp_path):
        db_path = str(tmp_path / "cost.db")
        mc = MetricsCollector(db_path)
        await mc.record(TurnMetrics(
            session_id="s1", model="gpt-4o", provider="openai",
            input_tokens=1_000_000, output_tokens=0,
        ))
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            row = await (await db.execute("SELECT cost_usd FROM turns")).fetchone()
            assert row[0] == 2.50  # $2.50/M input tokens for gpt-4o

    @pytest.mark.asyncio
    async def test_cost_with_explicit_value(self, tmp_path):
        db_path = str(tmp_path / "cost2.db")
        mc = MetricsCollector(db_path)
        await mc.record(TurnMetrics(
            session_id="s1", model="gpt-4o", provider="openai",
            input_tokens=1000, output_tokens=1000,
            cost_usd=0.50,  # explicit
        ))
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            row = await (await db.execute("SELECT cost_usd FROM turns")).fetchone()
            assert row[0] == 0.50

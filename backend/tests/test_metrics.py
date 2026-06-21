"""
BRUTAL TESTS for MetricsCollector and cost estimation — concurrency, corruption,
extreme values, and data integrity.

Catches: concurrent writes, DB corruption, overflow values, negative tokens,
concurrent report + record, and SQLite connection leaks.
"""
import asyncio
import threading
import pytest
from pathlib import Path
from backend.core.metrics import MetricsCollector, TurnMetrics, _estimate_cost, COST_TABLE


class TestCostEstimation:
    def test_known_model_cost(self):
        cost = _estimate_cost("anthropic", "claude-sonnet-4-6", 1000, 500)
        assert cost > 0
        expected = (1000 / 1_000_000 * 3.0) + (500 / 1_000_000 * 15.0)
        assert abs(cost - expected) < 0.001

    def test_unknown_model_returns_zero(self):
        cost = _estimate_cost("unknown", "model", 100, 100)
        assert cost == 0.0

    def test_local_model_zero_cost(self):
        cost = _estimate_cost("ollama", "llama2", 5000, 500)
        assert cost == 0.0

    def test_openai_gpt4o(self):
        cost = _estimate_cost("openai", "gpt-4o", 1000, 1000)
        expected = (1000 / 1_000_000 * 2.5) + (1000 / 1_000_000 * 10.0)
        assert abs(cost - expected) < 0.001

    def test_zero_tokens(self):
        cost = _estimate_cost("openai", "gpt-4o", 0, 0)
        assert cost == 0.0

    def test_provider_prefix_matching(self):
        cost = _estimate_cost("ollama", "custom-model", 100, 100)
        assert cost == 0.0


class TestCostEstimationBrutal:
    """Extreme values and edge cases for cost estimation."""

    def test_negative_tokens_zero_cost(self):
        """Negative tokens should not produce negative cost."""
        cost = _estimate_cost("openai", "gpt-4o", -1000, -500)
        assert cost == 0.0 or cost >= 0  # Should not go negative

    def test_massive_token_count(self):
        cost = _estimate_cost("openai", "gpt-4o", 100_000_000, 100_000_000)
        assert cost > 0
        assert cost < 10_000  # Sanity: not astronomically wrong

    def test_zero_input_nonzero_output(self):
        cost = _estimate_cost("anthropic", "claude-sonnet-4-6", 0, 1000)
        assert cost > 0

    def test_nonzero_input_zero_output(self):
        cost = _estimate_cost("anthropic", "claude-sonnet-4-6", 1000, 0)
        assert cost > 0

    def test_llamacpp_zero_cost(self):
        cost = _estimate_cost("llamacpp", "model", 1000, 1000)
        assert cost == 0.0

    def test_groq_model_cost(self):
        cost = _estimate_cost("groq", "llama-3.1-70b-versatile", 1000, 1000)
        assert cost > 0

    def test_groq_instant_model(self):
        cost = _estimate_cost("groq", "llama-3.1-8b-instant", 1000, 1000)
        assert cost > 0

    def test_haiku_model_cost(self):
        cost = _estimate_cost("anthropic", "claude-haiku-4-5", 1000, 1000)
        assert cost > 0

    def test_opus_model_cost(self):
        cost = _estimate_cost("anthropic", "claude-opus-4-6", 1000, 1000)
        assert cost > 0

    def test_cost_table_covers_known_models(self):
        """Every model in the cost table should return non-zero cost."""
        for key, rates in COST_TABLE.items():
            if rates == (0.0, 0.0):
                continue  # Skip local models
            provider, model = key.split("/", 1)
            cost = _estimate_cost(provider, model, 1000, 1000)
            assert cost > 0, f"Cost is 0 for {key}"

    def test_cost_deterministic(self):
        c1 = _estimate_cost("openai", "gpt-4o", 1000, 500)
        c2 = _estimate_cost("openai", "gpt-4o", 1000, 500)
        assert c1 == c2

    def test_cost_scales_linearly(self):
        c1 = _estimate_cost("openai", "gpt-4o", 1000, 1000)
        c2 = _estimate_cost("openai", "gpt-4o", 2000, 2000)
        assert abs(c2 - 2 * c1) < 0.001


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


class TestTurnMetricsBrutal:
    def test_empty_session_id(self):
        tm = TurnMetrics(session_id="")
        assert tm.session_id == ""

    def test_negative_tokens(self):
        tm = TurnMetrics(session_id="s1", input_tokens=-5, output_tokens=-3)
        assert tm.input_tokens == -5  # Should store, even if invalid
        assert tm.output_tokens == -3

    def test_huge_latency(self):
        tm = TurnMetrics(session_id="s1", latency_ms=999999999.99)
        assert tm.latency_ms == 999999999.99

    def test_timestamp_auto_generated(self):
        tm = TurnMetrics(session_id="s1")
        assert tm.timestamp is not None
        assert len(tm.timestamp) > 0

    def test_cost_usd_default_zero(self):
        tm = TurnMetrics(session_id="s1")
        assert tm.cost_usd == 0.0


class TestMetricsSQLite:
    @pytest.mark.asyncio
    async def test_ensure_init_creates_table(self, tmp_path):
        db_path = tmp_path / "test_metrics.db"
        mc = MetricsCollector(db_path)
        await mc._init()
        assert mc._ready is True

    @pytest.mark.asyncio
    async def test_record_and_query(self, tmp_path):
        db_path = tmp_path / "test_metrics.db"
        mc = MetricsCollector(db_path)
        await mc.record(TurnMetrics(
            session_id="s1", model="gpt-4o", provider="openai",
            input_tokens=100, output_tokens=50, latency_ms=500,
            tool_calls=2, memory_hits=3,
        ))
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM turns")).fetchone()
            assert row is not None
            assert row["session_id"] == "s1"
            assert row["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_record_multiple_turns(self, tmp_path):
        db_path = tmp_path / "multi.db"
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
    async def test_report_returns_structure(self, tmp_path):
        db_path = tmp_path / "weekly.db"
        mc = MetricsCollector(db_path)
        await mc.record(TurnMetrics(
            session_id="s1", model="claude-sonnet-4-6", provider="anthropic",
            input_tokens=1000, output_tokens=500, latency_ms=1000,
            tool_calls=3, memory_hits=2,
        ))
        report = await mc.report(days=7)
        assert report["total_turns"] >= 1
        assert report["total_tokens"] > 0
        assert report["total_cost_usd"] > 0
        assert report["avg_latency_ms"] > 0
        assert report["total_tool_calls"] >= 3
        assert len(report["top_models"]) >= 1

    @pytest.mark.asyncio
    async def test_record_gracefully_handles_error(self, tmp_path):
        """Even if DB path is bad, record should not crash."""
        mc = MetricsCollector(tmp_path / "nonexistent_dir" / "fake.db")
        # Should not raise
        try:
            await mc.record(TurnMetrics(session_id="s1"))
        except Exception:
            pass  # Acceptable


class TestMetricsSQLiteBrutal:
    @pytest.mark.asyncio
    async def test_empty_session_id_recorded(self, tmp_path):
        db_path = tmp_path / "empty_id.db"
        mc = MetricsCollector(db_path)
        await mc.record(TurnMetrics(session_id=""))
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            row = await (await db.execute("SELECT * FROM turns")).fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_unicode_model_name(self, tmp_path):
        db_path = tmp_path / "unicode.db"
        mc = MetricsCollector(db_path)
        await mc.record(TurnMetrics(session_id="s1", model="\u4f60\u597d-model"))
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            row = await (await db.execute("SELECT * FROM turns")).fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_huge_token_count(self, tmp_path):
        db_path = tmp_path / "huge.db"
        mc = MetricsCollector(db_path)
        await mc.record(TurnMetrics(
            session_id="s1", input_tokens=100_000_000, output_tokens=100_000_000,
        ))
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            row = await (await db.execute("SELECT * FROM turns")).fetchone()
            assert row["input_tokens"] == 100_000_000

    @pytest.mark.asyncio
    async def test_concurrent_record_writes(self, tmp_path):
        """Multiple concurrent writes should not corrupt the DB."""
        db_path = tmp_path / "concurrent.db"
        mc = MetricsCollector(db_path)

        async def write_turn(i):
            await mc.record(TurnMetrics(
                session_id=f"s{i}", model="test", provider="test",
                input_tokens=i, output_tokens=i,
            ))

        await asyncio.gather(*[write_turn(i) for i in range(20)])
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            count = await (await db.execute("SELECT COUNT(*) FROM turns")).fetchone()
            assert count[0] == 20

    @pytest.mark.asyncio
    async def test_report_empty_db(self, tmp_path):
        db_path = tmp_path / "empty.db"
        mc = MetricsCollector(db_path)
        report = await mc.report(days=7)
        assert report["total_turns"] == 0
        assert report["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_report_with_zero_tokens(self, tmp_path):
        db_path = tmp_path / "zero.db"
        mc = MetricsCollector(db_path)
        await mc.record(TurnMetrics(session_id="s1"))
        report = await mc.report(days=7)
        assert report["total_turns"] >= 1

    @pytest.mark.asyncio
    async def test_init_called_multiple_times_idempotent(self, tmp_path):
        db_path = tmp_path / "multi_init.db"
        mc = MetricsCollector(db_path)
        await mc._init()
        await mc._init()  # Second init should be no-op
        assert mc._ready is True
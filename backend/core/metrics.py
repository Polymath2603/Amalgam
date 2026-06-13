"""
MetricsCollector — persistent per-turn metrics for cost tracking and observability.

Records every LLM turn (tokens, model, latency, tools, costs) into a local
SQLite database at ``data/metrics.db``.  Provides convenience queries
(weekly_report) and an estimate_cost helper for up-front token cost estimation.

Usage::

    from backend.core.metrics import MetricsCollector, TurnMetrics

    _metrics = MetricsCollector("data/metrics.db")

    # After each LLM call:
    await _metrics.record(TurnMetrics(
        session_id=session_id,
        model=model_name,
        provider=provider_name,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=latency_ms,
        tool_calls=len(tool_calls),
        memory_hits=len(memory_results),
    ))
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import aiosqlite
except ImportError:
    aiosqlite = None
    logger.warning("aiosqlite not installed — metrics will be disabled")


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class TurnMetrics:
    """All measurements for one agent turn."""
    session_id: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    tool_calls: int = 0
    memory_hits: int = 0       # number of memory results actually injected
    skill_used: Optional[str] = None
    skill_created: bool = False
    correction_applied: bool = False
    cross_session_hits: int = 0
    preference_used: Optional[str] = None
    # cost_usd is calculated automatically in record()
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

# Approximate cost per 1M tokens (update as pricing changes)
# Format: provider/model → (input_cost_per_1m, output_cost_per_1m)
COST_TABLE = {
    "anthropic/claude-opus-4-6":    (15.00, 75.00),
    "anthropic/claude-sonnet-4-6":  (3.00,  15.00),
    "anthropic/claude-haiku-4-5":   (0.25,  1.25),
    "openai/gpt-4o":                (2.50,  10.00),
    "openai/gpt-4o-mini":           (0.15,  0.60),
    "groq/llama-3.1-70b-versatile": (0.59,  0.79),
    "groq/llama-3.1-8b-instant":    (0.05,  0.08),
    # Local models cost $0
    "ollama/":                      (0.00,  0.00),
    "llamacpp/":                    (0.00,  0.00),
}


def estimate_cost(provider: str, model: str,
                  input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for this LLM call."""
    key = f"{provider}/{model}"

    # Try exact match first, then prefix match
    rates = COST_TABLE.get(key)
    if not rates:
        for k, v in COST_TABLE.items():
            if key.startswith(k.split("/")[0]):  # match by provider prefix
                rates = v
                break

    if not rates:
        return 0.0

    input_cost = (input_tokens / 1_000_000) * rates[0]
    output_cost = (output_tokens / 1_000_000) * rates[1]
    return round(input_cost + output_cost, 6)


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class MetricsCollector:

    def __init__(self, db_path: str = "data/metrics.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def _ensure_init(self):
        if self._initialized:
            return
        if aiosqlite is None:
            logger.warning("aiosqlite unavailable — metrics db not created")
            return
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    model TEXT,
                    provider TEXT,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    latency_ms REAL DEFAULT 0.0,
                    tool_calls INTEGER DEFAULT 0,
                    memory_hits INTEGER DEFAULT 0,
                    skill_used TEXT,
                    skill_created INTEGER DEFAULT 0,
                    correction_applied INTEGER DEFAULT 0,
                    cross_session_hits INTEGER DEFAULT 0,
                    preference_used TEXT
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON turns(timestamp)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_session ON turns(session_id)")
            await db.commit()
        self._initialized = True

    async def record(self, m: TurnMetrics):
        """Record one turn's metrics. Never raises — silently logs errors."""
        try:
            await self._ensure_init()
            if aiosqlite is None:
                return
            # Calculate cost if not provided
            if m.cost_usd == 0.0:
                m.cost_usd = estimate_cost(
                    m.provider, m.model,
                    m.input_tokens, m.output_tokens,
                )

            async with aiosqlite.connect(str(self.db_path)) as db:
                await db.execute("""
                    INSERT INTO turns
                    (session_id, timestamp, model, provider, input_tokens, output_tokens,
                     cost_usd, latency_ms, tool_calls, memory_hits, skill_used, skill_created,
                     correction_applied, cross_session_hits, preference_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    m.session_id, m.timestamp, m.model, m.provider,
                    m.input_tokens, m.output_tokens, m.cost_usd,
                    m.latency_ms, m.tool_calls, m.memory_hits,
                    m.skill_used, int(m.skill_created),
                    int(getattr(m, 'correction_applied', False)),
                    int(getattr(m, 'cross_session_hits', 0)),
                    getattr(m, 'preference_used', None),
                ))
                await db.commit()
        except Exception as e:
            logger.debug(f"Metrics record error (non-fatal): {e}")

    async def weekly_report(self) -> dict:
        """Generate a summary of the last 7 days."""
        await self._ensure_init()
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()

        if aiosqlite is None:
            return _default_report()

        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row

            # Total stats
            row = await (await db.execute("""
                SELECT
                    COUNT(*) as total_turns,
                    COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens,
                    COALESCE(SUM(cost_usd), 0) as total_cost_usd,
                    COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
                    COALESCE(SUM(tool_calls), 0) as total_tool_calls,
                    COALESCE(AVG(memory_hits), 0) as avg_memory_hits
                FROM turns WHERE timestamp >= ?
            """, (week_ago,))).fetchone()

            report = dict(row) if row else _default_report()
            report["avg_memory_hits_per_turn"] = round(report.get("avg_memory_hits", 0), 1)
            report["avg_latency_ms"] = round(report.get("avg_latency_ms", 0), 0)

            # Top models
            rows = await (await db.execute("""
                SELECT model, COUNT(*) as uses,
                       COALESCE(SUM(cost_usd), 0) as cost
                FROM turns WHERE timestamp >= ?
                GROUP BY model ORDER BY uses DESC LIMIT 5
            """, (week_ago,))).fetchall()
            report["top_models"] = [dict(r) for r in rows]

            # Top skills
            rows = await (await db.execute("""
                SELECT skill_used, COUNT(*) as uses
                FROM turns WHERE timestamp >= ? AND skill_used IS NOT NULL
                GROUP BY skill_used ORDER BY uses DESC LIMIT 5
            """, (week_ago,))).fetchall()
            report["top_skills"] = [dict(r) for r in rows]

            return report


def _default_report() -> dict:
    return {
        "total_turns": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "avg_latency_ms": 0.0,
        "total_tool_calls": 0,
        "avg_memory_hits_per_turn": 0.0,
        "top_models": [],
        "top_skills": [],
    }

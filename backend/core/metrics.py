"""
Per-turn metrics collection. Answers: what did this session cost?
Which model? How long did it take? Did memory retrieval help?

Written to data/metrics.db (SQLite) via fire-and-forget asyncio tasks.
Never raises — if metrics fail, the main response is unaffected.

Source: AgenticFlow throughput tracking + OpenJarvis energy-per-inference model.
CLI: python -m backend stats [--days N]
"""
import aiosqlite
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
METRICS_DB = Path("data/metrics.db")

# Cost table: provider/model -> (input_$/1M, output_$/1M)
COST_TABLE = {
    "anthropic/claude-opus-4-6":       (15.00, 75.00),
    "anthropic/claude-sonnet-4-6":     (3.00,  15.00),
    "anthropic/claude-haiku-4-5":      (0.25,  1.25),
    "openai/gpt-4o":                   (2.50,  10.00),
    "openai/gpt-4o-mini":              (0.15,  0.60),
    "groq/llama-3.1-70b-versatile":    (0.59,  0.79),
    "groq/llama-3.1-8b-instant":       (0.05,  0.08),
    # Local models are free
    "ollama/":  (0.0, 0.0),
    "llamacpp/": (0.0, 0.0),
}


def _estimate_cost(provider: str, model: str, in_tok: int, out_tok: int) -> float:
    key = f"{provider}/{model}"
    rates = COST_TABLE.get(key)
    if not rates:
        for k, v in COST_TABLE.items():
            if key.startswith(k.rstrip("/")):
                rates = v
                break
    if not rates:
        return 0.0
    return round((in_tok / 1_000_000) * rates[0] + (out_tok / 1_000_000) * rates[1], 6)


@dataclass
class TurnMetrics:
    session_id: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    tool_calls: int = 0
    memory_hits: int = 0
    skill_used: Optional[str] = None
    skill_created: bool = False


class MetricsCollector:
    def __init__(self, db_path: Path = METRICS_DB):
        self.db = db_path
        self._ready = False

    async def _init(self):
        if self._ready:
            return
        async with aiosqlite.connect(self.db) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    timestamp TEXT,
                    model TEXT,
                    provider TEXT,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    latency_ms REAL DEFAULT 0.0,
                    tool_calls INTEGER DEFAULT 0,
                    memory_hits INTEGER DEFAULT 0,
                    skill_used TEXT,
                    skill_created INTEGER DEFAULT 0
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ts ON turns(timestamp)")
            await db.commit()
        self._ready = True

    async def record(self, m: TurnMetrics):
        """Fire-and-forget. Never raises."""
        try:
            await self._init()
            if m.cost_usd == 0.0:
                m.cost_usd = _estimate_cost(
                    m.provider, m.model, m.input_tokens, m.output_tokens
                )
            async with aiosqlite.connect(self.db) as db:
                await db.execute(
                    "INSERT INTO turns VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (m.session_id, m.timestamp, m.model, m.provider,
                     m.input_tokens, m.output_tokens, m.cost_usd,
                     m.latency_ms, m.tool_calls, m.memory_hits,
                     m.skill_used, int(m.skill_created)),
                )
                await db.commit()
        except Exception as e:
            logger.debug(f"Metrics record error (non-fatal): {e}")

    async def report(self, days: int = 7) -> dict:
        """Returns summary stats for the last N days."""
        await self._init()
        since = (datetime.now() - timedelta(days=days)).isoformat()
        async with aiosqlite.connect(self.db) as db:
            db.row_factory = aiosqlite.Row
            r = await (await db.execute("""
                SELECT COUNT(*) turns, SUM(cost_usd) cost,
                       SUM(input_tokens+output_tokens) tokens,
                       AVG(latency_ms) latency, SUM(tool_calls) tools,
                       AVG(memory_hits) mem_hits
                FROM turns WHERE timestamp > ?
            """, (since,))).fetchone()
            models = await (await db.execute("""
                SELECT model, COUNT(*) uses, SUM(cost_usd) cost
                FROM turns WHERE timestamp > ?
                GROUP BY model ORDER BY uses DESC LIMIT 5
            """, (since,))).fetchall()
            skills = await (await db.execute("""
                SELECT skill_used, COUNT(*) uses
                FROM turns WHERE timestamp > ? AND skill_used IS NOT NULL
                GROUP BY skill_used ORDER BY uses DESC LIMIT 10
            """, (since,))).fetchall()

        return {
            "period_days": days,
            "total_turns": r["turns"] or 0,
            "total_cost_usd": round(r["cost"] or 0, 4),
            "total_tokens": r["tokens"] or 0,
            "avg_latency_ms": round(r["latency"] or 0, 1),
            "total_tool_calls": r["tools"] or 0,
            "avg_memory_hits": round(r["mem_hits"] or 0, 2),
            "top_models": [dict(x) for x in models],
            "top_skills": [dict(x) for x in skills],
        }


# Module-level singleton
_collector = MetricsCollector()


async def record_turn(m: TurnMetrics):
    """Convenience: fire-and-forget wrapper."""
    import asyncio
    asyncio.create_task(_collector.record(m))


def get_collector() -> MetricsCollector:
    return _collector

"""
Metrics API route — exposes tool analytics and per-turn metrics.
"""

import time
import logging
from collections import defaultdict, deque
from typing import Optional

from fastapi import APIRouter
from backend.core.deps import get_shared
from backend.core.deprecated import deprecated

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])

# In-memory per-turn metrics store (bounded deque)
_turns: deque = deque(maxlen=500)


def record_turn(
    token_in: int = 0,
    token_out: int = 0,
    latency_ms: float = 0.0,
    cost: float = 0.0,
    model: str = "",
    tools_used: int = 0,
    errors: int = 0,
):
    """Record one conversation turn. Called by handler after each response."""
    global _turns
    entry = {
        "timestamp": time.time(),
        "token_in": token_in,
        "token_out": token_out,
        "token_total": token_in + token_out,
        "latency_ms": round(latency_ms, 1),
        "cost": round(cost, 6),
        "model": model,
        "tools_used": tools_used,
        "errors": errors,
    }
    _turns.append(entry)


@router.get("/api/metrics/turns")
async def get_turns(limit: int = 50):
    """Return recent conversation turns."""
    return {"turns": list(reversed(list(_turns)[-limit:]))}


@router.get("/api/metrics/tool-stats")
@deprecated()
async def get_tool_stats(tool: Optional[str] = None):
    """Return tool analytics aggregated stats."""
    client = get_shared().get("mcp")
    if client is not None and hasattr(client, "analytics"):
        return client.analytics.get_stats(tool_name=tool)
    return {"error": "analytics not available"}


@router.get("/api/metrics/tool-history")
async def get_tool_history(limit: int = 50):
    """Return recent tool call history."""
    client = get_shared().get("mcp")
    if client is not None and hasattr(client, "analytics"):
        return {"history": client.analytics.get_history(limit=limit)}
    return {"history": []}


@router.get("/api/metrics/summary")
async def get_summary():
    """Return aggregate summary of all metrics."""
    client = get_shared().get("mcp")

    tool_stats = {}
    if client is not None and hasattr(client, "analytics"):
        tool_stats = client.analytics.get_stats()

    total_cost = sum(t.get("cost", 0) for t in _turns)
    total_tokens = sum(t.get("token_total", 0) for t in _turns)
    avg_latency = (
        sum(t.get("latency_ms", 0) for t in _turns) / len(_turns)
        if _turns
        else 0
    )

    return {
        "total_turns": len(_turns),
        "total_cost": round(total_cost, 6),
        "total_tokens": total_tokens,
        "avg_latency_ms": round(avg_latency, 1),
        "tool_calls": tool_stats.get("total_calls", 0),
        "tool_failures": tool_stats.get("total_failures", 0),
    }

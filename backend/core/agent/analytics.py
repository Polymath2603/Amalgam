"""Tool analytics — track tool usage, error rates, latency.

Stores aggregated metrics in memory and optionally persists to disk.
"""

import json
import time
import logging
import threading
from pathlib import Path
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


class ToolAnalytics:
    """Thread-safe analytics collector for tool calls."""

    def __init__(self, persist_path: Optional[Path] = None):
        self._lock = threading.Lock()
        self._persist_path = persist_path
        self._tools: dict[str, dict] = {}
        self._history: list[dict] = []
        self._max_history = 500
        self._load()

    def record_call(self, tool_name: str, tool_args: dict,
                    latency_ms: float, success: bool,
                    error: Optional[str] = None):
        """Record one tool invocation."""
        with self._lock:
            info = self._tools.setdefault(tool_name, {
                "name": tool_name,
                "calls": 0,
                "successes": 0,
                "failures": 0,
                "total_latency_ms": 0.0,
                "min_latency_ms": float("inf"),
                "max_latency_ms": 0.0,
                "last_error": None,
                "last_called": 0,
            })
            info["calls"] += 1
            if success:
                info["successes"] += 1
            else:
                info["failures"] += 1
                if error:
                    info["last_error"] = error[:200]
            info["total_latency_ms"] += latency_ms
            info["min_latency_ms"] = min(info["min_latency_ms"], latency_ms)
            info["max_latency_ms"] = max(info["max_latency_ms"], latency_ms)
            info["last_called"] = time.time()

            entry = {
                "tool": tool_name,
                "latency_ms": latency_ms,
                "success": success,
                "error": error,
                "timestamp": time.time(),
            }
            self._history.append(entry)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def get_stats(self, tool_name: Optional[str] = None) -> dict:
        """Get aggregated stats for a tool or all tools."""
        with self._lock:
            if tool_name:
                info = self._tools.get(tool_name)
                if not info:
                    return {"error": f"No stats for tool: {tool_name}"}
                return self._format_tool(info)

            return {
                "tools": {
                    name: self._format_tool(info)
                    for name, info in sorted(self._tools.items())
                },
                "total_tools": len(self._tools),
                "total_calls": sum(t["calls"] for t in self._tools.values()),
                "total_failures": sum(t["failures"] for t in self._tools.values()),
            }

    def get_history(self, limit: int = 50) -> list[dict]:
        """Get recent tool call history."""
        with self._lock:
            return list(self._history[-limit:])

    def _format_tool(self, info: dict) -> dict:
        calls = info["calls"] or 1
        return {
            "name": info["name"],
            "calls": info["calls"],
            "successes": info["successes"],
            "failures": info["failures"],
            "success_rate": round(info["successes"] / calls * 100, 1) if calls else 0,
            "avg_latency_ms": round(info["total_latency_ms"] / calls, 1) if calls else 0,
            "min_latency_ms": info["min_latency_ms"] if info["min_latency_ms"] != float("inf") else 0,
            "max_latency_ms": info["max_latency_ms"],
            "last_error": info["last_error"],
            "last_called": info["last_called"],
        }

    def reset(self):
        """Clear all analytics data."""
        with self._lock:
            self._tools.clear()
            self._history.clear()

    def _load(self):
        """Load persisted analytics from disk."""
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text())
            with self._lock:
                self._tools = data.get("tools", {})
                self._history = data.get("history", [])
        except Exception as e:
            logger.warning("Failed to load tool analytics: %s", e)

    def persist(self):
        """Save analytics to disk."""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {
                    "tools": self._tools,
                    "history": self._history[-self._max_history:],
                }
            self._persist_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning("Failed to persist tool analytics: %s", e)

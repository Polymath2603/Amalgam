"""
Orchestrator state — tracks active sub-agents and emits swarm updates.
Used by Task 17 (Swarm Graph UI) to provide real-time agent tree visualization.
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Literal

logger = logging.getLogger(__name__)

AgentStatus = Literal["running", "waiting", "done", "failed", "cancelled"]


@dataclass
class AgentRun:
    """Tracks a single agent run within the orchestrator."""
    agent_type: str
    status: AgentStatus = "running"
    depth: int = 1
    task_description: str = ""
    model: str = "unknown"
    parent_id: str | None = None


class OrchestratorState:
    """Tracks all active and recently completed sub-agents."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.active_agents: dict[str, AgentRun] = {}
        self.completed_agents: list[tuple[str, AgentRun]] = []
        # Maximum number of completed agents to keep in history
        self._max_history: int = 100
        # Lock for serializing swarm updates
        self._send_lock = asyncio.Lock()

    def register_agent(self, agent_id: str, run: AgentRun):
        self.active_agents[agent_id] = run

    def update_status(self, agent_id: str, status: AgentStatus):
        if agent_id not in self.active_agents:
            logger.warning(
                "update_status called for unknown agent_id %r (ignored)", agent_id,
            )
            return
        self.active_agents[agent_id].status = status

        # When an agent finishes, move it to completed history
        if status in ("done", "failed", "cancelled"):
            self._archive_agent(agent_id)

    def _archive_agent(self, agent_id: str):
        """Move a completed agent from active to completed history."""
        run = self.active_agents.pop(agent_id, None)
        if run is not None:
            self.completed_agents.append((agent_id, run))
            # Trim history — O(1) with deque but keep list for JSON serialization compatibility
            if len(self.completed_agents) > self._max_history:
                self.completed_agents = self.completed_agents[-self._max_history:]

    def remove_agent(self, agent_id: str):
        """Immediately remove an agent without archiving."""
        self.active_agents.pop(agent_id, None)

    def to_dict(self) -> dict:
        """Serialize state to a JSON-safe dict."""
        return {
            "active_agents": {
                aid: {
                    "agent_type": run.agent_type,
                    "status": run.status,
                    "depth": run.depth,
                    "task_description": run.task_description,
                    "model": run.model,
                    "parent_id": run.parent_id,
                }
                for aid, run in self.active_agents.items()
            },
            "completed_agents": [
                [aid, {
                    "agent_type": run.agent_type,
                    "status": run.status,
                    "depth": run.depth,
                    "task_description": run.task_description,
                    "model": run.model,
                    "parent_id": run.parent_id,
                }]
                for aid, run in self.completed_agents
            ],
        }

    @classmethod
    def from_dict(cls, data: dict, config: dict | None = None) -> "OrchestratorState":
        """Deserialize state from a dict."""
        state = cls(config=config)
        for aid, run_data in data.get("active_agents", {}).items():
            state.active_agents[aid] = AgentRun(
                agent_type=run_data.get("agent_type", "basic"),
                status=run_data.get("status", "running"),
                depth=run_data.get("depth", 1),
                task_description=run_data.get("task_description", ""),
                model=run_data.get("model", "unknown"),
                parent_id=run_data.get("parent_id"),
            )
        for aid, run_data in data.get("completed_agents", []):
            state.completed_agents.append((aid, AgentRun(
                agent_type=run_data.get("agent_type", "basic"),
                status=run_data.get("status", "done"),
                depth=run_data.get("depth", 1),
                task_description=run_data.get("task_description", ""),
                model=run_data.get("model", "unknown"),
                parent_id=run_data.get("parent_id"),
            )))
        return state

    async def emit_swarm_update(self, ws_send_fn: Callable[[dict], Coroutine[Any, Any, None]]):
        """Send the current agent tree to the frontend.

        Uses a lock to prevent interleaved JSON from concurrent calls.
        """
        async with self._send_lock:
            nodes: list[dict] = []
            edges: list[dict] = []

            nodes.append({
                "id": "orchestrator",
                "label": "Orchestrator",
                "status": "running",
                "depth": 0,
                "model": self.config.get("model", "unknown"),
            })

            for agent_id, run in self.active_agents.items():
                nodes.append({
                    "id": agent_id,
                    "label": run.agent_type,
                    "status": run.status,
                    "depth": run.depth,
                    "task": run.task_description,  # Full description -- let frontend truncate
                    "model": run.model,
                })
                parent_id = run.parent_id or "orchestrator"
                edges.append({"from": parent_id, "to": agent_id})

            await ws_send_fn({
                "type": "swarm_update",
                "data": {"nodes": nodes, "edges": edges},
            })

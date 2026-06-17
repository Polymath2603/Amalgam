"""
Orchestrator state — tracks active sub-agents and emits swarm updates.
Used by Task 17 (Swarm Graph UI) to provide real-time agent tree visualization.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


@dataclass
class AgentRun:
    """Tracks a single agent run within the orchestrator."""
    agent_type: str
    status: str  # running | waiting | done | failed
    depth: int
    task_description: str
    model: str
    parent_id: str | None = None


class OrchestratorState:
    """Tracks all active and recently completed sub-agents."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.active_agents: dict[str, AgentRun] = {}

    def register_agent(self, agent_id: str, run: AgentRun):
        self.active_agents[agent_id] = run

    def update_status(self, agent_id: str, status: str):
        if agent_id in self.active_agents:
            self.active_agents[agent_id].status = status

    def remove_agent(self, agent_id: str):
        self.active_agents.pop(agent_id, None)

    async def emit_swarm_update(self, ws_send_fn: Callable[[dict], Coroutine[Any, Any, None]]):
        """Send the current agent tree to the frontend."""
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
                "task": run.task_description[:40],
                "model": run.model,
            })
            parent_id = run.parent_id or "orchestrator"
            edges.append({"from": parent_id, "to": agent_id})

        await ws_send_fn({
            "type": "swarm_update",
            "data": {"nodes": nodes, "edges": edges},
        })

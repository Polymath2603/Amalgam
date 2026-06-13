"""Agent factory — instantiate agents by config key."""

import logging
from typing import Any, Optional

from backend.core.agent.interface import AgentInterface
from backend.core.agent.basic_agent import BasicAgent
from backend.core.agent.reflective_agent import ReflectiveAgent
from backend.core.agent.planning_agent import PlanningAgent

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type] = {
    "basic": BasicAgent,
    "reflective": ReflectiveAgent,
    "planning": PlanningAgent,
}


class AgentFactory:
    """Creates agent instances based on a config string."""

    @staticmethod
    def create(agent_type: str = "basic", **kwargs) -> AgentInterface:
        """Return an agent instance.

        Kwargs are forwarded to the constructor (llm_router, memory, etc.).
        """
        cls = _REGISTRY.get(agent_type)
        if cls is None:
            logger.warning("Unknown agent type %r, falling back to basic", agent_type)
            cls = BasicAgent
        return cls(**kwargs)

    @staticmethod
    def register(name: str, cls: type):
        """Register a custom agent class."""
        _REGISTRY[name] = cls

    @staticmethod
    def available() -> list[str]:
        return list(_REGISTRY.keys())

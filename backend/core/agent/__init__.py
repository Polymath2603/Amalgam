"""Agent interfaces and built-in agent implementations."""

from backend.core.agent.base import BaseAgent, AgentTrace, ToolCall
from backend.core.agent.interface import AgentInterface
from backend.core.agent.basic_agent import BasicAgent
from backend.core.agent.reflective_agent import ReflectiveAgent
from backend.core.agent.planning_agent import PlanningAgent
from backend.core.agent.factory import AgentFactory
from backend.core.agent.stream_processor import StreamProcessor
__all__ = [
    "Agent",
    "AgentInterface",
    "BaseAgent",
    "AgentTrace",
    "ToolCall",
    "BasicAgent",
    "ReflectiveAgent",
    "PlanningAgent",
    "AgentFactory",
    "StreamProcessor",
]


def __getattr__(name):
    """Lazy import for legacy monolithic Agent — avoids pulling in litellm/cohere/pydantic chain
    when only the new agent types are used."""
    if name == "Agent":
        from backend.core.agent.core import Agent  # noqa: PLC0415
        return Agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

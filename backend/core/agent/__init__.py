"""Agent interfaces and built-in agent implementations."""

from backend.core.agent.base import BaseAgent, AgentTrace, ToolCall
from backend.core.agent.interface import AgentInterface
from backend.core.agent.basic_agent import BasicAgent
from backend.core.agent.reflective_agent import ReflectiveAgent
from backend.core.agent.planning_agent import PlanningAgent
from backend.core.agent.factory import AgentFactory
from backend.core.agent.stream_processor import StreamProcessor
from backend.core.agent.core import Agent  # legacy monolithic Agent

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

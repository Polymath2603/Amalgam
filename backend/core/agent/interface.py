"""
Legacy AgentInterface — kept for backwards compatibility.

New code should import from backend.core.agent.base instead.
"""
from backend.core.agent.base import BaseAgent, AgentTrace, ToolCall  # noqa: F401

# Alias for old imports that reference AgentInterface
AgentInterface = BaseAgent

__all__ = ["AgentInterface", "BaseAgent", "AgentTrace", "ToolCall"]

"""
AgentFactory — returns the correct agent type based on config.
Swap agent type in settings without touching any other code.
"""
from .basic_agent import BasicAgent
from .planning_agent import PlanningAgent
from .reflective_agent import ReflectiveAgent
from .base import BaseAgent


class AgentFactory:
    @staticmethod
    def create(agent_type: str, llm, tools, memory, config, mcp_client=None) -> BaseAgent:
        """
        agent_type: "basic" | "planning" | "reflective" | "reflective_planning"
        reflective_planning = PlanningAgent wrapped in ReflectiveAgent (recommended default)

        mcp_client: optional MCPClient for agents that need MCP tool execution.
        """
        match agent_type:
            case "basic":
                return BasicAgent(llm, tools, memory, config, mcp_client=mcp_client)
            case "planning":
                return PlanningAgent(llm, tools, memory, config, mcp_client=mcp_client)
            case "reflective":
                basic = BasicAgent(llm, tools, memory, config, mcp_client=mcp_client)
                return ReflectiveAgent(basic, llm, tools, memory, config)
            case "reflective_planning":
                planning = PlanningAgent(llm, tools, memory, config, mcp_client=mcp_client)
                return ReflectiveAgent(planning, llm, tools, memory, config)
            case _:
                raise ValueError(f"Unknown agent type: {agent_type}")

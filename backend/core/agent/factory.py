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
    def create(
        agent_type: str,
        llm,
        tools,
        memory,
        config,
        mcp_client=None,
        strategy_selector=None,
    ) -> BaseAgent:
        """
        agent_type: "basic" | "planning" | "reflective" | "reflective_planning"
        reflective_planning = PlanningAgent wrapped in ReflectiveAgent (recommended default)

        mcp_client: optional MCPClient for agents that need MCP tool execution.
        strategy_selector: optional StrategySelector for meta-cognitive strategy selection.
        """
        match agent_type:
            case "basic":
                return BasicAgent(llm, tools, memory, config, mcp_client=mcp_client, strategy_selector=strategy_selector)
            case "planning":
                return PlanningAgent(llm, tools, memory, config, mcp_client=mcp_client, strategy_selector=strategy_selector)
            case "reflective":
                basic = BasicAgent(llm, tools, memory, config, mcp_client=mcp_client, strategy_selector=strategy_selector)
                return ReflectiveAgent(basic, llm, tools, memory, config,
                                       mcp_client=mcp_client, strategy_selector=strategy_selector)
            case "reflective_planning":
                planning = PlanningAgent(llm, tools, memory, config, mcp_client=mcp_client, strategy_selector=strategy_selector)
                return ReflectiveAgent(planning, llm, tools, memory, config,
                                       mcp_client=mcp_client, strategy_selector=strategy_selector)
            case _:
                raise ValueError(f"Unknown agent type: {agent_type}")

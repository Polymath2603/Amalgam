"""
BaseAgent — the shared interface for all agent types.

All agent implementations (BasicAgent, PlanningAgent, ReflectiveAgent)
inherit from this class and must implement the ``run`` async generator.

The run() method is an async generator that yields text chunks as they
are produced. This enables streaming to the WebSocket without buffering
the entire response.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Records one tool invocation during an agent run."""
    tool_name: str
    tool_input: dict
    tool_output: str
    success: bool = True
    error: Optional[str] = None


@dataclass
class AgentTrace:
    """
    Complete record of what happened during one agent turn.
    Used for: metrics collection, skill auto-creation, reflection.
    """
    session_id: str
    user_message: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model_used: str = ""
    latency_ms: float = 0.0
    skill_used: Optional[str] = None
    full_response: str = ""

    @property
    def is_complex(self) -> bool:
        """True if this turn involved enough tool calls to warrant skill creation."""
        return len(self.tool_calls) >= 5


class BaseAgent(ABC):
    """
    Abstract base class for all agent types.

    Subclasses must implement:
        run(user_message, context) -> AsyncGenerator[str, None]
    """

    def __init__(self, llm_client, tools: dict, memory, config: dict):
        """
        Parameters
        ----------
        llm_client : LLMRouter
            The LLM client used for generation.
        tools : dict
            Available tool functions keyed by name.
        memory : Memory
            Session memory for storing/retrieving conversation history.
        config : dict
            Agent configuration (temperature, max_tokens, etc.).
        """
        self.llm = llm_client
        self.tools = tools
        self.memory = memory
        self.config = config

    @abstractmethod
    async def run(
        self,
        user_message: str,
        context: dict,
    ) -> AsyncGenerator[str, None]:
        """
        Process a user message and yield response text chunks.

        Parameters
        ----------
        user_message : str
            The raw user input.
        context : dict
            Contains: session_id, history, memory_context, etc.

        Yields
        ------
        str
            Text chunks of the agent's response (streaming).
        """
        ...

    async def execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """
        Execute one tool by name.

        Can be overridden by subclasses that need custom tool execution
        (e.g. permission gates, rate limiting).

        Parameters
        ----------
        tool_name : str
            Name of the tool to call.
        tool_input : dict
            Arguments for the tool.

        Returns
        -------
        str
            Tool output (serialized).
        """
        tool_fn = self.tools.get(tool_name)
        if tool_fn is None:
            msg = f"Unknown tool: {tool_name}"
            logger.warning(msg)
            return msg

        try:
            if hasattr(tool_fn, "__call__"):
                result = tool_fn(**tool_input)
            else:
                result = await tool_fn(tool_input)
            return str(result)
        except Exception as e:
            logger.error(f"Tool '{tool_name}' failed: {e}")
            return f"Tool error: {str(e)}"

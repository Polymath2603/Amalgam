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

from backend.core.llm.cost_router import CostRouter

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
        self.llm = CostRouter(llm_client) if hasattr(llm_client, 'stream') else llm_client
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

    async def generate_idle_prompt(self) -> str:
        """Generate a brief, natural conversation starter.

        Used by the WebSocket handler for idle/ping prompts.
        Override in subclasses that have richer context (characters, etc.).
        """
        char_id = self.config.get("character.active", "default") if self.config else "default"
        name = "assistant"

        prompt = (
            f"You are {name}."
            " Generate a brief, natural conversation starter or idle observation."
            " Keep it under 20 words. Be in-character. Just the text, no quotes."
        )
        try:
            result = await self.llm.generate([{"role": "user", "content": prompt}], temperature=0.9)
            return (result or "").strip().strip('"').strip("'")
        except Exception as e:
            logger.warning(f"Idle prompt generation failed: {e}")
            return ""

    async def subconscious_reflect(self) -> str:
        """Reflect on recent conversation and store a summary.

        Used by the WebSocket handler for background reflection.
        Override in subclasses that need richer reflection logic.
        """
        recent = self.memory.get_recent(10)
        if not recent:
            return ""

        chat_log = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
        char_id = self.config.get("character.active", "default") if self.config else "default"
        name = "assistant"

        prompt = (
            f"You are {name}. Summarize the key facts and emotional undertones "
            f"from this recent conversation in one sentence. Focus on what you learned "
            f"about the user and how they feel.\n\nConversation:\n{chat_log}"
        )
        try:
            summary = await self.llm.generate([{"role": "user", "content": prompt}], temperature=0.5)
            if summary:
                await self.memory.add_turn("system", f"[reflection] {summary.strip()}")
            return summary.strip() if summary else ""
        except Exception as e:
            logger.warning(f"Subconscious reflection failed: {e}")
            return ""

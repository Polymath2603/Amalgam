"""
BaseAgent — the shared interface for all agent types.

All agents yield text chunks (for streaming) and produce an AgentTrace on completion.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    name: str
    input: dict
    output: str
    success: bool = True


@dataclass
class AgentTrace:
    session_id: str
    user_message: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    full_response: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def is_complex(self) -> bool:
        """True if this run had enough tool calls to generate a skill from."""
        return len(self.tool_calls) >= 5


class BaseAgent(ABC):
    def __init__(self, llm, tools: dict, memory, config: dict):
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.config = config

    @abstractmethod
    async def run(
        self, user_message: str, context: dict
    ) -> AsyncGenerator[str, None]:
        """Yield response chunks. Sets context['last_trace'] when done."""
        ...
        yield ""

    async def execute_tool(self, name: str, tool_input: dict) -> ToolCall:
        if name not in self.tools:
            return ToolCall(name, tool_input, f"Error: unknown tool '{name}'", False)
        try:
            result = await self.tools[name](**tool_input)
            return ToolCall(name, tool_input, str(result)[:4000], True)
        except Exception as e:
            logger.warning(f"Tool '{name}' raised: {e}")
            return ToolCall(name, tool_input, f"Tool error: {e}", False)

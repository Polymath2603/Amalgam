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
    def __init__(self, llm, tools: dict, memory, config: dict, mcp_client=None):
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.config = config
        self.mcp_client = mcp_client

    @abstractmethod
    async def run(
        self, user_message: str, context: dict
    ) -> AsyncGenerator[str, None]:
        """Yield response chunks. Sets context['last_trace'] when done."""
        ...
        yield ""

    async def spawn_subagent(self, prompt: str) -> str:
        """Spawn a sub-agent to handle a focused task.

        Override in subclasses to provide custom sub-agent behaviour.
        Returns the complete response as a string.
        """
        # Default: delegate to a fresh BasicAgent with same capabilities
        from backend.core.agent.basic_agent import BasicAgent
        sub = BasicAgent(self.llm, self.tools, self.memory, self.config, mcp_client=self.mcp_client)
        parts: list[str] = []
        async for chunk in sub.run(prompt, {"session_id": "subagent"}):
            parts.append(str(chunk))
        return "".join(parts)

    async def execute_tool(self, name: str, tool_input: dict) -> ToolCall:
        # First check local tools dict
        if name in self.tools:
            try:
                result = await self.tools[name](**tool_input)
                tc = ToolCall(name, tool_input, str(result)[:4000], True)
            except Exception as e:
                logger.warning(f"Tool '{name}' raised: {e}")
                tc = ToolCall(name, tool_input, f"Tool error: {e}", False)

        # Fall back to MCP client if available
        elif self.mcp_client is not None:
            try:
                result = await self.mcp_client.call_tool_structured(name, tool_input)
                if result.success:
                    tc = ToolCall(name, tool_input, result.content[:4000], True)
                else:
                    tc = ToolCall(name, tool_input, result.error or f"Error: unknown tool '{name}'", False)
            except Exception as e:
                logger.warning(f"MCP tool '{name}' failed: {e}")
                tc = ToolCall(name, tool_input, f"Tool error: {e}", False)
        else:
            tc = ToolCall(name, tool_input, f"Error: unknown tool '{name}'", False)

        # Allow plugins to transform tool results
        try:
            from backend.core.plugin import get_registry
            registry = get_registry()
            tc.output = await registry.hook_tool_result(name, tool_input, tc.output)
        except Exception:
            pass

        return tc

    async def handle_user_input(self, text: str, images: list = None,
                                relationship_context: str = "") -> 'AsyncGenerator[str | tuple[str, str], None]':
        """Legacy streaming interface — delegates to run() for backward compatibility.
        
        Yields text chunks from run() plus standard signal tuples
        (__thinking__, __tool__, __error__) that the WebSocket handler expects.
        """
        from typing import AsyncIterator as _AsyncIterator
        ctx = {
            "session_id": getattr(self.memory, 'get_current_session', lambda: '')() if hasattr(self.memory, 'get_current_session') else '',
            "relationship_context": relationship_context,
            "images": images or [],
        }
        async for chunk in self.run(text, ctx):
            yield chunk

"""
BaseAgent — the shared interface for all agent types.

All agents yield text chunks (for streaming) and produce an AgentTrace on completion.
The ``handle_user_input()`` method additionally yields ``(signal_type, value)`` tuples
that the WebSocket handler uses for typed frontend events (tool calls, errors, thinking, etc.).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional, Union
import logging

logger = logging.getLogger(__name__)

# A re-exported union alias for the signal-tuple protocol.
# The handler at backend/api/ws/handler.py expects these tuples.
SignalTuple = tuple[str, str]

# Type alias for LLM instances — primarily LLMRouter but supports mocks/proxies.
LLMType = Union['LLMRouter', Any]


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
    def __init__(self, llm: LLMType, tools: dict, memory: Any, config: dict,
                 mcp_client: Any = None, strategy_selector: Any = None):
        if not isinstance(tools, dict):
            logger.warning("tools must be a dict, got %s; coercing to {}", type(tools).__name__, {})
            tools = {}
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.config = config
        self.mcp_client = mcp_client
        self.strategy_selector = strategy_selector
        self.settings = config or {}

    @abstractmethod
    async def run(
        self, user_message: str, context: dict
    ) -> AsyncGenerator[str | SignalTuple, None]:
        """Yield response chunks and/or signal tuples. Sets context['last_trace'] when done.

        **Contract:**
        - Yields ``str`` chunks for streaming text, and/or ``(signal_type, value)``
          tuples (e.g. ``("__tool__", name)``, ``("__error__", message)``) for typed
          frontend events.
        - The ``context`` dict is mutated in-place: ``context['last_trace']``
          is set to the final :class:`AgentTrace` after the last chunk.
          Callers should **not** reuse the same ``context`` dict across
          multiple ``run()`` calls unless they expect stale traces.
        - Errors should be raised as exceptions, not yielded as text.
          The ``handle_user_input()`` wrapper converts exception text to
          ``("__error__", ...)`` tuples for the frontend.
        """
        yield ""  # keep the ABC method syntactically a generator

    async def handle_user_input(
        self, text: str, images: list = None,
        relationship_context: str = ""
    ) -> AsyncGenerator[str | SignalTuple, None]:
        """Legacy streaming interface — wraps ``run()`` with frontend signal tuples.

        This is the entry point called by the WebSocket handler.  It yields:

        * ``str`` chunks for normal response text
        * ``("__thinking__", text)`` before the LLM begins generating
        * ``("__tool__", name)`` for each tool invocation
        * ``("__error__", message)`` when the agent encounters an unrecoverable error

        Subclasses that override ``handle_user_input`` must preserve the same
        yield-type contract.
        """
        from typing import AsyncIterator as _AsyncIterator

        ctx = {
            "session_id": (
                getattr(self.memory, 'get_current_session', lambda: '')()
                if hasattr(self.memory, 'get_current_session')
                else ''
            ),
            "relationship_context": relationship_context,
            "images": images or [],
        }

        # Emit thinking signal before starting
        yield ("__thinking__", "Processing your request...")

        error_occurred = False
        try:
            async for chunk in self.run(text, ctx):
                if isinstance(chunk, tuple):
                    # Pass through any signal tuples the agent yields directly
                    yield chunk
                elif isinstance(chunk, str) and chunk.startswith("[Error:"):
                    # Convert [Error: …] strings to proper error signals
                    error_msg = chunk[len("[Error:"):].rstrip("]").strip()
                    yield ("__error__", error_msg)
                    error_occurred = True
                    return
                else:
                    yield chunk
        except Exception as e:
            logger.exception("Agent error in handle_user_input")
            yield ("__error__", str(e))
            error_occurred = True
            return

    async def spawn_subagent(self, prompt: str) -> str:
        """Spawn a sub-agent to handle a focused task.

        Override in subclasses to provide custom sub-agent behaviour.
        Returns the complete response as a string.
        """
        # Default: delegate to a fresh BasicAgent with its own Memory instance
        from backend.core.agent.basic_agent import BasicAgent
        from backend.core.memory import Memory

        sub_memory = Memory(llm_router=self.llm)
        sub = BasicAgent(
            self.llm, self.tools, sub_memory, self.config,
            mcp_client=self.mcp_client,
            strategy_selector=self.strategy_selector,
        )
        parts: list[str] = []
        async for chunk in sub.run(prompt, {"session_id": "subagent"}):
            if isinstance(chunk, str):
                parts.append(chunk)
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
        except Exception as e:
            logger.warning(f"Plugin hook_tool_result failed: {e}")

        return tc

    async def generate_idle_prompt(self) -> str:
        """Generate an idle/initiative prompt. Override in subclasses."""
        return ""

    async def subconscious_reflect(self) -> str:
        """Run subconscious reflection. Override in subclasses."""
        return ""

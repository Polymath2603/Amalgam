"""Basic stateless tool-calling agent."""

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from backend.core.agent.base import BaseAgent, AgentTrace, ToolCall

logger = logging.getLogger(__name__)


class BasicAgent(BaseAgent):
    """Simple agent with a tool-calling loop and no meta-cognition.

    Implements the BaseAgent contract with a ``run()`` async generator.
    Also retains ``handle_user_input()`` for legacy callers.
    """

    def __init__(self, llm_router, memory, mcp_client=None,
                 settings=None, tools=None):
        # Map positional args to BaseAgent's named interface
        super().__init__(
            llm_client=llm_router,
            tools=tools or {},
            memory=memory,
            config=settings or {},
        )
        self.llm = llm_router
        self.memory = memory
        self.mcp_client = mcp_client
        self.settings = settings
        self._tools = tools or []
        self._history: List[Dict] = []

    async def run(self, user_message: str, context: dict) -> AsyncIterator[str]:
        """Stream a response, yielding text chunks."""
        session_id = context.get("session_id", "unknown")
        relationship_context = context.get("relationship_context", "")
        await self.memory.add_turn("user", user_message)
        messages = self._build_messages(user_message, None, relationship_context)
        schema = await self._get_tool_schema()

        try:
            async for chunk in self.llm.stream(messages, tools=schema):
                yield chunk
        except Exception as e:
            logger.error(f"BasicAgent stream error: {e}")
            yield f"Error: {e}"

    async def handle_user_input(self, text: str, images: list = None,
                                relationship_context: str = "") -> AsyncIterator[Any]:
        """Legacy streaming interface — delegates to run()."""
        ctx = {"session_id": "", "relationship_context": relationship_context}
        async for chunk in self.run(text, ctx):
            yield chunk

    async def get_response(self, text: str) -> str:
        """Simple synchronous-style response (no streaming)."""
        messages = self._build_messages(text)
        schema = await self._get_tool_schema()
        try:
            return await self.llm.generate(messages, tools=schema)
        except Exception as e:
            logger.error(f"BasicAgent get_response error: {e}")
            return f"Error: {e}"

    def load_history(self, session_id: str):
        """Load prior turns from memory."""
        stored = self.memory.get_session_sync(session_id) if hasattr(
            self.memory, "get_session_sync") else []
        self._history = stored

    async def execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute an MCP tool by name."""
        if self.mcp_client:
            return await self.mcp_client.call_tool(tool_name, tool_input)
        return f"No MCP client available for tool: {tool_name}"

    # --- Internal helpers ---

    def _build_messages(self, text: str, images: list = None,
                        relationship_context: str = "") -> List[Dict]:
        system = self._build_system_prompt(relationship_context)
        messages = [{"role": "system", "content": system}]
        messages.extend(self._history)
        user_msg: Dict = {"role": "user", "content": text}
        if images:
            user_msg["images"] = images
        messages.append(user_msg)
        return messages

    def _build_system_prompt(self, relationship_context: str = "") -> str:
        parts = ["You are a helpful AI assistant."]
        if relationship_context:
            parts.append(f"\nRelationship context:\n{relationship_context}")
        return "\n".join(parts)

    async def _get_tool_schema(self) -> Optional[List[Dict]]:
        if self.mcp_client and self.mcp_client.has_servers():
            return self.mcp_client.get_tool_schema()
        return self._tools or None

"""Basic stateless tool-calling agent."""

import asyncio
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

    def __init__(self, llm, tools=None, memory=None, config=None):
        super().__init__(llm, tools or {}, memory, config or {})
        self.llm = llm
        self.memory = memory
        self.mcp_client = config.get('mcp_client') if isinstance(config, dict) else None
        self.settings = config or {}
        self._tools = list((tools or {}).values())
        self._history: List[Dict] = []

    def update_settings(self, settings):
        """Update settings when they change."""
        self.settings = settings
        self.config = settings if isinstance(settings, dict) else settings or {}
        if hasattr(self.llm, 'reload_settings'):
            self.llm.reload_settings()
        logger.debug("BasicAgent.update_settings called")

    async def run(self, user_message: str, context: dict) -> AsyncIterator[str]:
        """Stream a response with tool execution loop."""
        session_id = context.get("session_id", "unknown")
        relationship_context = context.get("relationship_context", "")
        await self.memory.add_turn("user", user_message)
        messages = self._build_messages(user_message, None, relationship_context)
        schema = await self._get_tool_schema()

        max_iterations = 5
        iterations = 0
        current_input = user_message

        while iterations < max_iterations:
            iterations += 1
            if iterations > 1:
                messages = self._build_messages(current_input, None, relationship_context)

            try:
                if schema:
                    collected_tool_calls = []
                    text_accumulated = ""
                    async for item in self.llm.stream_with_tools(messages, tools=schema):
                        if isinstance(item, str):
                            text_accumulated += item
                        elif isinstance(item, dict) and item.get("type") == "tool_use":
                            collected_tool_calls.append(item)

                    if text_accumulated.strip():
                        yield text_accumulated

                    if collected_tool_calls:
                        results = await asyncio.gather(*[
                            self.execute_tool(tc["name"], tc.get("arguments") or {})
                            for tc in collected_tool_calls
                        ])
                        combined = "\n".join(
                            f"--- {tc['name']} ---\n{r}"
                            for tc, r in zip(collected_tool_calls, results)
                        )
                        current_input = f"Tool results:\n{combined}"
                    else:
                        break
                else:
                    async for chunk in self.llm.stream(messages):
                        yield chunk
                    break
            except Exception as e:
                logger.error(f"BasicAgent iteration error: {e}")
                yield f"Error: {e}"
                break

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

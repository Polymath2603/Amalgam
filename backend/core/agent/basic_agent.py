"""Basic stateless tool-calling agent."""

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from backend.core.agent.base import BaseAgent, AgentTrace, ToolCall
from backend.core.plugin import get_registry

logger = logging.getLogger(__name__)


class BasicAgent(BaseAgent):
    """Simple agent with a tool-calling loop and no meta-cognition.

    Implements the BaseAgent contract with a ``run()`` async generator.
    Also retains ``handle_user_input()`` for legacy callers.
    """

    def __init__(self, llm, tools=None, memory=None, config=None, mcp_client=None):
        resolved_mcp = mcp_client or (config.get('mcp_client') if isinstance(config, dict) else None)
        super().__init__(llm, tools or {}, memory, config or {}, mcp_client=resolved_mcp)
        self.llm = llm
        self.memory = memory
        self.mcp_client = resolved_mcp
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
        self.load_history(session_id)
        relationship_context = context.get("relationship_context", "")
        await self.memory.add_turn("user", user_message)
        messages = await self._build_messages(user_message, None, relationship_context)
        # Allow plugins to modify messages before LLM
        try:
            registry = get_registry()
            messages = await registry.hook_messages(messages)
        except Exception:
            pass
        schema = await self._get_tool_schema()

        max_iterations = 5
        iterations = 0
        current_input = user_message

        # Build a trace so ReflectiveAgent can inspect tool usage
        model_name = ""
        if hasattr(self.llm, 'get_model_name'):
            model_name = self.llm.get_model_name()
        trace = AgentTrace(session_id=session_id, user_message=user_message, model=model_name)
        full_response = ""

        while iterations < max_iterations:
            iterations += 1
            if iterations > 1:
                messages = await self._build_messages(current_input, None, relationship_context)
                # Allow plugins to modify messages before each LLM call
                try:
                    registry = get_registry()
                    messages = await registry.hook_messages(messages)
                except Exception:
                    pass

            try:
                if schema:
                    collected_tool_calls = []
                    text_accumulated = ""
                    async for item in self.llm.stream_with_tools(messages, tools=schema):
                        if isinstance(item, str):
                            text_accumulated += item
                            full_response += item
                        elif isinstance(item, dict) and item.get("type") == "tool_use":
                            collected_tool_calls.append(item)

                    if text_accumulated.strip():
                        yield text_accumulated

                    if collected_tool_calls:
                        tool_results = await asyncio.gather(*[
                            self.execute_tool(tc["name"], tc.get("arguments") or {})
                            for tc in collected_tool_calls
                        ])
                        # Collect ToolCall objects into the trace
                        for tr in tool_results:
                            if isinstance(tr, ToolCall):
                                trace.tool_calls.append(tr)
                        combined = "\n".join(
                            f"--- {tc['name']} ---\n{tr.output if isinstance(tr, ToolCall) else tr}"
                            for tc, tr in zip(collected_tool_calls, tool_results)
                        )
                        current_input = f"Tool results:\n{combined}"
                    else:
                        break
                else:
                    async for chunk in self.llm.stream(messages):
                        yield chunk
                        full_response += chunk
                    break
            except Exception as e:
                logger.error(f"BasicAgent iteration error: {e}")
                yield f"Error: {e}"
                full_response += f"Error: {e}"
                break

        trace.full_response = full_response
        context["last_trace"] = trace

        # Save assistant response so future turns see it in load_history
        if full_response.strip():
            await self.memory.add_turn("assistant", full_response)

    async def handle_user_input(self, text: str, images: list = None,
                                relationship_context: str = "") -> AsyncIterator[Any]:
        """Legacy streaming interface — delegates to run()."""
        ctx = {
            "session_id": getattr(self.memory, 'get_current_session', lambda: '')() if hasattr(self.memory, 'get_current_session') else '',
            "relationship_context": relationship_context,
            "images": images or [],
        }
        async for chunk in self.run(text, ctx):
            yield chunk

    async def get_response(self, text: str) -> str:
        """Simple synchronous-style response (no streaming)."""
        messages = await self._build_messages(text)
        # Allow plugins to modify messages before response
        try:
            registry = get_registry()
            messages = await registry.hook_messages(messages)
        except Exception:
            pass
        schema = await self._get_tool_schema()
        try:
            return await self.llm.generate(messages, tools=schema)
        except Exception as e:
            logger.error(f"BasicAgent get_response error: {e}")
            return f"Error: {e}"

    def load_history(self, session_id: str):
        """Load prior turns from memory."""
        stored = []
        if hasattr(self.memory, "get_session_messages"):
            msgs = self.memory.get_session_messages(session_id)
            # Include only recent messages (last ~20) to avoid context overflow
            stored = [{"role": m["role"], "content": m["content"]} for m in msgs[-20:]]
        self._history = stored

    async def execute_tool(self, name: str, tool_input: dict) -> ToolCall:
        """Execute a tool, falling back to MCP client when not in local tools dict.

        This bridges the gap between the tool schema (which may include MCP tools)
        and the actual execution path — MCP tools are visible to the LLM but were
        never registered in self.tools.
        """
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
            registry = get_registry()
            tc.output = await registry.hook_tool_result(name, tool_input, tc.output)
        except Exception:
            pass

        return tc

    # --- Internal helpers ---

    async def _build_messages(self, text: str, images: list = None,
                              relationship_context: str = "") -> List[Dict]:
        system = await self._build_system_prompt(relationship_context)
        messages = [{"role": "system", "content": system}]
        messages.extend(self._history)
        user_msg: Dict = {"role": "user", "content": text}
        if images:
            user_msg["images"] = images
        messages.append(user_msg)
        return messages

    async def _build_system_prompt(self, relationship_context: str = "") -> str:
        parts = ["You are a helpful AI assistant."]
        if relationship_context:
            parts.append(f"\nRelationship context:\n{relationship_context}")
        prompt = "\n".join(parts)
        # Allow plugins to modify the system prompt
        try:
            registry = get_registry()
            prompt = await registry.hook_system_prompt(prompt)
        except Exception:
            pass
        return prompt

    async def _get_tool_schema(self) -> Optional[List[Dict]]:
        if self.mcp_client and self.mcp_client.has_servers():
            schema = self.mcp_client.get_tool_schema()
        else:
            schema = self._tools or None

        # Allow plugins to modify tool definitions
        if schema is not None:
            try:
                registry = get_registry()
                schema = await registry.hook_tool_definition(schema)
            except Exception:
                pass
        return schema

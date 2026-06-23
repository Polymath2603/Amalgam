"""Basic stateless tool-calling agent."""

import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from backend.core.agent.base import BaseAgent, AgentTrace, ToolCall, LLMType, SignalTuple
from backend.core.plugin import get_registry

logger = logging.getLogger(__name__)


class BasicAgent(BaseAgent):
    """Simple agent with a tool-calling loop and no meta-cognition.

    Implements the BaseAgent contract with a ``run()`` async generator.
    Also retains ``handle_user_input()`` for legacy callers.
    """

    def __init__(self, llm: LLMType, tools: Any = None, memory: Any = None,
                 config: Any = None, mcp_client: Any = None,
                 strategy_selector: Any = None):
        # Resolve mcp_client: prefer explicit, fallback to config for Settings objects
        resolved_mcp = mcp_client
        if resolved_mcp is None and config is not None:
            resolved_mcp = getattr(config, 'mcp_client', None) or (
                config.get('mcp_client') if isinstance(config, dict) else None
            )
        super().__init__(llm, tools or {}, memory, config or {},
                         mcp_client=resolved_mcp,
                         strategy_selector=strategy_selector)
        self.llm = llm
        self.memory = memory
        self.mcp_client = resolved_mcp
        self.strategy_selector = strategy_selector
        self._tools = list((tools or {}).values())
        self._history: List[Dict] = []

    def update_settings(self, settings):
        """Update settings when they change."""
        self.settings = settings
        self.config = settings if isinstance(settings, dict) else settings or {}
        if hasattr(self.llm, 'reload_settings'):
            self.llm.reload_settings()
        logger.debug("BasicAgent.update_settings called")

    async def run(self, user_message: str, context: dict) -> AsyncGenerator[str | SignalTuple, None]:
        """Stream a response with tool execution loop."""
        session_id = context.get("session_id", "unknown")
        await self.load_history(session_id)
        relationship_context = context.get("relationship_context", "")
        images = context.get("images", [])
        await self.memory.add_turn("user", user_message)
        messages = await self._build_messages(user_message, images or None, relationship_context)
        # Allow plugins to modify messages before LLM
        try:
            registry = get_registry()
            messages = await registry.hook_messages(messages)
        except Exception as e:
            logger.warning(f"Plugin hook_messages failed (pre-loop): {e}")
        schema = await self._get_tool_schema()

        # Intent classification & strategy selection
        intent = self._classify_intent(user_message)
        strategy = None
        if self.strategy_selector:
            strategy = self.strategy_selector.select(intent)
            logger.debug("Strategy for intent=%s: max_iterations=%s, temperature=%s, CoT=%s",
                         intent, strategy.max_iterations, strategy.temperature, strategy.use_chain_of_thought)
        max_iterations = min(strategy.max_iterations if strategy else 5, 25)
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
                except Exception as e:
                    logger.warning(f"Plugin hook_messages failed (iteration {iterations}): {e}")

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
                        # Emit tool signals so the WebSocket handler can show them
                        for tc_info in collected_tool_calls:
                            yield ("__tool__", f"Calling tool: {tc_info['name']}")

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
                yield f"[Error: {e}]"
                full_response += f"[Error: {e}]"
                break

        trace.full_response = full_response
        context["last_trace"] = trace

        # Save assistant response so future turns see it in load_history
        if full_response.strip():
            await self.memory.add_turn("assistant", full_response)

    async def handle_user_input(self, text: str, images: list = None,
                                relationship_context: str = "") -> AsyncGenerator[str | SignalTuple, None]:
        """Legacy streaming interface — delegates to run()."""
        ctx = {
            "session_id": self.memory.get_current_session(),
            "relationship_context": relationship_context,
            "images": images or [],
        }
        yield ("__thinking__", "Processing your request...")
        try:
            async for chunk in self.run(text, ctx):
                if isinstance(chunk, tuple):
                    yield chunk
                elif isinstance(chunk, str) and chunk.startswith("[Error:"):
                    error_msg = chunk[len("[Error:"):].rstrip("]").strip()
                    yield ("__error__", error_msg)
                    return
                else:
                    yield chunk
        except Exception as e:
            logger.exception("Agent error in BasicAgent.handle_user_input")
            yield ("__error__", str(e))
            return

    async def get_response(self, text: str) -> str:
        """Simple synchronous-style response (no streaming)."""
        messages = await self._build_messages(text)
        # Allow plugins to modify messages before response
        try:
            registry = get_registry()
            messages = await registry.hook_messages(messages)
        except Exception as e:
            logger.warning(f"Plugin hook_messages failed (get_response): {e}")
        schema = await self._get_tool_schema()
        try:
            return await self.llm.generate(messages, tools=schema)
        except Exception as e:
            logger.error(f"BasicAgent get_response error: {e}")
            return f"Error: {e}"

    async def load_history(self, session_id: str):
        """Load prior turns from memory into ``self._history``."""
        stored = []
        msgs = self.memory.get_session_messages(session_id)
        stored = [{"role": m["role"], "content": m["content"]} for m in msgs[-20:]]
        self._history = stored

    async def generate_idle_prompt(self) -> str:
        """Generate an idle/initiative prompt using the LLM."""
        system = await self._build_system_prompt()
        prompt = (
            "Generate a brief, natural conversation starter or idle observation. "
            "Keep it under 20 words. Just the text, no quotes."
        )
        try:
            result = await self.llm.generate(
                [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                temperature=0.9,
            )
            return (result or "").strip().strip('"').strip("'")
        except Exception as e:
            logger.warning(f"Idle prompt generation failed: {e}")
            return ""

    async def subconscious_reflect(self) -> str:
        """Run subconscious reflection on recent conversation history.

        Loads recent turns from memory if ``_history`` is empty (e.g. when
        called outside of ``run()``), so the method works in any context.
        """
        history = []
        if self._history:
            history = self._history
        elif self.memory is not None:
            try:
                recent = self.memory.get_recent(10)
                history = [{"role": m.get("role", ""), "content": m.get("content", "")}
                           for m in (recent or [])]
            except Exception:
                pass

        if not history:
            return ""
        recent = "\n".join(
            f"{m['role']}: {m['content'][:200]}" for m in history[-10:]
        )
        prompt = (
            "Summarize the key facts and emotional undertones from this recent conversation "
            "in one sentence. Focus on what you learned about the user and how they feel.\n\n"
            f"Conversation:\n{recent}"
        )
        try:
            summary = await self.llm.generate([{"role": "user", "content": prompt}], temperature=0.5)
            return (summary or "").strip()
        except Exception as e:
            logger.warning(f"Subconscious reflection failed: {e}")
            return ""

    # --- Internal helpers ---

    @staticmethod
    def _classify_intent(text: str) -> str:
        """Simple keyword-based intent classification for strategy selection."""
        text_lower = text.lower().strip()
        if any(text_lower.startswith(p) for p in (
            "what is", "what are", "who is", "when is",
            "where is", "how much", "tell me about",
            "define", "what does", "why"
        )):
            return "conversation"
        if any(kw in text_lower for kw in (
            "remember", "do you remember", "recall", "what did i",
            "what was", "earlier", "previously", "before"
        )):
            return "memory_op"
        if any(kw in text_lower for kw in (
            "search vault", "find in vault", "vault search",
            "access vault", "open vault"
        )):
            return "vault_op"
        if any(kw in text_lower for kw in (
            "code", "function", "class ", "def ", "implement",
            "debug", "fix ", "bug", "refactor"
        )):
            return "code"
        if any(kw in text_lower for kw in (
            "reflect", "think about", "analyze", "evaluate", "consider"
        )):
            return "reflection"
        return "tool_execution"  # default for action-oriented requests

    async def _build_messages(self, text: str, images: list = None,
                              relationship_context: str = "") -> List[Dict]:
        system = await self._build_system_prompt(relationship_context)
        messages = [{"role": "system", "content": system}]
        messages.extend(self._history)

        # Build user message — handle images as content blocks if present
        if images:
            content_parts: list = []
            content_parts.append({"type": "text", "text": text})
            for img in images:
                if isinstance(img, str):
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": img}
                    })
                elif isinstance(img, dict):
                    # Already a content block
                    content_parts.append(img)
            user_msg = {"role": "user", "content": content_parts}
        else:
            user_msg = {"role": "user", "content": text}
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
        except Exception as e:
            logger.warning(f"Plugin hook_system_prompt failed: {e}")
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
            except Exception as e:
                logger.warning(f"Plugin hook_tool_definition failed: {e}")
        return schema

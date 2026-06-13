"""
ReflectiveAgent — runs after every N turns to improve itself.

After every REFLECTION_EVERY_N turns, it:
1. Reviews the recent conversation quality
2. Extracts what it learned about the user
3. Checks if a skill should be created from a complex task
4. Updates the user profile with any new information
"""

import json
import logging
from typing import Any, AsyncIterator

from backend.core.agent.base import BaseAgent, AgentTrace, ToolCall
from backend.core.agent.basic_agent import BasicAgent

logger = logging.getLogger(__name__)

REFLECTION_EVERY_N = 5


class ReflectiveAgent(BaseAgent):
    """
    Agent wrapper that runs light-weight reflection in the background.

    Every REFLECTION_EVERY_N turns, a brief reflection pass is triggered:
    - Extract user preferences / facts
    - Update the persistent UserProfile
    - Optionally create reusable skills for complex multi-tool tasks
    """

    def __init__(self, llm_router, memory, mcp_client=None,
                 settings=None, tools=None):
        super().__init__(
            llm_client=llm_router,
            tools=tools or {},
            memory=memory,
            config=settings or {},
        )
        self._inner = BasicAgent(llm_router, memory, mcp_client, settings, tools)
        self._turn_count = 0
        self._traces: list[AgentTrace] = []

    async def run(self, user_message: str, context: dict) -> AsyncIterator[str]:
        """Stream a response, then optionally reflect."""
        session_id = context.get("session_id", "unknown")
        trace = AgentTrace(session_id=session_id, user_message=user_message)
        collected: list[str] = []

        try:
            async for chunk in self._inner.run(user_message, context):
                collected.append(chunk)
                yield chunk
        except Exception as e:
            logger.error("ReflectiveAgent run error: %s", e)
            yield f"Error: {e}"
            return

        trace.full_response = "".join(collected)
        self._traces.append(trace)
        self._turn_count += 1

        # Reflect every N turns (fire-and-forget)
        if self._turn_count >= REFLECTION_EVERY_N:
            self._turn_count = 0
            try:
                await self._reflect(trace)
            except Exception as e:
                logger.debug(f"Reflection pass failed (non-fatal): {e}")

    async def handle_user_input(self, text: str, images: list = None,
                                relationship_context: str = "") -> AsyncIterator[Any]:
        """Legacy streaming interface — delegates to run()."""
        ctx = {"session_id": "", "relationship_context": relationship_context or ""}
        async for chunk in self.run(text, ctx):
            yield chunk

    async def get_response(self, text: str) -> str:
        """Delegate to inner agent."""
        return await self._inner.get_response(text)

    def load_history(self, session_id: str):
        self._inner.load_history(session_id)

    # --- Reflection ---

    async def _reflect(self, last_trace: AgentTrace):
        """
        Background reflection: analyse recent turns and update profile/skills.
        """
        recent = self._traces[-REFLECTION_EVERY_N:] if len(self._traces) >= REFLECTION_EVERY_N else self._traces

        # 1. Check if a skill should be created from a complex multi-tool turn
        complex_turns = [t for t in recent if t.is_complex]
        if complex_turns:
            logger.info(f"Found {len(complex_turns)} complex turn(s) — skill creation candidate")

        # 2. Feed last turn into UserProfile (if available)
        from backend.core.user_profile import _user_profile as profile
        user_msgs = [{"role": "user", "content": t.user_message} for t in recent if t.user_message]
        if user_msgs:
            await profile.update_from_session(
                user_msgs,
                llm_caller=lambda p: self.llm.generate([{"role": "user", "content": p}])
            )

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @property
    def traces(self) -> list[AgentTrace]:
        return list(self._traces)

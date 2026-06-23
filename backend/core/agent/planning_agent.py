"""
PlanningAgent — for compound tasks with multiple distinct steps.
Classifies the request first. If simple -> delegates to BasicAgent.
If compound -> decomposes into steps -> executes each with prior step context.
"""
import re
import json
import logging
from typing import Any, AsyncGenerator
from .base import BaseAgent, LLMType, SignalTuple
from .basic_agent import BasicAgent

logger = logging.getLogger(__name__)

COMPOUND_SIGNALS = {
    " and then ", " after that ", ", then ",
    " also ", "step 1", "multiple", "each of", "for each",
}
# Additional signals that indicate a compound task even in short queries
_COMPOUND_SHORT_SIGNALS = {
    " and then ",
    "after that ",
    ", then ",
    " then ",
    " followed by ",
}


class PlanningAgent(BaseAgent):

    def __init__(self, llm: LLMType, tools: Any = None, memory: Any = None,
                 config: Any = None, mcp_client: Any = None,
                 strategy_selector: Any = None):
        resolved_mcp = mcp_client
        if resolved_mcp is None and config is not None:
            resolved_mcp = getattr(config, 'mcp_client', None) or (
                config.get('mcp_client') if isinstance(config, dict) else None
            )
        super().__init__(llm, tools or {}, memory, config or {},
                         mcp_client=resolved_mcp,
                         strategy_selector=strategy_selector)
        self.settings = config or {}

    async def generate_idle_prompt(self) -> str:
        """Generate an idle/initiative prompt — delegate to BasicAgent."""
        agent = BasicAgent(
            self.llm, self.tools, self.memory, self.config,
            mcp_client=self.mcp_client, strategy_selector=self.strategy_selector
        )
        return await agent.generate_idle_prompt()

    async def subconscious_reflect(self) -> str:
        """Run subconscious reflection on recent conversation history.

        Delegates to a BasicAgent so the inner agent's reflection logic
        (including history loading from memory) is reused.
        """
        agent = BasicAgent(
            self.llm, self.tools, self.memory, self.config,
            mcp_client=self.mcp_client, strategy_selector=self.strategy_selector
        )
        # Pre-load history so the sub-agent has context even when called
        # outside of a run() loop.
        if hasattr(self.memory, 'get_recent'):
            try:
                recent = self.memory.get_recent(10)
                if hasattr(recent, '__await__'):
                    recent = await recent
                if recent:
                    agent._history = [
                        {"role": m.get("role", ""), "content": m.get("content", "")}
                        for m in recent
                    ]
            except Exception:
                pass
        return await agent.subconscious_reflect()

    def update_settings(self, settings):
        """Update settings when they change."""
        self.settings = settings
        self.config = settings if isinstance(settings, dict) else settings or {}
        if hasattr(self.llm, 'reload_settings'):
            self.llm.reload_settings()
        logger.debug("PlanningAgent.update_settings called")

    async def run(
        self, user_message: str, context: dict
    ) -> AsyncGenerator[str | SignalTuple, None]:

        # Fast path: if simple, skip decomposition entirely
        if not self._is_compound(user_message):
            async for chunk in BasicAgent(
                self.llm, self.tools, self.memory, self.config,
                mcp_client=self.mcp_client, strategy_selector=self.strategy_selector
            ).run(user_message, context):
                yield chunk
            return

        # Decompose into steps (one LLM call, cheap model)
        yield "Let me break this down...\n\n"
        steps = await self._decompose(user_message, context)
        if not steps:
            # Decomposition failed — fall back to basic
            async for chunk in BasicAgent(
                self.llm, self.tools, self.memory, self.config,
                mcp_client=self.mcp_client, strategy_selector=self.strategy_selector
            ).run(user_message, context):
                yield chunk
            return

        yield f"**{len(steps)} steps:**\n"
        for i, s in enumerate(steps, 1):
            yield f"{i}. {s['title']}\n"
        yield "\n---\n\n"

        # Execute each step, carry results forward
        prior = []
        for i, step in enumerate(steps, 1):
            yield f"**Step {i}: {step['title']}**\n"
            instruction = step["instruction"]

            # Inject original user context so sub-steps see the full picture
            original_user_msg = context.get("original_message", user_message)
            original_images = context.get("images", [])
            original_relationship = context.get("relationship_context", "")

            ctx_parts = [f"Original user request: {original_user_msg}"]
            if original_relationship:
                ctx_parts.append(f"Relationship context: {original_relationship}")
            if original_images:
                ctx_parts.append(f"The user provided {len(original_images)} image(s) with their request.")
            instruction = f"{instruction}\n\n[Context: {' | '.join(ctx_parts)}]"

            if prior:
                prior_text = "\n".join(
                    f"Step {r['step']} found: {r['result'][:300]}" for r in prior
                )
                instruction += f"\n[Prior step results:\n{prior_text}]"

            step_result = []
            async for chunk in BasicAgent(
                self.llm, self.tools, self.memory, self.config,
                mcp_client=self.mcp_client, strategy_selector=self.strategy_selector
            ).run(instruction, {**context, "is_substep": True}):
                yield chunk
                step_result.append(chunk)

            prior.append({
                "step": i, "title": step["title"],
                "result": "".join(step_result),
            })
            yield "\n\n"

        # Synthesize
        yield "---\n\n**Summary:**\n"
        synthesis_prompt = (
            f"Original request: {user_message}\n\n"
            + "\n".join(
                f"Step {r['step']} ({r['title']}): {r['result']}"
                for r in prior
            )
            + "\n\nWrite a brief final answer that integrates the above."
        )
        async for chunk in BasicAgent(
            self.llm, self.tools, self.memory, self.config,
            mcp_client=self.mcp_client, strategy_selector=self.strategy_selector
        ).run(synthesis_prompt, {**context, "is_synthesis": True}):
            yield chunk

    def _is_compound(self, msg: str) -> bool:
        """Heuristic: detect compound tasks that benefit from decomposition.

        A query is considered compound if it contains sequencing signals
        (e.g. "and then", "after that") AND has more than a few words.
        Short queries with strong sequencing signals (e.g. "Find X and then
        summarise") are also flagged as compound.
        """
        low = msg.lower()
        words = msg.split()
        word_count = len(words)

        # Long queries with any signal → compound
        if word_count > 8 and any(s in low for s in COMPOUND_SIGNALS):
            return True

        # Short queries with strong sequencing signals → compound
        if any(s in low for s in _COMPOUND_SHORT_SIGNALS):
            return True

        return False

    async def _decompose(self, msg: str, context: dict) -> list[dict]:
        prompt = (
            f"Break this into ordered steps (max 5). "
            f"Respond ONLY with a JSON array. Each item: "
            f'{{"title": "short title", "instruction": "full instruction"}}. '
            f"Task: {msg}"
        )
        try:
            resp = await self.llm.complete(prompt, max_tokens=600)
            resp = re.sub(r"```(?:json)?", "", resp).strip()
            resp_json = json.loads(resp)
            if not isinstance(resp_json, list):
                logger.warning("Decomposition expected JSON array, got %s — falling back",
                               type(resp_json).__name__)
                return []
            return [
                s for s in resp_json
                if isinstance(s, dict) and "title" in s and "instruction" in s
            ][:5]
        except Exception as e:
            logger.warning(f"Decomposition failed: {e}")
            return []

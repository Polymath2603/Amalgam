"""
PlanningAgent — for compound tasks with multiple distinct steps.
Classifies the request first. If simple -> delegates to BasicAgent.
If compound -> decomposes into steps -> executes each with prior step context.
"""
import re
import json
import logging
from typing import AsyncGenerator
from .base import BaseAgent
from .basic_agent import BasicAgent

logger = logging.getLogger(__name__)

COMPOUND_SIGNALS = [
    " and then ", " after that ", ", then ", " first ",
    " also ", "step 1", "multiple", "each of", "for each",
]


class PlanningAgent(BaseAgent):

    async def run(
        self, user_message: str, context: dict
    ) -> AsyncGenerator[str, None]:

        # Fast path: if simple, skip decomposition entirely
        if not self._is_compound(user_message):
            async for chunk in BasicAgent(
                self.llm, self.tools, self.memory, self.config
            ).run(user_message, context):
                yield chunk
            return

        # Decompose into steps (one LLM call, cheap model)
        yield "Let me break this down...\n\n"
        steps = await self._decompose(user_message, context)
        if not steps:
            # Decomposition failed — fall back to basic
            async for chunk in BasicAgent(
                self.llm, self.tools, self.memory, self.config
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
            if prior:
                prior_text = "\n".join(
                    f"Step {r['step']} found: {r['result'][:300]}" for r in prior
                )
                instruction += f"\n\n[Prior step results:\n{prior_text}]"

            step_result = []
            async for chunk in BasicAgent(
                self.llm, self.tools, self.memory, self.config
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
            self.llm, self.tools, self.memory, self.config
        ).run(synthesis_prompt, {**context, "is_synthesis": True}):
            yield chunk

    def _is_compound(self, msg: str) -> bool:
        low = msg.lower()
        if any(s in low for s in COMPOUND_SIGNALS) and len(msg.split()) > 15:
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
            steps = json.loads(resp)
            return [
                s for s in steps
                if isinstance(s, dict) and "title" in s and "instruction" in s
            ][:5]
        except Exception as e:
            logger.warning(f"Decomposition failed: {e}")
            return []

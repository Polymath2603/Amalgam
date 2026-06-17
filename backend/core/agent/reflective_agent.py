"""
ReflectiveAgent — wraps any agent and adds background learning.
Transparent: yields chunks exactly as the inner agent does.
After completion: if trace.is_complex -> tries to create a skill (background task).
Every 10 turns: reflects on conversation quality (background task).
"""
import asyncio
import re
import logging
from typing import AsyncGenerator
from .base import BaseAgent

logger = logging.getLogger(__name__)


class ReflectiveAgent(BaseAgent):
    REFLECT_EVERY = 10

    def __init__(self, inner: BaseAgent, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inner = inner
        self._turn_count = 0

    async def run(
        self, user_message: str, context: dict
    ) -> AsyncGenerator[str, None]:
        chunks = []
        async for chunk in self.inner.run(user_message, context):
            yield chunk
            chunks.append(chunk)

        self._turn_count += 1
        trace = context.get("last_trace")

        # Fire background tasks — never block the user response
        if trace and trace.is_complex:
            asyncio.create_task(self._try_create_skill(trace))

        if self._turn_count % self.REFLECT_EVERY == 0:
            asyncio.create_task(
                self._reflect(context.get("history", []))
            )

    async def _try_create_skill(self, trace):
        """
        Ask the LLM: 'Is what you just did a reusable pattern?'
        If yes, write a SKILL.md into data/skills/.
        Source: Hermes-Agent — skills grow from the agent's own experience.
        """
        trace_lines = "\n".join(
            f"- {tc.name}({list(tc.input.keys())}) -> "
            f"{'OK' if tc.success else 'FAIL'}: {tc.output[:80]}"
            for tc in trace.tool_calls
        )
        prompt = f"""Task you completed: {trace.user_message}

Tool calls made:
{trace_lines}

Is this a reusable pattern? If YES write a SKILL.md (exact format below).
If NO respond: NO_SKILL

---
name: [lowercase-hyphenated]
description: [one sentence]
version: 1.0.0
author: auto-generated
triggers:
  - "[trigger phrase]"
tools_required: [used tools]
---
## When to use
[1-2 sentences]
## Process
[numbered steps]
## Notes
[gotchas]"""

        try:
            resp = await self.llm.complete(prompt, max_tokens=600)
            if resp.strip() == "NO_SKILL":
                return

            name_m = re.search(r"^name:\s*(.+)$", resp, re.MULTILINE)
            if not name_m:
                return

            skill_name = name_m.group(1).strip()
            skill_path = f"data/skills/{skill_name}.md"

            # Scan for prompt injection before saving anything
            if _has_injection(resp):
                logger.warning(f"Auto-skill rejected (injection detected): {skill_name}")
                return

            with open(skill_path, "w") as f:
                f.write(resp)
            logger.info(f"Auto-created skill: {skill_name}")

        except Exception as e:
            logger.debug(f"Skill creation failed (non-fatal): {e}")

    async def _reflect(self, history: list):
        """Periodic quality check on conversation. Stores result in vault."""
        if len(history) < 4:
            return
        recent = "\n".join(
            f"{m['role'].upper()}: {m['content'][:200]}"
            for m in history[-10:]
        )
        prompt = (
            "Review this conversation briefly:\n\n" + recent +
            "\n\nIn 4 lines answer:\n"
            "PATTERNS: [what user frequently asks]\n"
            "QUALITY: [any suboptimal response, or 'good']\n"
            "SKILL: [what skill would help, or 'none']\n"
            "USER_PREF: [new preference revealed, or 'none']"
        )
        try:
            resp = await self.llm.complete(prompt, max_tokens=200)
            logger.info(f"[Reflection]\n{resp}")
        except Exception as e:
            logger.debug(f"Reflection failed (non-fatal): {e}")


def _has_injection(text: str) -> bool:
    """
    Scan skill text for prompt injection patterns before saving.
    Source: brain dump — 'why would I follow an instruction from a downloaded skill?'
    """
    patterns = [
        "ignore previous instructions",
        "disregard",
        "you are now",
        "forget everything",
        "jailbreak",
        "dan ",
    ]
    low = text.lower()
    return any(p in low for p in patterns)

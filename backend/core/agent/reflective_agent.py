"""
ReflectiveAgent — wraps any agent and adds background learning.
Transparent: yields chunks exactly as the inner agent does.
After completion: if trace.is_complex -> tries to create a skill (background task).
Every 10 turns: reflects on conversation quality (background task).
"""
import asyncio
import re
import logging
from typing import Any, AsyncGenerator
from .base import BaseAgent, LLMType, SignalTuple

logger = logging.getLogger(__name__)

# Safe characters for skill file names — strip everything else
_SAFE_NAME_RE = re.compile(r"[^a-z0-9_-]")
_INJECTION_PATTERNS = [
    "ignore previous instructions",
    "disregard",
    "you are now",
    "forget everything",
    "jailbreak",
]


def _has_injection(text: str) -> bool:
    """Scan text for prompt injection patterns before saving.

    Returns True if any known injection pattern is found.
    """
    low = text.lower()
    return any(p in low for p in _INJECTION_PATTERNS)


def _sanitise_skill_name(name: str) -> str:
    """Sanitise a skill name for safe filesystem use.

    - Lowercases the name
    - Strips all characters except ``[a-z0-9_-]``
    - Truncates to 64 characters
    - Falls back to ``"unnamed-skill"`` if the result is empty
    """
    safe = _SAFE_NAME_RE.sub("", name.lower())[:64]
    if not safe:
        safe = "unnamed-skill"
    return safe


class ReflectiveAgent(BaseAgent):
    REFLECT_EVERY = 10

    def __init__(self, inner: BaseAgent, llm: LLMType, tools: Any = None,
                 memory: Any = None, config: Any = None,
                 mcp_client: Any = None, strategy_selector: Any = None):
        super().__init__(llm, tools or {}, memory, config or {},
                         mcp_client=mcp_client,
                         strategy_selector=strategy_selector)
        self.inner = inner
        self._turn_count = 0
        self._bg_tasks: list[asyncio.Task] = []

    async def generate_idle_prompt(self) -> str:
        if hasattr(self.inner, 'generate_idle_prompt'):
            return await self.inner.generate_idle_prompt()
        return await super().generate_idle_prompt()

    async def subconscious_reflect(self) -> str:
        if hasattr(self.inner, 'subconscious_reflect'):
            return await self.inner.subconscious_reflect()
        return await super().subconscious_reflect()

    def update_settings(self, settings):
        if hasattr(self.inner, 'update_settings'):
            self.inner.update_settings(settings)

    async def run(
        self, user_message: str, context: dict
    ) -> AsyncGenerator[str | SignalTuple, None]:
        async for chunk in self.inner.run(user_message, context):
            yield chunk

        self._turn_count += 1
        trace = context.get("last_trace")

        # Fire background tasks — never block the user response
        if trace and trace.is_complex:
            task = asyncio.create_task(self._try_create_skill(trace))
            task.add_done_callback(
                lambda t: t.exception() and logger.error(
                    "Skill creation task failed: %s", t.exception()
                )
            )
            self._bg_tasks.append(task)

        if self._turn_count % self.REFLECT_EVERY == 0:
            task = asyncio.create_task(
                self._reflect(context.get("history", []))
            )
            task.add_done_callback(
                lambda t: t.exception() and logger.error(
                    "Reflection task failed: %s", t.exception()
                )
            )
            self._bg_tasks.append(task)

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

            raw_name = name_m.group(1).strip()
            safe_name = _sanitise_skill_name(raw_name)
            if safe_name != raw_name:
                logger.warning("Sanitised skill name '%s' → '%s'", raw_name, safe_name)

            # Scan for prompt injection before saving anything
            if _has_injection(resp):
                logger.warning("Auto-skill rejected (injection detected): %s", safe_name)
                return

            skill_path = f"data/skills/{safe_name}.md"
            with open(skill_path, "w") as f:
                f.write(resp)
            logger.info("Auto-created skill: %s", safe_name)

        except Exception as e:
            logger.warning(f"Skill creation failed (non-fatal): {e}")

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
            logger.info("[Reflection]\n%s", resp)
        except Exception as e:
            logger.warning(f"Reflection failed (non-fatal): {e}")

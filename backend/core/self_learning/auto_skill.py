"""
AutoSkillCreator — detect novel multi-tool solutions and persist them as SKILL.md.

When the agent successfully solves a problem using multiple tool calls, the
AutoSkillCreator extracts the pattern, generates a SKILL.md file with YAML
frontmatter, and saves it to the skills directory for future reuse.

Integration points:
- ReflectiveAgent._reflect() calls maybe_create_skill() on complex traces
- Skill MCP server picks up new skills automatically via _discover_skill_files()
"""

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Awaitable, Optional

from backend.core.paths import SKILLS_DIR

logger = logging.getLogger(__name__)

# Minimum tool calls to consider a turn complex enough for skill creation
MIN_TOOL_CALLS_FOR_SKILL = 3


class AutoSkillCreator:
    """Creates reusable skills from complex tool-using turns."""

    def __init__(self, llm_caller: Optional[Callable[[str], Awaitable[str]]] = None):
        """
        Parameters
        ----------
        llm_caller : async callable, optional
            An async function that takes a prompt string and returns a response.
            If None, skill creation uses template-based generation (no LLM).
        """
        self._llm_caller = llm_caller
        self._recently_created: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def maybe_create_skill(
        self,
        user_message: str,
        tool_calls: list,
        full_response: str,
        metrics_collector=None,
    ) -> Optional[str]:
        """Create a skill if the turn qualifies (multiple tool calls, not recently seen).

        Parameters
        ----------
        user_message : str
            The user's original message that triggered the tool sequence.
        tool_calls : list
            List of ToolCall dicts or objects with tool_name, tool_input, tool_output.
        full_response : str
            The agent's full response text.
        metrics_collector : optional
            MetricsCollector instance to record skill creation.

        Returns
        -------
        str or None
            The skill name if created, None otherwise.
        """
        if len(tool_calls) < MIN_TOOL_CALLS_FOR_SKILL:
            return None

        # Generate a skill name from the user message
        skill_name = self._generate_skill_name(user_message)
        if not skill_name:
            return None

        # Avoid creating skills with very similar names in rapid succession
        if skill_name in self._recently_created:
            logger.debug(f"Skill {skill_name!r} was recently created — skipping")
            return None

        skill_dir = SKILLS_DIR / skill_name
        if skill_dir.exists():
            logger.debug(f"Skill {skill_name!r} already exists — skipping")
            return None

        # Decide creation method
        if self._llm_caller:
            content = await self._generate_skill_llm(
                user_message, tool_calls, full_response
            )
        else:
            content = self._generate_skill_template(
                user_message, tool_calls, full_response
            )

        if not content:
            return None

        # Persist
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(content, encoding="utf-8")
        logger.info(f"Auto-created skill: {skill_name} at {skill_path}")

        self._recently_created.add(skill_name)

        # Record in metrics
        if metrics_collector:
            try:
                await metrics_collector.record_skill_created(skill_name)
            except Exception:
                pass

        return skill_name

    # ------------------------------------------------------------------
    # Skill name generation
    # ------------------------------------------------------------------

    def _generate_skill_name(self, user_message: str) -> Optional[str]:
        """Derive a short hyphenated name from the user's request."""
        text = user_message.strip().lower()
        # Remove punctuation, keep meaningful words
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        words = text.split()
        # Remove very common stopwords
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "to", "for",
                     "of", "in", "on", "at", "with", "by", "and", "or", "how",
                     "what", "why", "when", "where", "do", "does", "did", "can",
                     "could", "will", "would", "should", "i", "you", "we", "they",
                     "my", "your", "our", "me", "please", "help"}
        meaningful = [w for w in words if w not in stopwords and len(w) > 2]
        if not meaningful:
            return None
        # Take up to 4 words
        name_part = "-".join(meaningful[:4])
        # Ensure unique: append a short hash
        short_hash = uuid.uuid4().hex[:6]
        return f"{name_part}-{short_hash}"

    # ------------------------------------------------------------------
    # Content generation
    # ------------------------------------------------------------------

    async def _generate_skill_llm(
        self,
        user_message: str,
        tool_calls: list,
        full_response: str,
    ) -> Optional[str]:
        """Use the LLM to generate a well-structured SKILL.md."""
        tools_text = json.dumps(
            [self._tool_call_summary(tc) for tc in tool_calls],
            indent=2,
        )

        prompt = f"""You are a skill extraction system. Based on the following interaction, create a reusable SKILL.md file that captures the approach used.

The user asked: "{user_message}"

The agent used these tools:
{tools_text}

The agent's response was: "{full_response[:1000]}"

Create a SKILL.md with YAML frontmatter and clear sections that explain:
1. What problem this skill solves (description)
2. When to use it (triggers)
3. Step-by-step instructions
4. Which tool(s) to use and in what order
5. Example usage

Format:
---
name: <hyphenated-name>
description: "<one-line description>"
---

# <Title>

## Problem
...

## When to Use
...

## Steps
...

## Tools
...

## Example
...

Output ONLY the SKILL.md content. No explanation."""

        try:
            response = await self._llm_caller(prompt)
            response = response.strip()
            # Strip markdown fences if present
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            return response
        except Exception as e:
            logger.warning(f"LLM skill generation failed: {e}")
            return None

    def _generate_skill_template(
        self,
        user_message: str,
        tool_calls: list,
        full_response: str,
    ) -> str:
        """Generate a SKILL.md using a template (no LLM needed)."""
        name = self._generate_skill_name(user_message) or f"auto-skill-{uuid.uuid4().hex[:8]}"
        desc = user_message[:80].strip()
        tool_names = ", ".join(set(
            tc.tool_name if hasattr(tc, "tool_name") else tc.get("tool_name", "unknown")
            for tc in tool_calls
        ))
        steps = "\n".join(
            f"{i+1}. Use `{tc.tool_name if hasattr(tc, 'tool_name') else tc.get('tool_name', 'unknown')}`"
            for i, tc in enumerate(tool_calls)
        )

        return f"""---
name: "{name}"
description: "{desc}"
created: {datetime.now().isoformat()}
auto_generated: true
---

# {name.replace("-", " ").title()}

## Problem
{user_message}

## Tools Used
{tool_names}

## Steps
{steps}

## Example
**User:** {user_message[:200]}
**Agent:** Used multiple tools to fulfill the request.
"""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tool_call_summary(tc: Any) -> dict:
        """Normalize a ToolCall (object or dict) to a summary dict."""
        if hasattr(tc, "tool_name"):
            return {
                "tool": tc.tool_name,
                "input": tc.tool_input,
                "success": tc.success,
            }
        return {
            "tool": tc.get("tool_name", "unknown"),
            "input": tc.get("tool_input", {}),
            "success": tc.get("success", True),
        }

    @staticmethod
    def list_recent_skills() -> list[dict]:
        """List all auto-generated skills with metadata."""
        if not SKILLS_DIR.exists():
            return []
        results = []
        for entry in sorted(SKILLS_DIR.iterdir()):
            skill_path = entry / "SKILL.md"
            if skill_path.exists():
                content = skill_path.read_text(encoding="utf-8")
                results.append({
                    "name": entry.name,
                    "path": str(skill_path),
                    "auto_generated": "auto_generated: true" in content,
                    "size": len(content),
                })
        return results

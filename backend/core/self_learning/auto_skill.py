"""
AutoSkillCreator — detect novel multi-tool solutions and persist them as SKILL.md.

When the agent successfully solves a problem using multiple tool calls, the
AutoSkillCreator extracts the pattern, generates a SKILL.md file with YAML
frontmatter, and saves it to the skills directory for future reuse.

Integration points:
- ReflectiveAgent._reflect() calls maybe_create_skill() on complex traces
- Skill MCP server picks up new skills automatically via _discover_skill_files()
"""

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Optional, Protocol, runtime_checkable

import yaml

from backend.core.paths import SKILLS_DIR

logger = logging.getLogger(__name__)

# Minimum tool calls to consider a turn complex enough for skill creation
MIN_TOOL_CALLS_FOR_SKILL = 3

# Maximum number of words to use from the user message for a skill name
MAX_NAME_WORDS = 4

# Collision-safe hash length for deduplication (48 bits ≈ 281 trillion space)
NAME_HASH_LENGTH = 12

# Common stopwords — frozenset for O(1) membership checks
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "to", "for",
    "of", "in", "on", "at", "with", "by", "and", "or", "how",
    "what", "why", "when", "where", "do", "does", "did", "can",
    "could", "will", "would", "should", "i", "you", "we", "they",
    "my", "your", "our", "me", "please", "help",
})

# Max skill creations per session (rate limiter)
_MAX_SKILLS_PER_SESSION = 5


@runtime_checkable
class SkillGenerator(Protocol):
    """Protocol for LLM callables used to generate skill content.

    An async function that takes a prompt string and returns a response.
    """

    async def __call__(self, prompt: str) -> str:
        ...


class AutoSkillCreator:
    """Creates reusable skills from complex tool-using turns."""

    def __init__(self, llm_caller: Optional[SkillGenerator] = None):
        """
        Parameters
        ----------
        llm_caller : SkillGenerator, optional
            An async function that takes a prompt string and returns a response.
            If None, skill creation uses template-based generation (no LLM).
        """
        self._llm_caller = llm_caller
        self._recently_created: set[str] = set()
        self._session_skill_count = 0

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

        # Rate limit: don't flood skill directory
        if self._session_skill_count >= _MAX_SKILLS_PER_SESSION:
            logger.debug("Session skill limit reached — skipping")
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

        # Validate that the content has correct YAML frontmatter
        if not self._validate_skill_content(content):
            logger.warning(f"Generated content for {skill_name!r} failed validation — skipping")
            return None

        # Persist with error handling
        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text(content, encoding="utf-8")
        except OSError as e:
            logger.error(f"Failed to write skill {skill_name!r}: {e}")
            return None

        logger.info(f"Auto-created skill: {skill_name} at {skill_path}")

        self._recently_created.add(skill_name)
        self._session_skill_count += 1

        # Record in metrics
        if metrics_collector:
            try:
                await metrics_collector.record_skill_created(skill_name)
            except Exception as e:
                logger.exception(f"Failed to record skill creation metric: {e}")

        return skill_name

    # ------------------------------------------------------------------
    # Skill name generation
    # ------------------------------------------------------------------

    def _generate_skill_name(self, user_message: str) -> Optional[str]:
        """Derive a short hyphenated name from the user's request.

        Uses a content-based hash derived from the user message so that
        the same input always produces the same skill name (deterministic).
        """
        text = user_message.strip().lower()
        # Remove punctuation, keep meaningful words
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        words = text.split()
        meaningful = [w for w in words if w not in _STOPWORDS and len(w) > 2]
        if not meaningful:
            return None
        # Take up to MAX_NAME_WORDS words
        name_part = "-".join(meaningful[:MAX_NAME_WORDS])
        # Content-based hash for determinism
        short_hash = hashlib.sha256(user_message.encode()).hexdigest()[:NAME_HASH_LENGTH]
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
            return self._strip_markdown_fence(response)
        except Exception as e:
            logger.warning(f"LLM skill generation failed: {e}")
            return None

    @staticmethod
    def _strip_markdown_fence(text: str) -> str:
        """Robustly strip markdown code fences from LLM output."""
        text = text.strip()
        if not text.startswith("```"):
            return text
        # Remove the opening fence line
        newline_idx = text.index("\n") if "\n" in text else -1
        if newline_idx == -1:
            return ""
        body = text[newline_idx + 1:]
        # Remove trailing fence if present (handles extra whitespace/newlines)
        body = re.sub(r"```\s*$", "", body, flags=re.DOTALL)
        return body.strip()

    def _generate_skill_template(
        self,
        user_message: str,
        tool_calls: list,
        full_response: str,
    ) -> str:
        """Generate a SKILL.md using a template (no LLM needed)."""
        name = self._generate_skill_name(user_message) or f"auto-skill-{hashlib.sha256(user_message.encode()).hexdigest()[:8]}"
        desc = user_message[:80].strip()
        tool_names = ", ".join(set(
            self._get_tool_name(tc) for tc in tool_calls
        ))
        steps = "\n".join(
            f"{i+1}. Use `{self._get_tool_name(tc)}`"
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
    def _get_tool_name(tc: Any) -> str:
        """Safely extract tool_name from a ToolCall object or dict."""
        if isinstance(tc, dict):
            return tc.get("tool_name", "unknown")
        return getattr(tc, "tool_name", "unknown")

    @staticmethod
    def _tool_call_summary(tc: Any) -> dict:
        """Normalize a ToolCall (object or dict) to a summary dict.

        Uses _get_tool_name for the tool name to avoid duplicating
        the isinstance logic from _get_tool_name.
        """
        if isinstance(tc, dict):
            return {
                "tool": tc.get("tool_name", "unknown"),
                "input": tc.get("tool_input", {}),
                "success": tc.get("success", True),
            }
        return {
            "tool": getattr(tc, "tool_name", "unknown"),
            "input": getattr(tc, "tool_input", {}),
            "success": getattr(tc, "success", True),
        }

    @staticmethod
    def _validate_skill_content(content: str) -> bool:
        """Validate that the generated content has proper YAML frontmatter."""
        content = content.strip()
        if not content.startswith("---"):
            logger.debug("Skill content missing opening YAML frontmatter")
            return False

        # Find closing ---
        end_idx = content.find("---", 3)
        if end_idx == -1:
            logger.debug("Skill content missing closing YAML frontmatter")
            return False

        frontmatter = content[3:end_idx].strip()
        if not frontmatter:
            logger.debug("Skill content has empty YAML frontmatter")
            return False

        # Validate YAML parses
        try:
            data = yaml.safe_load(frontmatter)
        except yaml.YAMLError as e:
            logger.debug(f"Skill content has invalid YAML frontmatter: {e}")
            return False

        if not isinstance(data, dict):
            logger.debug("Skill content frontmatter is not a mapping")
            return False

        if "name" not in data:
            logger.debug("Skill content frontmatter missing 'name' field")
            return False

        return True

    @staticmethod
    def list_recent_skills() -> list[dict]:
        """List all auto-generated skills with metadata.

        Uses file metadata (mtime, size) instead of reading full contents,
        reducing I/O from O(content) to O(metadata).
        """
        if not SKILLS_DIR.exists():
            return []
        results = []
        for entry in sorted(SKILLS_DIR.iterdir()):
            skill_path = entry / "SKILL.md"
            if skill_path.exists():
                try:
                    stat = skill_path.stat()
                    # Quick check: read only the first ~2 KB to detect auto_generated
                    # This is still a partial read but much cheaper than reading full content
                    head = skill_path.read_bytes()[:2048]
                    auto_generated = b"auto_generated: true" in head
                    results.append({
                        "name": entry.name,
                        "path": str(skill_path),
                        "auto_generated": auto_generated,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    })
                except (OSError, PermissionError) as e:
                    logger.warning(f"Could not read skill {entry.name}: {e}")
                    continue
        return results

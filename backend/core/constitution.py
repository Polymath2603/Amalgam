# backend/core/constitution.py
"""
Loads CONSTITUTION.md and combines it with a character/agent's soul.
Constitution is always first. Character soul follows. Character can override.

Usage:
    from backend.core.constitution import build_system_prompt
    system = build_system_prompt(character_soul="You are Aria...", character_name="aria")
"""
from pathlib import Path
import logging

logger = logging.getLogger(__name__)
CONSTITUTION_PATH = Path("data/constitution.md")

# Module-level cache so we don't re-read the file every prompt
_cache: str | None = None


def load_constitution() -> str:
    """Load the global constitution. Returns empty string if file doesn't exist."""
    global _cache
    if _cache is not None:
        return _cache
    if CONSTITUTION_PATH.exists():
        _cache = CONSTITUTION_PATH.read_text(encoding="utf-8").strip()
        return _cache
    logger.warning("data/constitution.md not found — no global rules applied")
    return ""


def reload_constitution():
    """Invalidate cache so next load_constitution() re-reads the file."""
    global _cache
    _cache = None


def build_system_prompt(
    character_soul: str,
    character_name: str = "",
    skip_constitution: bool = False,
) -> str:
    """
    Combine CONSTITUTION.md with a character's own system prompt.
    Constitution comes first so its rules take precedence.
    The character soul follows — it defines personality, not safety rules.
    """
    if skip_constitution:
        return character_soul

    constitution = load_constitution()
    if not constitution:
        return character_soul

    parts = []
    if constitution:
        parts.append(f"[Global Rules]\n{constitution}")
    if character_soul:
        parts.append(f"[Character: {character_name or 'assistant'}]\n{character_soul}")

    return "\n\n".join(parts)

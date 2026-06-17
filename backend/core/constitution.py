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


def load_constitution() -> str:
    """Load the global constitution. Returns empty string if file doesn't exist."""
    if CONSTITUTION_PATH.exists():
        return CONSTITUTION_PATH.read_text(encoding="utf-8").strip()
    logger.warning("data/constitution.md not found — no global rules applied")
    return ""


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

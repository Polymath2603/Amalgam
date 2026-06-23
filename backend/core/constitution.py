"""
Loads CONSTITUTION.md and combines it with a character/agent's soul.
Constitution is always first. Character soul follows. Character can override.

Usage:
    from backend.core.constitution import build_system_prompt
    system = await build_system_prompt(character_soul="You are Aria...", character_name="aria")
"""
import asyncio
from pathlib import Path
import logging

from backend.core.paths import DATA_DIR

logger = logging.getLogger(__name__)
CONSTITUTION_PATH = DATA_DIR / "constitution.md"

# Cache for hot-reload support — reload_cache() sets this to None
_cache: str | None = None
_lock = asyncio.Lock()


async def load_constitution() -> str:
    """Load the global constitution asynchronously. Returns empty string if file doesn't exist."""
    global _cache, _lock
    if _cache is not None:
        return _cache
    async with _lock:
        # Double-check after acquiring lock
        if _cache is not None:
            return _cache
        if CONSTITUTION_PATH.exists():
            _cache = (await asyncio.to_thread(CONSTITUTION_PATH.read_text, encoding="utf-8")).strip()
            return _cache
        logger.warning("constitution.md not found — no global rules applied")
        _cache = ""
        return ""


def reload_cache():
    """Clear the cached constitution so it's re-read on next access.

    Called by HotReloader when constitution.md changes.
    """
    global _cache
    _cache = None


async def build_system_prompt(
    character_soul: str,
    character_name: str = "",
    skip_constitution: bool = False,
) -> str:
    """
    Combine CONSTITUTION.md with a character's own system prompt.
    Uses natural language framing instead of [Section] headers.
    """
    if skip_constitution:
        return character_soul

    constitution = await load_constitution()
    parts = []

    if constitution:
        parts.append(f"You are operating under these global rules:\n{constitution}")

    if character_soul:
        if constitution:
            parts.append(f"Your identity:\n{character_soul}")
        else:
            parts.append(character_soul)

    return "\n\n".join(parts)

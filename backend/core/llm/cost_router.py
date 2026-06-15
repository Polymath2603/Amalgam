"""
Cost router — classifies requests and routes to appropriate model tier.

Simple/trivial queries go to a cheaper fast model.
Complex queries (code, analysis, reasoning) use the full smart model.
Saves cost without sacrificing quality on hard tasks.
"""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

# Keywords that indicate a simple/trivial query
_SIMPLE_KEYWORDS = {
    "hello", "hi", "hey", "thanks", "thank you", "ok", "okay", "yes", "no",
    "goodbye", "bye", "morning", "afternoon", " evening", "night",
    "how are you", "what's up", "sup", "nice", "great", "cool",
}

# Short max length for simple classification (characters)
_SIMPLE_MAX_LENGTH = 80


def classify_task(messages: List[Dict]) -> str:
    """Classify the latest user message as 'fast' or 'smart'.

    Uses lightweight heuristics — no extra LLM call needed.
    Returns 'fast' for trivial queries, 'smart' for everything else.
    """
    if not messages:
        return "smart"

    # Get the last user message
    last = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                last = content.strip()
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        last = part["text"].strip()
                        break
            break

    if not last:
        return "smart"

    length = len(last)

    # Very short messages are likely simple
    if length < _SIMPLE_MAX_LENGTH:
        lower = last.lower().rstrip("?.!")
        if lower in _SIMPLE_KEYWORDS or any(lower.startswith(k) for k in _SIMPLE_KEYWORDS):
            return "fast"
        # Pure punctuation or very short fragments
        if length < 10:
            return "fast"

    # Longer messages default to smart
    return "smart"


class CostRouter:
    """Wraps an LLM provider and routes requests to the appropriate model tier.

    Usage:
        router = CostRouter(llm_router)
        async for token in router.stream(messages):
            yield token
    """

    def __init__(self, provider):
        self._provider = provider

    def __getattr__(self, name):
        # Delegate unknown attribute lookups to the underlying provider
        return getattr(self._provider, name)

    def _apply_tier(self, tier: str):
        """Set the model tier on the underlying provider."""
        if hasattr(self._provider, "_model_tier"):
            self._provider._model_tier = tier

    async def stream(self, messages, temperature=None):
        tier = classify_task(messages)
        logger.debug("CostRouter: classified as '%s'", tier)
        self._apply_tier(tier)
        async for token in self._provider.stream(messages, temperature):
            yield token

    async def stream_with_tools(self, messages, tools, temperature=None):
        tier = classify_task(messages)
        logger.debug("CostRouter: classified as '%s'", tier)
        self._apply_tier(tier)
        async for item in self._provider.stream_with_tools(messages, tools, temperature):
            yield item

    async def generate(self, messages, temperature=None):
        tier = classify_task(messages)
        logger.debug("CostRouter: classified as '%s'", tier)
        self._apply_tier(tier)
        return await self._provider.generate(messages, temperature)

"""
Cost router — classifies requests and routes to appropriate model tier.

Two layers:
1. `LLMCostRouter` / `route_llm_call()` — standalone router that picks the
   cheapest appropriate model for a task (use before calling the LLM).
2. `CostRouter` — wraps a provider and routes per-call within that provider
   (legacy compatibility, used by BasicAgent).

Simple/trivial queries go to a cheaper fast model.
Complex queries (code, analysis, reasoning) use the full smart model.
Saves cost without sacrificing quality on hard tasks.

Source: AgenticFlow's SONA routing system (~60% cost savings on mixed workloads).
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Standalone router (plan spec: LLMCostRouter + route_llm_call)
# ---------------------------------------------------------------------------

@dataclass
class ModelConfig:
    """Which provider + model to use for a task type."""
    provider: str     # "anthropic", "groq", "openai", "ollama"
    model: str        # exact model string as used by litellm
    max_tokens: int   # safe output cap for this task type


# Task type → cheapest appropriate model
ROUTING_TABLE: dict[str, ModelConfig] = {
    "simple_qa":      ModelConfig("groq",      "llama-3.1-8b-instant",  512),
    "classification": ModelConfig("groq",      "llama-3.1-8b-instant",  128),
    "summarization":  ModelConfig("groq",      "llama-3.1-70b-versatile", 1024),
    "translation":    ModelConfig("groq",      "llama-3.1-70b-versatile", 2048),
    "creative":       ModelConfig("anthropic", "claude-sonnet-4-6",      4096),
    "code":           ModelConfig("anthropic", "claude-sonnet-4-6",      4096),
    "analysis":       ModelConfig("anthropic", "claude-sonnet-4-6",      8192),
    "tool_use":       ModelConfig("anthropic", "claude-opus-4-6",        8192),
    "default":        ModelConfig("anthropic", "claude-sonnet-4-6",      4096),
}

# Keyword patterns per task type (checked in order — first match wins)
PATTERNS: list[tuple[str, list[str]]] = [
    ("tool_use",      [r"\b(search|find on web|browse|run|execute|write to|create file|screenshot)\b"]),
    ("code",          [r"\b(code|function|class|debug|bug|error|script|python|javascript|sql)\b", r"```"]),
    ("analysis",      [r"\b(analyze|explain why|compare|difference between|pros and cons|evaluate)\b"]),
    ("creative",      [r"\b(write a (story|poem|essay|blog|email|letter))\b", r"\b(creative|compose|draft)\b"]),
    ("translation",   [r"\b(translate|in (french|spanish|german|japanese|chinese|arabic))\b"]),
    ("summarization", [r"\b(summarize|tldr|tl;dr|key points|overview|condense)\b"]),
    ("classification",[r"\b(is it|does it|yes or no|categorize|classify)\b"]),
]


class LLMCostRouter:
    """
    Standalone router that picks the cheapest model for a task.

    Usage:
        router = LLMCostRouter()
        cfg = router.route(user_message, user_model_pref="auto")
        # cfg.provider, cfg.model, cfg.max_tokens
    """

    def route(
        self,
        message: str,
        user_model_pref: Optional[str] = None,
    ) -> ModelConfig:
        # Always respect explicit user choice
        if user_model_pref and user_model_pref not in ("auto", "", None):
            return ModelConfig("user", user_model_pref, 4096)

        task_type = self._classify(message)
        return ROUTING_TABLE.get(task_type, ROUTING_TABLE["default"])

    def _classify(self, message: str) -> str:
        msg = message.lower()
        for task_type, pats in PATTERNS:
            if any(re.search(p, msg) for p in pats):
                return task_type
        # Short messages with no special pattern → simple QA (cheapest)
        if len(message.split()) < 12:
            return "simple_qa"
        return "default"


# Module-level singleton
_router = LLMCostRouter()


def route_llm_call(message: str, user_pref: Optional[str] = None) -> ModelConfig:
    """Convenience: route a user message to the cheapest appropriate model."""
    return _router.route(message, user_pref)


# ---------------------------------------------------------------------------
# Legacy wrapper (plan's simple keywords + CostRouter class)
# ---------------------------------------------------------------------------

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

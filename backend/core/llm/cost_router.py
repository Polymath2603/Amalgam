"""
Routes LLM calls to a model appropriate for the task type.

Provides keyword-based task classification and model selection
without requiring a separate LLM call.
"""

import re
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelConfig:
    provider: str     # "anthropic", "groq", "openai", "ollama"
    model: str        # exact model string as used by litellm
    max_tokens: int   # safe output cap for this task type


# Task type -> default model configuration.
# These can be overridden by passing a custom table to LLMCostRouter.
DEFAULT_ROUTING_TABLE: dict[str, ModelConfig] = {
    "simple_qa":      ModelConfig("groq",      "llama-3.1-8b-instant",    512),
    "classification": ModelConfig("groq",      "llama-3.1-8b-instant",    128),
    "summarization":  ModelConfig("groq",      "llama-3.1-70b-versatile", 1024),
    "translation":    ModelConfig("groq",      "llama-3.1-70b-versatile", 2048),
    "creative":       ModelConfig("anthropic", "claude-sonnet-4-6",       4096),
    "code":           ModelConfig("anthropic", "claude-sonnet-4-6",       4096),
    "analysis":       ModelConfig("anthropic", "claude-sonnet-4-6",       8192),
    "tool_use":       ModelConfig("anthropic", "claude-opus-4-6",         8192),
    "default":        ModelConfig("anthropic", "claude-sonnet-4-6",       4096),
}

# Keyword patterns per task type (checked in order — first match wins)
DEFAULT_PATTERNS: list[tuple[str, list[str]]] = [
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
    Task-type based model router.

    Usage:
        router = LLMCostRouter()
        cfg = router.route(user_message, user_model_pref="auto")

    The routing table and patterns can be customised via constructor args.
    """

    def __init__(
        self,
        routing_table: Optional[dict[str, ModelConfig]] = None,
        patterns: Optional[list[tuple[str, list[str]]]] = None,
    ):
        self._routing_table = routing_table or DEFAULT_ROUTING_TABLE
        self._patterns = patterns or DEFAULT_PATTERNS

    def route(
        self,
        message: str,
        user_model_pref: Optional[str] = None,
    ) -> ModelConfig:
        if user_model_pref and user_model_pref not in ("auto", "", None):
            return ModelConfig("user", user_model_pref, 4096)

        task_type = self._classify(message)
        return self._routing_table.get(task_type, self._routing_table["default"])

    def _classify(self, message: str) -> str:
        msg = message.lower()
        for task_type, pats in self._patterns:
            if any(re.search(p, msg) for p in pats):
                return task_type
        if len(message.split()) < 12:
            return "simple_qa"
        return "default"


# Module-level singleton with thread safety
_router: Optional[LLMCostRouter] = None
_router_lock = threading.Lock()


def route_llm_call(message: str, user_pref: Optional[str] = None) -> ModelConfig:
    """Module-level convenience: route via the shared singleton."""
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = LLMCostRouter()
    return _router.route(message, user_pref)


def reset_router():
    """Reset singleton for test isolation."""
    global _router
    _router = None

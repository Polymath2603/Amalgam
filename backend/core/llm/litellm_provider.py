"""
LiteLLM-based provider — unified wrapper for all LLM backends.

Replaces per-provider classes (gemini, claude, ollama, openai_compat, etc.)
with a single class that delegates to litellm.acompletion().
"""

import asyncio
import functools
import json
import logging
import os
import random
import re
from typing import AsyncIterator, List, Dict, Any, Optional

import litellm
from litellm import acompletion as _litellm_acompletion, aembedding as _litellm_aembedding

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True


# ---------------------------------------------------------------------------
# Custom exceptions — callers can catch these instead of parsing error strings
# ---------------------------------------------------------------------------

class LLMProviderError(Exception):
    """Base exception for LLM provider failures."""


class RateLimitError(LLMProviderError):
    """Raised when the provider returns a rate-limit (429) response."""


class EmbeddingError(LLMProviderError):
    """Raised when embedding generation fails."""


# ---------------------------------------------------------------------------
# Provider constants
# ---------------------------------------------------------------------------

PROVIDER_PREFIX = {
    "gemini": "gemini",
    "openrouter": "openrouter",
    "groq": "groq",
    "deepseek": "deepseek",
    "mistral": "mistral",
    "together": "together_ai",
    "chatgpt": "openai",
    "azure-openai": "azure",
    "alibaba": "dashscope",
    "huggingface": "huggingface",
    "zai": "zai",
    "siliconflow": "openai",
    "claude": "anthropic",
    "ollama": "ollama",
    "llamacpp": "openai",
    "koboldai": "openai",
    "opencode": "openai",
    "aws": "bedrock",
    "gcp": "vertex_ai",
}

TOOL_CAPABLE = {
    "gemini", "openrouter", "groq", "deepseek", "mistral", "together",
    "chatgpt", "azure-openai", "alibaba", "huggingface", "zai", "siliconflow",
    "claude", "aws", "gcp",
}

CONTEXT_LIMITS = {
    "groq": 32768,
    "llamacpp": 4096,
    "koboldai": 4096,
}

OUTPUT_LIMITS = {
    "groq": 512,
    "llamacpp": 2048,
    "koboldai": 2048,
}

_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 5.0

EMBEDDING_CAPABLE = {
    "gemini", "ollama", "openai", "deepseek", "mistral",
    "together", "chatgpt", "azure-openai",
    "openrouter", "alibaba", "huggingface", "aws", "gcp",
}

EMBEDDING_MODEL_DEFAULTS = {
    "gemini": "gemini/text-embedding-004",
    "ollama": "nomic-embed-text",
    "openai": "openai/text-embedding-3-small",
    "chatgpt": "openai/text-embedding-3-small",
    "azure-openai": "azure/text-embedding-3-small",
    "deepseek": "openai/text-embedding-3-small",
    "mistral": "mistral/mistral-embed",
    "together": "together_ai/nomic-ai/nomic-embed-text-v1.5",
    "groq": "openai/text-embedding-3-small",
    "openrouter": "openai/text-embedding-3-small",
    "alibaba": "openai/text-embedding-3-small",
    "huggingface": "openai/text-embedding-3-small",
    "aws": "bedrock/amazon.titan-embed-text-v2:0",
    "gcp": "vertex_ai/textembedding-gecko",
}

# Providers that use an OpenAI-compatible API format
OPENAI_COMPAT_PROVIDERS = {
    "opencode", "llamacpp", "koboldai", "siliconflow",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a rate-limit (429) error."""
    exc_type = type(exc).__name__
    if "RateLimitError" in exc_type:
        return True
    msg = str(exc).lower()
    return "rate limit" in msg or "429" in msg or "rate_limit_exceeded" in msg


def _get_retry_delay(exc: Exception, attempt: int) -> float:
    """Extract retry delay from error message or use exponential backoff with jitter."""
    msg = str(exc)
    match = re.search(r"try again in ([\d.]+)s", msg)
    if match:
        return float(match.group(1)) + 0.5
    delay = _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
    # Add jitter (±25%) to avoid thundering herd
    jitter = random.uniform(0.75, 1.25)
    return delay * jitter


# ---------------------------------------------------------------------------
# Model-info cache (TTL: 5 minutes)
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=32)
def _get_cached_model_info(model_name: str) -> dict:
    """Cached wrapper around litellm.get_model_info()."""
    try:
        return litellm.get_model_info(model_name)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Main provider class
# ---------------------------------------------------------------------------

class LiteLLMProvider:
    """Unified LLM provider using LiteLLM."""

    def __init__(self, settings=None):
        self._settings = settings
        self._provider = "gemini"
        self._model_tier = "default"
        self._reload()

    def _reload(self):
        if self._settings:
            self._provider = self._settings.get("provider.active", "gemini")

    def reload_settings(self):
        if self._settings:
            self._settings.load()
        self._reload()

    def _get_model_config(self) -> tuple[str, dict]:
        """Build LiteLLM model string and kwargs from settings.

        Returns:
            (model_string, extra_kwargs) for litellm.acompletion()
        """
        provider = self._provider
        cfg: dict = {}
        if self._settings:
            cfg = self._settings.get(f"provider.{provider}", {})

        if not cfg:
            cfg = {}

        model_name = cfg.get("model", "")
        if self._model_tier == "fast" and cfg.get("model_fast"):
            model_name = cfg["model_fast"]

        prefix = PROVIDER_PREFIX.get(provider, provider)
        if provider in ("llamacpp", "koboldai", "siliconflow"):
            model = model_name
        elif provider == "ollama":
            model = f"ollama/{model_name}"
        else:
            model = f"{prefix}/{model_name}" if model_name else prefix

        kwargs: dict = {}
        api_key = cfg.get("api_key", "")
        base_url = cfg.get("base_url", "")

        if api_key:
            kwargs["api_key"] = api_key
            # Pass provider-specific API key kwargs that litellm expects
            if provider == "gemini":
                kwargs["gemini_api_key"] = api_key
            elif provider == "chatgpt":
                kwargs["openai_api_key"] = api_key

        if base_url:
            kwargs["api_base"] = base_url.rstrip("/")

        if provider == "aws":
            kwargs["aws_access_key_id"] = cfg.get("access_key", "")
            kwargs["aws_secret_access_key"] = cfg.get("secret_key", "")
            kwargs["aws_region_name"] = cfg.get("region", "us-east-1")
        elif provider == "gcp":
            sa_json = cfg.get("service_account_json", "")
            if sa_json:
                kwargs["vertex_credentials"] = sa_json
            kwargs["vertex_project"] = cfg.get("project_id", "")
            kwargs["vertex_location"] = cfg.get("region", "us-central1")

        return model, kwargs

    def _get_temperature(self, override: float = None) -> float:
        if override is not None:
            return float(override)
        if self._settings:
            return float(self._settings.get("llm.temperature", 0.7))
        return 0.7

    def supports_native_tools(self) -> bool:
        return self._provider in TOOL_CAPABLE

    def get_max_output_tokens(self) -> int:
        """Return max output tokens for the active model, with caching."""
        try:
            model_name = self.get_model_name()
            info = _get_cached_model_info(model_name)
            max_output = info.get("max_output_tokens")
            if max_output and max_output > 0:
                return max_output
        except Exception as exc:
            logger.debug("Failed to look up max_output_tokens: %s", exc)

        if self._provider in OUTPUT_LIMITS:
            return OUTPUT_LIMITS[self._provider]
        if self._settings:
            return int(self._settings.get("llm.max_tokens", 2048))
        return 2048

    def get_context_token_limit(self) -> int:
        """Return context token limit for the active model, with caching."""
        try:
            model_name = self.get_model_name()
            info = _get_cached_model_info(model_name)
            max_input = info.get("max_input_tokens")
            if max_input and max_input > 0:
                return max_input
        except Exception as exc:
            logger.debug("Failed to look up context_token_limit: %s", exc)

        if self._provider in CONTEXT_LIMITS:
            return CONTEXT_LIMITS[self._provider]
        if self._settings:
            return int(self._settings.get("llm.context_token_limit", 8192))
        return 8192

    def get_model_name(self) -> str:
        """Return the full model string (e.g. 'groq/llama-3.3-70b-versatile')."""
        model, _ = self._get_model_config()
        return model

    # ------------------------------------------------------------------
    # Retry helpers (reduces duplication across stream / generate)
    # ------------------------------------------------------------------

    async def _retry_stream(self, model: str, messages: list, **kwargs) -> AsyncIterator[str]:
        """Stream text completion with rate-limit retry logic.

        Raises:
            LLMProviderError: on non-retryable errors.
            RateLimitError: when all retries are exhausted.
        """
        for attempt in range(_RATE_LIMIT_MAX_RETRIES):
            try:
                response = await _litellm_acompletion(
                    model=model, messages=messages, stream=True, **kwargs
                )
                async for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield delta.content
                return
            except Exception as e:
                if _is_rate_limit_error(e) and attempt < _RATE_LIMIT_MAX_RETRIES - 1:
                    delay = _get_retry_delay(e, attempt)
                    logger.warning(
                        "Rate limited (%s), retrying in %.1fs (attempt %d/%d)",
                        self._provider, delay, attempt + 1, _RATE_LIMIT_MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("LiteLLM stream error (%s): %s", self._provider, e)
                if _is_rate_limit_error(e):
                    raise RateLimitError(str(e)) from e
                raise LLMProviderError(str(e)) from e

    async def _retry_generate(self, model: str, messages: list, **kwargs) -> str:
        """Non-streaming completion with rate-limit retry logic.

        Raises:
            LLMProviderError: on non-retryable errors.
            RateLimitError: when all retries are exhausted.
        """
        for attempt in range(_RATE_LIMIT_MAX_RETRIES):
            try:
                response = await _litellm_acompletion(
                    model=model, messages=messages, **kwargs
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                if _is_rate_limit_error(e) and attempt < _RATE_LIMIT_MAX_RETRIES - 1:
                    delay = _get_retry_delay(e, attempt)
                    logger.warning(
                        "Rate limited (%s), retrying in %.1fs (attempt %d/%d)",
                        self._provider, delay, attempt + 1, _RATE_LIMIT_MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("LiteLLM generate error (%s): %s", self._provider, e)
                if _is_rate_limit_error(e):
                    raise RateLimitError(str(e)) from e
                raise LLMProviderError(str(e)) from e

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def stream(self, messages: list, temperature: float = None) -> AsyncIterator[str]:
        """Stream text-only completion."""
        model, kwargs = self._get_model_config()
        temp = self._get_temperature(temperature)
        max_tokens = self.get_max_output_tokens()

        async for token in self._retry_stream(
            model, messages,
            temperature=temp, max_tokens=max_tokens, **kwargs,
        ):
            yield token

    async def stream_with_tools(
        self, messages: list, tools: List[Dict[str, Any]], temperature: float = None,
    ) -> AsyncIterator:
        """Stream completion with native tool calling.

        Yields str (text tokens) and dict (tool_use calls).

        Raises:
            LLMProviderError: on non-retryable errors.
            RateLimitError: when all retries are exhausted.
        """
        model, kwargs = self._get_model_config()
        temp = self._get_temperature(temperature)
        max_tokens = self.get_max_output_tokens()

        for attempt in range(_RATE_LIMIT_MAX_RETRIES):

            pending_tool_calls: Dict[int, dict] = {}

            try:
                response = await _litellm_acompletion(
                    model=model, messages=messages, stream=True,
                    tools=tools, tool_choice="auto",
                    temperature=temp, max_tokens=max_tokens, **kwargs,
                )
                async for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue

                    if delta.content:
                        yield delta.content

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index or 0
                            if idx not in pending_tool_calls:
                                pending_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                            pt = pending_tool_calls[idx]
                            if tc.id:
                                pt["id"] = tc.id
                            if tc.function and tc.function.name:
                                pt["name"] = tc.function.name
                            if tc.function and tc.function.arguments:
                                pt["arguments"] += tc.function.arguments

                    finish = chunk.choices[0].finish_reason if chunk.choices else None
                    if finish == "tool_calls" and pending_tool_calls:
                        for idx in sorted(pending_tool_calls.keys()):
                            pt = pending_tool_calls[idx]
                            if pt["id"] and pt["name"]:
                                try:
                                    args = json.loads(pt["arguments"]) if pt["arguments"] else {}
                                except json.JSONDecodeError:
                                    args = {}
                                yield {
                                    "type": "tool_use",
                                    "id": pt["id"],
                                    "name": pt["name"],
                                    "arguments": args,
                                }
                        pending_tool_calls.clear()

                if pending_tool_calls:
                    for idx in sorted(pending_tool_calls.keys()):
                        pt = pending_tool_calls[idx]
                        if pt["id"] and pt["name"]:
                            try:
                                args = json.loads(pt["arguments"]) if pt["arguments"] else {}
                            except json.JSONDecodeError:
                                args = {}
                            yield {
                                "type": "tool_use",
                                "id": pt["id"],
                                "name": pt["name"],
                                "arguments": args,
                            }
                    pending_tool_calls.clear()

                return

            except Exception as e:
                if _is_rate_limit_error(e) and attempt < _RATE_LIMIT_MAX_RETRIES - 1:
                    delay = _get_retry_delay(e, attempt)
                    logger.warning(
                        "Rate limited (%s), retrying in %.1fs (attempt %d/%d)",
                        self._provider, delay, attempt + 1, _RATE_LIMIT_MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("LiteLLM stream_with_tools error (%s): %s", self._provider, e)
                if _is_rate_limit_error(e):
                    raise RateLimitError(str(e)) from e
                raise LLMProviderError(str(e)) from e

    async def generate(self, messages: list, temperature: float = None) -> str:
        """Non-streaming completion.

        Raises:
            LLMProviderError: on non-retryable errors.
            RateLimitError: when all retries are exhausted.
        """
        model, kwargs = self._get_model_config()
        temp = self._get_temperature(temperature)
        max_tokens = self.get_max_output_tokens()

        return await self._retry_generate(
            model, messages,
            temperature=temp, max_tokens=max_tokens, **kwargs,
        )

    async def get_embedding(self, text: str) -> List[float]:
        """Generate embedding vector.

        Raises:
            EmbeddingError: if embedding fails or provider not supported.
        """
        if self._provider not in EMBEDDING_CAPABLE:
            raise EmbeddingError(
                f"Provider '{self._provider}' does not support embeddings"
            )

        model, kwargs = self._get_model_config()

        embed_model: Optional[str] = None
        if self._settings:
            embed_model = self._settings.get("memory.embedding_model", "")

        if not embed_model:
            if self._provider == "ollama":
                ollama_model = "nomic-embed-text"
                if self._settings:
                    ollama_model = self._settings.get("provider.ollama.model", ollama_model)
                    if "embed" not in ollama_model.lower():
                        ollama_model = "nomic-embed-text"
                embed_model = f"ollama/{ollama_model}"
            else:
                embed_model = EMBEDDING_MODEL_DEFAULTS.get(self._provider, "")

        if not embed_model:
            raise EmbeddingError(
                f"No embedding model configured for provider '{self._provider}'"
            )

        # If embedding model uses a different provider, inject the right API key
        embed_provider = embed_model.split("/", 1)[0] if "/" in embed_model else embed_model
        if embed_provider != self._provider and self._settings:
            # Try to fetch API key for the embedding provider from settings
            embed_provider_cfg = self._settings.get(f"provider.{embed_provider}", {})
            embed_api_key = embed_provider_cfg.get("api_key", "")
            if embed_api_key:
                kwargs["api_key"] = embed_api_key
                if embed_provider == "gemini":
                    kwargs["gemini_api_key"] = embed_api_key
                elif embed_provider in ("chatgpt", "openai"):
                    kwargs["openai_api_key"] = embed_api_key

        try:
            response = await _litellm_aembedding(model=embed_model, input=[text], **kwargs)
            return response.data[0].embedding
        except Exception as e:
            logger.error(
                "LiteLLM embedding error (%s, model=%s): %s",
                self._provider, embed_model, e,
            )
            raise EmbeddingError(str(e)) from e

    async def close(self):
        """No-op — LiteLLM manages its own HTTP clients."""
        pass

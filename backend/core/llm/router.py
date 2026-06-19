"""
LLM Router — thin facade over LiteLLMProvider.

Preserves the existing interface used by Agent and Memory while
delegating all inference to LiteLLM.
"""

import logging
from typing import AsyncIterator, List, Dict, Any

import litellm

from .litellm_provider import LiteLLMProvider, OPENAI_COMPAT_PROVIDERS

logger = logging.getLogger(__name__)


# Mapping of provider -> litellm attribute name for built-in model lists.
# Kept as a dict instead of hasattr/dir scanning for robustness.
LITELLM_MODEL_ATTRS: dict[str, str] = {
    "gemini": "gemini_models",
    "bedrock": "bedrock_models",
}


class LLMRouter:
    """Unified LLM router backed by LiteLLM."""

    # Providers that use an OpenAI-compatible API format
    OPENAI_COMPAT = OPENAI_COMPAT_PROVIDERS

    def __init__(self, settings=None):
        if settings is not None and not hasattr(settings, "get"):
            raise TypeError("settings must support .get() method")
        self.settings = settings
        self._provider = LiteLLMProvider(settings)

    def reload_settings(self):
        self._provider.reload_settings()

    def supports_native_tools(self) -> bool:
        return self._provider.supports_native_tools()

    def get_max_output_tokens(self) -> int:
        return self._provider.get_max_output_tokens()

    def get_context_token_limit(self) -> int:
        return self._provider.get_context_token_limit()

    def get_model_name(self) -> str:
        return self._provider.get_model_name()

    async def stream(self, messages: list, temperature: float = None) -> AsyncIterator[str]:
        async for token in self._provider.stream(messages, temperature):
            yield token

    async def stream_with_tools(
        self, messages: list, tools: List[Dict[str, Any]], temperature: float = None,
    ) -> AsyncIterator:
        if self.supports_native_tools():
            async for item in self._provider.stream_with_tools(messages, tools, temperature):
                yield item
        else:
            logger.warning(
                "Provider '%s' does not support native tools; falling back to plain text stream",
                self._provider._provider,
            )
            async for token in self._provider.stream(messages, temperature):
                yield token

    async def generate(self, messages: list, temperature: float = None) -> str:
        return await self._provider.generate(messages, temperature)

    async def complete(self, prompt: str, max_tokens: int = None, temperature: float = None) -> str:
        """Convenience: wrap a string prompt in messages and call generate().

        Used by PlanningAgent._decompose(), ReflectiveAgent._try_create_skill(), etc.
        """
        messages = [{"role": "user", "content": prompt}]
        return await self.generate(messages, temperature)

    async def get_embedding(self, text: str) -> List[float]:
        return await self._provider.get_embedding(text)

    async def fetch_ollama_models(self) -> List[str]:
        """Fetch models from a running Ollama server."""
        import httpx

        base_url = "http://localhost:11434"
        timeout = 10  # default
        if self.settings:
            base_url = self.settings.get("provider.ollama.base_url", base_url)
            timeout = self.settings.get("llm.ollama_timeout", timeout)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning("Failed to fetch Ollama models: %s", e)
        return []

    async def fetch_gemini_models(self) -> List[str]:
        attr = LITELLM_MODEL_ATTRS.get("gemini")
        if attr and hasattr(litellm, attr):
            return sorted(getattr(litellm, attr))
        return []

    async def fetch_openai_compat_models(self, provider: str) -> List[str]:
        attr = f"{provider}_models"
        if hasattr(litellm, attr):
            return sorted(getattr(litellm, attr))
        return []

    async def fetch_bedrock_models(self) -> List[str]:
        attr = LITELLM_MODEL_ATTRS.get("bedrock")
        if attr and hasattr(litellm, attr):
            return sorted(getattr(litellm, attr))
        return []

    async def fetch_vertex_models(self) -> List[str]:
        """List vertex_ai models known to litellm."""
        models: set = set()
        # Only scan known vertex-related prefixes instead of all dir(litellm)
        for suffix in ("vertex_ai_models", "vertex_models", "vertex_ai_bedrock_models"):
            if hasattr(litellm, suffix):
                models.update(getattr(litellm, suffix))
        return sorted(models)

    async def close(self):
        await self._provider.close()

"""
Provider profiles for the Amalgam CLI.

Offers:
- Auto-detection of configured providers from env vars
- Display helpers for /provider and /model commands
- Provider metadata (known providers, model lists)
"""
import os
from dataclasses import dataclass, field
from typing import Optional


# TODO dedup: KNOWN_PROVIDERS, PROVIDER_MODELS, and resolve_display_name
# duplicate data from backend/api/routes/setup.py::PROVIDER_CATALOG and
# webui/js/modules/settings-schema.js.  The /api/providers endpoint is
# the single source of truth.  When adding a new provider, update the
# PROVIDER_CATALOG dict in setup.py first, then keep the CLI lists in
# sync for offline/CLI-only use.
#
# ── Known providers and their models ───────────────────────────────────
KNOWN_PROVIDERS: list[str] = [
    "gemini", "openai", "anthropic", "groq", "ollama", "openrouter",
    "deepseek", "siliconflow", "zai", "mistral", "together",
    "huggingface", "llamacpp", "koboldai", "aws", "gcp",
    "opencode", "opendev",
]

PROVIDER_MODELS: dict[str, list[str]] = {
    "gemini": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini"],
    "anthropic": ["claude-sonnet-4-20250514", "claude-haiku-3-5"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "deepseek-r1-distill-llama-70b"],
    "ollama": [],
    "openrouter": ["meta-llama/llama-3.1-8b-instruct:free"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash-free"],
    "siliconflow": ["deepseek-ai/DeepSeek-R1", "deepseek-ai/DeepSeek-V3"],
    "zai": ["google/gemma-2-27b-it", "Qwen/QwQ-32B-Preview"],
    "mistral": ["mistral-small-latest", "mistral-large-latest"],
    "together": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
    "huggingface": [],
    "llamacpp": [],
    "koboldai": [],
    "aws": [],
    "gcp": [],
    "opencode": [],
    "opendev": [],
}


@dataclass
class ProviderInfo:
    """Describes a configured provider."""
    name: str
    display_name: str
    has_api_key: bool
    has_base_url: bool
    model: str = ""
    source: str = "config"  # config | env | default


def detect_providers(settings) -> list[ProviderInfo]:
    """Auto-detect which providers have API keys configured.

    Checks:
    1. settings.json (already env-merged by Settings.load)
    2. Environment variables directly
    3. Known defaults
    """
    providers: list[ProviderInfo] = []
    known_set = set(KNOWN_PROVIDERS)
    checked = set()

    # Check all known providers
    for name in KNOWN_PROVIDERS:
        cfg: dict | None = None
        try:
            cfg = settings.get(f"provider.{name}")
        except Exception:
            pass

        api_key = ""
        base_url = ""
        model = ""

        if cfg and isinstance(cfg, dict):
            api_key = (cfg.get("api_key") or "").strip()
            base_url = (cfg.get("base_url") or "").strip()
            model = (cfg.get("model") or "").strip()

        # Check env vars directly (fallback for providers not in settings)
        env_key = _provider_env_key(name)
        if not api_key and env_key in os.environ:
            api_key = os.environ[env_key].strip()

        # Special cases
        if not api_key and name == "gemini" and "GOOGLE_API_KEY" in os.environ:
            api_key = os.environ["GOOGLE_API_KEY"].strip()
        if not api_key and name == "openai" and "OPENAI_API_KEY" in os.environ:
            api_key = os.environ["OPENAI_API_KEY"].strip()
        if not api_key and name == "anthropic" and "ANTHROPIC_API_KEY" in os.environ:
            api_key = os.environ["ANTHROPIC_API_KEY"].strip()

        display = name
        source = "config"
        if api_key:
            source = "env" if env_key in os.environ or any(
                k in os.environ for k in _provider_alt_env_keys(name)
            ) else "config"
        elif not cfg:
            source = "default"

        providers.append(ProviderInfo(
            name=name,
            display_name=display,
            has_api_key=bool(api_key),
            has_base_url=bool(base_url),
            model=model,
            source=source,
        ))
        checked.add(name)

    return providers


def _provider_env_key(name: str) -> str:
    """Get the primary env var name for a provider's API key."""
    mapping = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "chatgpt": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "groq": "GROQ_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "together": "TOGETHER_API_KEY",
        "zai": "ZAI_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
        "huggingface": "HUGGINGFACE_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "azure-openai": "AZURE_OPENAI_API_KEY",
        "alibaba": "ALIBABA_API_KEY",
    }
    return mapping.get(name, f"{name.upper()}_API_KEY")


def _provider_alt_env_keys(name: str) -> list[str]:
    """Get alternative env var names for a provider."""
    alt = {
        "gemini": ["GOOGLE_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "chatgpt": ["OPENAI_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY"],
        "claude": ["ANTHROPIC_API_KEY"],
    }
    return alt.get(name, [])


def autocomplete_words(settings) -> list[str]:
    """Build the word list for prompt_toolkit autocomplete."""
    words = list(KNOWN_PROVIDERS)
    active_prov = "?"
    try:
        active_prov = settings.get("provider.active", "?")
    except Exception:
        pass
    words.extend(PROVIDER_MODELS.get(active_prov, []))
    for prov_models in PROVIDER_MODELS.values():
        words.extend(prov_models)
    return words


def resolve_display_name(provider_name: str) -> str:
    """Get a human-readable display name for a provider."""
    display_map = {
        "gemini": "Google Gemini",
        "openai": "OpenAI",
        "chatgpt": "ChatGPT (OpenAI)",
        "anthropic": "Anthropic",
        "claude": "Claude (Anthropic)",
        "groq": "Groq",
        "ollama": "Ollama (local)",
        "openrouter": "OpenRouter",
        "deepseek": "DeepSeek",
        "siliconflow": "SiliconFlow",
        "zai": "Z.AI",
        "mistral": "Mistral AI",
        "together": "Together AI",
        "huggingface": "HuggingFace",
        "llamacpp": "llama.cpp (local)",
        "koboldai": "KoboldAI (local)",
        "aws": "AWS Bedrock",
        "gcp": "GCP Vertex AI",
        "azure-openai": "Azure OpenAI",
        "alibaba": "Alibaba Cloud",
        "opencode": "OpenCode",
        "opendev": "OpenDev",
    }
    return display_map.get(provider_name, provider_name.title())

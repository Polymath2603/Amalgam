"""
Provider profiles for the Amalgam CLI.

Offers:
- Auto-detection of configured providers from env vars
- Display helpers for /provider and /model commands
- Provider metadata (known providers, model lists)

Canonical source for provider metadata:
  backend/api/routes/setup.py::PROVIDER_CATALOG

When adding a new provider, update the PROVIDER_CATALOG dict in setup.py first.
"""
import os
from dataclasses import dataclass, field
from typing import Optional

# ── Derive provider metadata from the canonical source ──────────────────
# Uses a lazy import with fallback so that CLI-only usage (without the full
# backend loaded) still works.  The /api/providers endpoint is the single
# source of truth; these lists are kept in sync automatically.
def _load_catalog():
    """Import PROVIDER_CATALOG from the backend, returning (id_list, model_dict, name_map)."""
    try:
        from backend.api.routes.setup import PROVIDER_CATALOG
        ids = [p["id"] for p in PROVIDER_CATALOG]
        models = {p["id"]: list(p.get("models") or []) for p in PROVIDER_CATALOG}
        name_map = {p["id"]: p["name"] for p in PROVIDER_CATALOG}
        return ids, models, name_map
    except ImportError:
        # Fallback: hardcoded data kept in sync with PROVIDER_CATALOG
        ids = [
            "alibaba", "anthropic", "anthropic-compat", "aws", "azure-openai", "chatgpt", "claude",
            "deepseek", "gcp", "gemini", "groq", "huggingface", "koboldai",
            "llamacpp", "mistral", "ollama", "openai", "openai-compat", "opencode", "opendev",
            "openrouter", "siliconflow", "together", "zai",
        ]
        models = {
            "anthropic": ["claude-haiku-3-5", "claude-sonnet-4-20250514"],
            "anthropic-compat": [],
            "aws": [],
            "azure-openai": [],
            "chatgpt": [],
            "claude": [],
            "deepseek": ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash-free"],
            "gcp": [],
            "gemini": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
            "groq": ["deepseek-r1-distill-llama-70b", "llama-3.1-8b-instant", "llama-3.3-70b-versatile"],
            "huggingface": [],
            "koboldai": [],
            "llamacpp": [],
            "mistral": ["mistral-large-latest", "mistral-small-latest"],
            "ollama": [],
            "openai": ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"],
            "openai-compat": [],
            "opencode": [],
            "opendev": [],
            "openrouter": ["meta-llama/llama-3.1-8b-instruct:free"],
            "siliconflow": ["deepseek-ai/DeepSeek-R1", "deepseek-ai/DeepSeek-V3"],
            "together": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
            "zai": ["Qwen/QwQ-32B-Preview", "google/gemma-2-27b-it"],
        }
        name_map = {
            "alibaba": "Alibaba Cloud",
            "anthropic": "Anthropic",
            "anthropic-compat": "Anthropic-Compatible",
            "aws": "AWS Bedrock",
            "azure-openai": "Azure OpenAI",
            "chatgpt": "ChatGPT (OpenAI)",
            "claude": "Claude (Anthropic)",
            "deepseek": "DeepSeek",
            "gcp": "GCP Vertex AI",
            "gemini": "Google Gemini",
            "groq": "Groq",
            "huggingface": "HuggingFace",
            "koboldai": "KoboldAI (local)",
            "llamacpp": "llama.cpp (local)",
            "mistral": "Mistral AI",
            "ollama": "Ollama (local)",
            "openai": "OpenAI",
            "openai-compat": "OpenAI-Compatible",
            "opencode": "OpenCode",
            "opendev": "OpenDev",
            "openrouter": "OpenRouter",
            "siliconflow": "SiliconFlow",
            "together": "Together AI",
            "zai": "Z.AI",
        }
        return ids, models, name_map

_catalog_ids, _catalog_models, _catalog_names = _load_catalog()

KNOWN_PROVIDERS: list[str] = list(_catalog_ids)
PROVIDER_MODELS: dict[str, list[str]] = dict(_catalog_models)


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

        display = _catalog_names.get(name, name)
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

    return providers


def _provider_env_key(name: str) -> str:
    """Get the primary env var name for a provider's API key."""
    mapping = {
        "alibaba": "ALIBABA_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "anthropic-compat": "ANTHROPIC_COMPAT_API_KEY",
        "azure-openai": "AZURE_OPENAI_API_KEY",
        "chatgpt": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "huggingface": "HUGGINGFACE_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openai-compat": "OPENAI_COMPAT_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
        "together": "TOGETHER_API_KEY",
        "zai": "ZAI_API_KEY",
    }
    return mapping.get(name, f"{name.upper()}_API_KEY")


def _provider_alt_env_keys(name: str) -> list[str]:
    """Get alternative env var names for a provider."""
    alt = {
        "anthropic": ["ANTHROPIC_API_KEY"],
        "chatgpt": ["OPENAI_API_KEY"],
        "claude": ["ANTHROPIC_API_KEY"],
        "gemini": ["GOOGLE_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
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
    """Get a human-readable display name for a provider.

    Uses the canonical PROVIDER_CATALOG from backend/api/routes/setup.py
    (or the fallback map if the backend is not loaded).
    Falls back to title-cased name if not found.
    """
    return _catalog_names.get(provider_name, provider_name.title())

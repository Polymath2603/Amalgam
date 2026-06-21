"""
Setup wizard API routes.
Provides endpoints for the first-time setup flow with health validation.

Endpoints:
  GET  /api/setup/status       → {needs_setup: bool, completed_steps: [...], providers: [...]}
  GET  /api/providers          → Available providers with models and defaults
  POST /api/setup/step1         → Configure provider + test connection
  POST /api/setup/step2         → Configure voice (STT engine + TTS engine + test)
  POST /api/setup/step3         → Configure character + behavior preferences
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging

from backend.api.deps import settings as get_settings
from backend.core.health import get_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/setup")

# Standalone router for the providers endpoint at /api/providers
providers_router = APIRouter(prefix="/api")

# ── Setup state key in settings.json ──
SETUP_COMPLETED_KEY = "setup_completed"
SETUP_STEPS_KEY = "setup_steps"

# Map setup-wizard provider IDs to internal settings keys
PROVIDER_KEY_MAP = {
    "openai": "chatgpt",
    "anthropic": "claude",
}

def _settings_key(provider_id: str) -> str:
    """Map a setup-wizard provider ID to the internal settings key."""
    return PROVIDER_KEY_MAP.get(provider_id, provider_id)

# ---------------------------------------------------------------------------
# Curated provider catalog — used by both /api/setup/status and /api/providers
# The models list here serves as a known-good default; the /api/providers
# endpoint also attempts to enrich from litellm's built-in model lists.
# ---------------------------------------------------------------------------
PROVIDER_CATALOG = [
    {"id": "openai",           "name": "OpenAI (ChatGPT)",             "has_free_tier": False, "needs_api_key": True,  "default_model": "gpt-4o-mini",           "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1"],                         "api_key_hint": "starts with sk- or sk-proj- (51+ chars)"},
    {"id": "anthropic",        "name": "Anthropic (Claude)",           "has_free_tier": False, "needs_api_key: "REDACTED", "claude-haiku-3-5"],              "api_key_hint": "starts with sk-ant- (108 chars)"},
    {"id": "gemini",           "name": "Google Gemini",                "has_free_tier": True,  "needs_api_key": True,  "default_model": "gemini-2.0-flash",      "models": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],    "api_key_hint": "starts with AIzaSy (39 chars)"},
    {"id": "openrouter",       "name": "OpenRouter",                   "has_free_tier": True,  "needs_api_key": True,  "default_model": "meta-llama/llama-3.1-8b-instruct:free", "models": ["meta-llama/llama-3.1-8b-instruct:free"],            "api_key_hint": "starts with sk-or-v1- (52+ chars)"},
    {"id": "groq",             "name": "Groq",                         "has_free_tier": True,  "needs_api_key: "REDACTED"], "api_key_hint": "starts with gsk_ (56 chars)"},
    {"id": "deepseek",         "name": "DeepSeek",                     "has_free_tier": False, "needs_api_key": True,  "default_model": "deepseek-chat",         "models": ["deepseek-chat", "deepseek-reasoner"],                         "api_key_hint": "starts with sk- (32+ chars)"},
    {"id": "mistral",          "name": "Mistral",                      "has_free_tier": False, "needs_api_key: "REDACTED"],             "api_key_hint": "starts with Ux... or u... (32 chars)"},
    {"id": "together",         "name": "Together AI",                  "has_free_tier": False, "needs_api_key": True,  "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "models": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],      "api_key_hint": "starts with t1v... or 8x... (40+ chars)"},
    {"id": "opencode",         "name": "OpenCode",                      "has_free_tier": False, "needs_api_key: "REDACTED", "models": [],                     "api_key_hint": "starts with sk- (32+ chars)"},
    {"id": "ollama",           "name": "Ollama (Local)",               "has_free_tier": True,  "needs_api_key": False, "default_model": "",                      "models": [],                                                             "api_key_hint": ""},
    {"id": "llamacpp",         "name": "llama.cpp (Local)",            "has_free_tier": True,  "needs_api_key": False, "default_model": "",                      "models": [],                                                             "api_key_hint": ""},
    {"id": "koboldai",         "name": "KoboldAI (Local)",             "has_free_tier": True,  "needs_api_key": False, "default_model": "",                      "models": [],                                                             "api_key_hint": ""},
    {"id": "azure-openai",     "name": "Azure OpenAI",                  "has_free_tier": False, "needs_api_key": True,  "default_model": "gpt-4o-mini",           "models": ["gpt-4o-mini", "gpt-4o"],                                      "api_key_hint": "paste your Azure API key or set AZURE_OPENAI_API_KEY env"},
    {"id": "aws",              "name": "AWS Bedrock",                   "has_free_tier": False, "needs_api_key": True,  "default_model": "anthropic.claude-sonnet-4-20250514", "models": [],    "api_key_hint": "set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY env vars"},
    {"id": "gcp",              "name": "GCP Vertex AI",                 "has_free_tier": False, "needs_api_key": True,  "default_model": "gemini-2.0-flash-001",  "models": [],                     "api_key_hint": "set GCP_SERVICE_ACCOUNT_JSON env var"},
    {"id": "alibaba",          "name": "Alibaba Cloud (DashScope)",     "has_free_tier": True,  "needs_api_key": True,  "default_model": "qwen-turbo",            "models": ["qwen-turbo", "qwen-plus", "qwen-max"],                       "api_key_hint": "starts with sk- (32+ chars) or set ALIBABA_API_KEY env"},
    {"id": "siliconflow",      "name": "SiliconFlow",                  "has_free_tier": True,  "needs_api_key": True,  "default_model": "deepseek-ai/DeepSeek-R1", "models": ["deepseek-ai/DeepSeek-R1", "deepseek-ai/DeepSeek-V3"],     "api_key_hint": "starts with sk- (32+ chars)"},
    {"id": "huggingface",      "name": "Hugging Face Inference",       "has_free_tier": True,  "needs_api_key": True,  "default_model": "",                      "models": [],                                                             "api_key_hint": "starts with hf_ (36+ chars)"},
    {"id": "zai",              "name": "ZAI (Turing/LLM-ZH)",          "has_free_tier": False, "needs_api_key": True,  "default_model": "google/gemma-2-27b-it", "models": ["google/gemma-2-27b-it", "Qwen/QwQ-32B-Preview"],             "api_key_hint": "starts with zsk- (32+ chars)"},
]


class Step1Request(BaseModel):
    provider: str
    api_key: str = ""
    model: str = ""

class Step2Request(BaseModel):
    stt_engine: str = "browser"
    tts_engine: str = "edge-tts"
    voice_input_enabled: bool = True
    voice_output_enabled: bool = True

class Step3Request(BaseModel):
    character: str = "default"
    permission_level: str = "confirm"
    companion_enabled: bool = False
    thinking_enabled: bool = True


@router.get("/status")
async def get_setup_status():
    """Check if setup has been completed and return available providers."""
    s = get_settings()
    completed = s.get(SETUP_COMPLETED_KEY, False)
    steps = s.get(SETUP_STEPS_KEY, [])
    
    return {
        "needs_setup": not completed,
        "completed_steps": steps,
        "providers": PROVIDER_CATALOG,
    }


@providers_router.get("/providers")
async def list_providers():
    """Return available LLM providers with their models and defaults.

    This endpoint dynamically tries to enrich model lists from litellm's
    built-in model catalog, falling back to the curated defaults.
    It also detects which providers have API keys configured in env vars or settings.
    """
    import os
    try:
        from backend.core.llm.router import LLMRouter
        router_instance = LLMRouter()
        s = get_settings()
        providers = []

        # Env-var key names per provider ID
        ENV_KEYS = {
            "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            "openai": ["OPENAI_API_KEY"],
            "anthropic": ["ANTHROPIC_API_KEY"],
            "groq": ["GROQ_API_KEY"],
            "deepseek": ["DEEPSEEK_API_KEY"],
            "mistral": ["MISTRAL_API_KEY"],
            "together": ["TOGETHER_API_KEY"],
            "siliconflow": ["SILICONFLOW_API_KEY"],
            "zai": ["ZAI_API_KEY"],
            "huggingface": ["HUGGINGFACE_API_KEY"],
            "openrouter": ["OPENROUTER_API_KEY"],
            "azure-openai": ["AZURE_OPENAI_API_KEY"],
            "alibaba": ["ALIBABA_API_KEY", "DASHSCOPE_API_KEY"],
            "aws": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
            "gcp": ["GCP_SERVICE_ACCOUNT_JSON"],
            "opencode": ["OPENCODE_API_KEY"],
        }

        for p in PROVIDER_CATALOG:
            entry = dict(p)  # shallow copy
            pid = p["id"]

            # Detect if already configured via settings or env vars
            provider_key = _settings_key(pid)
            cfg = s.get(f"provider.{provider_key}")
            has_api_key = False
            if cfg and isinstance(cfg, dict) and cfg.get("api_key"):
                has_api_key = True
            if not has_api_key:
                env_names = ENV_KEYS.get(pid, [])
                has_api_key = any(os.environ.get(k) for k in env_names)

            entry["has_api_key"] = has_api_key

            # Only enrich models for the currently active provider
            active_provider = s.get("provider.active", "")
            litellm_models = None
            if pid == active_provider:
                try:
                    if pid == "gemini":
                        litellm_models = await router_instance.fetch_gemini_models()
                    elif pid in ("openai", "chatgpt"):
                        litellm_models = await router_instance.fetch_openai_compat_models("chatgpt")
                    elif pid == "anthropic":
                        litellm_models = await router_instance.fetch_openai_compat_models("anthropic")
                    elif pid == "groq":
                        litellm_models = await router_instance.fetch_openai_compat_models("groq")
                    elif pid == "ollama":
                        litellm_models = await router_instance.fetch_ollama_models()
                    elif pid == "openrouter":
                        litellm_models = await router_instance.fetch_openai_compat_models("openrouter")
                    elif pid == "deepseek":
                        litellm_models = await router_instance.fetch_openai_compat_models("deepseek")
                    elif pid == "mistral":
                        litellm_models = await router_instance.fetch_openai_compat_models("mistral")
                    elif pid == "together":
                        litellm_models = await router_instance.fetch_openai_compat_models("together")
                except Exception:
                    logger.debug("Could not enrich models for %s from litellm", pid, exc_info=True)

            if litellm_models:
                entry["models"] = litellm_models
                # Ensure default_model is still valid
                if entry.get("default_model") and entry["default_model"] not in litellm_models:
                    entry["default_model"] = litellm_models[0] if litellm_models else ""

            providers.append(entry)

        return {"providers": providers}

    except ImportError:
        logger.warning("LLMRouter not available, returning curated provider list")
        providers = [dict(p) for p in PROVIDER_CATALOG]
        for p in providers:
            pid = p["id"]
            provider_key = _settings_key(pid)
            cfg = (get_settings()).get(f"provider.{provider_key}")
            has_api_key = False
            if cfg and isinstance(cfg, dict) and cfg.get("api_key"):
                has_api_key = True
            if not has_api_key:
                env_names = ENV_KEYS.get(pid, [])
                has_api_key = any(os.environ.get(k) for k in env_names) if 'ENV_KEYS' in dir() else False
            p["has_api_key"] = has_api_key
        return {"providers": providers}
    except Exception as exc:
        logger.error("Failed to list providers: %s", exc)
        return {"providers": PROVIDER_CATALOG}


@router.post("/step1")
async def setup_step1(req: Step1Request):
    """Configure the LLM provider. Validates the connection."""
    s = get_settings()
    provider_key = _settings_key(req.provider)
    
    # Save provider config
    s.set("provider.active", provider_key)
    if req.api_key:
        s.set(f"provider.{provider_key}.api_key", req.api_key)
    if req.model:
        s.set(f"provider.{provider_key}.model", req.model)
    
    # Test connection using health registry
    registry = get_registry()
    state = await registry.check("llm")
    
    ok = state.status.value == "ok"
    
    # Mark step completed
    steps = s.get(SETUP_STEPS_KEY, [])
    if "provider" not in steps:
        steps.append("provider")
    s.set(SETUP_STEPS_KEY, steps)
    
    return {
        "ok": ok,
        "provider": req.provider,
        "detail": state.detail,
        "error": state.last_error if not ok else None,
    }


@router.post("/step2")
async def setup_step2(req: Step2Request):
    """Configure voice settings. Tests TTS if possible."""
    s = get_settings()
    
    s.set("voice.stt_engine", req.stt_engine)
    s.set("voice.engine", req.tts_engine)
    s.set("voice.input_enabled", req.voice_input_enabled)
    s.set("voice.output_enabled", req.voice_output_enabled)
    
    # Test TTS connection if not using browser engine
    tts_ok = True
    tts_detail = "configured"
    if req.tts_engine != "browser":
        registry = get_registry()
        state = await registry.check("tts")
        tts_ok = state.status.value == "ok"
        tts_detail = state.detail
    
    steps = s.get(SETUP_STEPS_KEY, [])
    if "voice" not in steps:
        steps.append("voice")
    s.set(SETUP_STEPS_KEY, steps)
    
    return {
        "ok": tts_ok,
        "tts_detail": tts_detail,
    }


@router.post("/step3")
async def setup_step3(req: Step3Request):
    """Configure character and behavior preferences."""
    s = get_settings()
    
    s.set("character.active", req.character)
    s.set("behavior.permission_level", req.permission_level)
    s.set("behavior.companion_enabled", req.companion_enabled)
    s.set("behavior.thinking_enabled", req.thinking_enabled)
    
    # Mark setup as fully completed
    steps = s.get(SETUP_STEPS_KEY, [])
    if "character" not in steps:
        steps.append("character")
    if "behavior" not in steps:
        steps.append("behavior")
    s.set(SETUP_STEPS_KEY, steps)
    s.set(SETUP_COMPLETED_KEY, True)
    
    return {
        "ok": True,
        "setup_complete": True,
        "character": req.character,
    }


@router.post("/save")
async def save_setup(body: dict):
    """Save initial provider configuration from the setup wizard."""
    provider = body.get("provider", "gemini")
    api_key = body.get("api_key", "")
    model = body.get("model", "")

    if not api_key:
        return {"status": "error", "message": "API key is required"}

    s = get_settings()
    provider_key = _settings_key(provider)
    s.set("provider.active", provider_key)
    s.set(f"provider.{provider_key}.api_key", api_key)
    if model:
        s.set(f"provider.{provider_key}.model", model)

    # Also configure LLM with the new settings
    try:
        from backend.api.deps import llm
        llm().reload_settings()
    except Exception:
        logger.warning("Failed to reload LLM settings after setup save")

    return {"status": "ok", "provider": provider}

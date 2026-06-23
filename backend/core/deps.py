"""
Shared component injection — used by CLI, gRPC, and WebUI.
Not part of the `api` package to avoid cross-boundary imports.
"""
import logging
import threading
from types import MappingProxyType
from typing import Any, Dict, Optional

import backend.core.config.settings as _settings_mod
from backend.core.config.settings import Settings
from backend.core.llm import LLMRouter
from backend.core.memory import Memory
from backend.core.context_builder import ContextBuilder
from backend.core.context_manager import ContextManager
from backend.core.vault import VaultManager
from backend.core.paths import EMBEDDINGS_DIR
from backend.core.agent.core import Agent
from backend.core.agent.factory import AgentFactory
from backend.core.metacognitive.strategy_selector import StrategySelector
from backend.core.relationship import Relationship
from backend.core.mcp.client import MCPClient
from backend.core.voice.tts import TTS
from backend.voice.wakeword import WakeWordRouter
from backend.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

_shared: Dict[str, Any] = {
    "settings": None,
    "llm": None,
    "memory": None,
    "context_builder": None,
    "context_manager": None,
    "vault": None,
    "mcp": None,
    "tts": None,
    "agent": None,
    "relationship": None,
    "wakeword": None,
    "strategy_selector": None,
    "orchestrator": None,
    "companion": None,
}
_init_lock = threading.Lock()


def get_shared() -> MappingProxyType:
    """Return a read-only view of shared components, initializing lazily if needed."""
    with _init_lock:
        if _shared["settings"] is None:
            _shared["settings"] = Settings()
            # Register with module-level wrappers (C5 fix, N5 fix)
            _settings_mod.set_global_instance(_shared["settings"])
        if _shared["llm"] is None:
            _shared["llm"] = LLMRouter(settings=_shared["settings"])
        if _shared["memory"] is None:
            _shared["memory"] = Memory(llm_router=_shared["llm"], settings=_shared["settings"])
        if _shared["context_builder"] is None:
            _shared["context_builder"] = ContextBuilder(settings=_shared["settings"])
        if _shared["context_manager"] is None:
            _shared["context_manager"] = ContextManager(settings=_shared["settings"])
        if _shared["vault"] is None:
            from backend.core.paths import VAULT_DIR
            vault_path = _shared["settings"].get("vault.path", str(VAULT_DIR))
            _shared["vault"] = VaultManager(vault_path, embeddings_path=str(EMBEDDINGS_DIR))
        if _shared["mcp"] is None:
            _shared["mcp"] = MCPClient()
        if _shared["tts"] is None:
            engine = _shared["settings"].get("voice.engine", "edge-tts")
            _shared["tts"] = TTS(engine=engine)
            elevenlabs_key = _shared["settings"].get("voice.elevenlabs.api_key", "")
            if elevenlabs_key:
                elevenlabs_model = _shared["settings"].get("voice.elevenlabs.model", "eleven_multilingual_v2")
                _shared["tts"].configure_elevenlabs(elevenlabs_key, elevenlabs_model)
            azure_key = _shared["settings"].get("voice.azure.api_key", "")
            if azure_key:
                azure_region = _shared["settings"].get("voice.azure.region", "eastus")
                _shared["tts"].configure_azure(azure_key, azure_region)
            dashscope_key = _shared["settings"].get("voice.dashscope.api_key", "")
            if dashscope_key:
                dashscope_model = _shared["settings"].get("voice.dashscope.model", "cosyvoice-v1")
                _shared["tts"].configure_dashscope(dashscope_key, dashscope_model)
            volcengine_app_id = _shared["settings"].get("voice.volcengine.app_id", "")
            volcengine_token = _shared["settings"].get("voice.volcengine.access_token", "")
            if volcengine_app_id and volcengine_token:
                volcengine_cluster = _shared["settings"].get("voice.volcengine.cluster", "volcano_tts")
                _shared["tts"].configure_volcengine(volcengine_app_id, volcengine_token, volcengine_cluster)
            deepgram_key = _shared["settings"].get("voice.deepgram.api_key", "")
            if deepgram_key:
                deepgram_model = _shared["settings"].get("voice.deepgram.model", "aura-2")
                _shared["tts"].configure_deepgram(deepgram_key, deepgram_model)
        if _shared["relationship"] is None:
            _shared["relationship"] = Relationship()
        if _shared["wakeword"] is None:
            ww_engine = _shared["settings"].get("wake_word.engine", "openwakeword")
            _shared["wakeword"] = WakeWordRouter(engine=ww_engine)
        if _shared["strategy_selector"] is None:
            _shared["strategy_selector"] = StrategySelector()
        if _shared["orchestrator"] is None:
            _shared["orchestrator"] = Orchestrator(config=_shared["settings"])
        if _shared["companion"] is None:
            from backend.core.companion.scheduler import CompanionScheduler
            # Capture references at init time (fix C2)
            _settings_ref = _shared["settings"]
            _llm_ref = _shared["llm"]
            _memory_ref = _shared["memory"]
            _shared["companion"] = CompanionScheduler(
                settings_provider=lambda: _settings_ref,
                llm_provider=lambda: _llm_ref,
                memory_provider=lambda: _memory_ref,
            )
        if _shared["agent"] is None:
            agent_type = _shared["settings"].get("agent.type", "reflective_planning")
            mcp_client = _shared["mcp"]
            # Log when agent type is overridden (fix L1)
            if agent_type is None:
                logger.info("agent.type is null in config, falling back to 'basic'")
            try:
                _shared["agent"] = AgentFactory.create(
                    agent_type or "basic",
                    llm=_shared["llm"],
                    tools={},
                    memory=_shared["memory"],
                    config=_shared["settings"],
                    mcp_client=mcp_client,
                    strategy_selector=_shared["strategy_selector"],
                )
            except Exception:
                # Log exception before fallback (fix H1)
                logger.exception("AgentFactory.create failed, falling back to basic Agent")
                _shared["agent"] = Agent(
                    mcp_client=mcp_client,
                    llm=_shared["llm"],
                    memory=_shared["memory"],
                    context_builder=_shared["context_builder"],
                    settings=_shared["settings"],
                    strategy_selector=_shared["strategy_selector"],
                )
            # Register sub-agent spawner via callable to avoid circular dependency
            try:
                mcp_client.register_subagent_spawner(_shared["agent"].spawn_subagent)
            except Exception:
                logger.exception("Failed to register subagent spawner, resetting agent")
                _shared["agent"] = None
                raise

        # Lazy-init remaining keys inside the lock (fix C1)
        if _shared.get("characters_dir") is None:
            from backend.core.paths import CHARACTERS_DIR as _C
            _shared["characters_dir"] = _C
        if _shared.get("health_registry") is None:
            from backend.core.health import get_registry as _gr
            _shared["health_registry"] = _gr()
        if _shared.get("metrics_collector") is None:
            from backend.core.metrics import get_collector as _gc
            _shared["metrics_collector"] = _gc()
        if _shared.get("switch_profile") is None:
            from backend.core.config.settings import switch_profile as _sp
            _shared["switch_profile"] = _sp
        if _shared.get("known_providers") is None:
            try:
                from cli.provider import KNOWN_PROVIDERS as _kp
                _shared["known_providers"] = _kp
            except (ImportError, ModuleNotFoundError):
                logger.warning("cli.provider not importable — known_providers not available")
                _shared["known_providers"] = {}
        if _shared.get("provider_models") is None:
            try:
                from cli.provider import PROVIDER_MODELS as _pm
                _shared["provider_models"] = _pm
            except (ImportError, ModuleNotFoundError):
                logger.warning("cli.provider not importable — provider_models not available")
                _shared["provider_models"] = {}

        # Return read-only proxy (fix H6)
        return MappingProxyType(_shared)


def set_shared(key: str, value: Any) -> None:
    """Set a shared component value under the lock."""
    with _init_lock:
        _shared[key] = value


# H2 fix: accessors read from _shared directly without lock.
# GIL protects dict reads; all writes happen under _init_lock during
# get_shared(), which is always called at startup before any accessor.
def settings() -> Settings:
    return _shared["settings"]

def llm() -> LLMRouter:
    return _shared["llm"]

def memory() -> Memory:
    return _shared["memory"]

def context_builder() -> ContextBuilder:
    return _shared["context_builder"]

def context_manager() -> ContextManager:
    return _shared["context_manager"]

def vault() -> VaultManager:
    return _shared["vault"]

def mcp() -> MCPClient:
    return _shared["mcp"]

def tts() -> TTS:
    return _shared["tts"]

def agent() -> Agent:
    return _shared["agent"]

def relationship() -> Relationship:
    return _shared["relationship"]

def wakeword() -> WakeWordRouter:
    return _shared["wakeword"]

def strategy_selector() -> StrategySelector:
    return _shared["strategy_selector"]

def orchestrator() -> Orchestrator:
    return _shared["orchestrator"]

def companion() -> Any:
    return _shared["companion"]

def characters_dir() -> Any:
    return _shared["characters_dir"]

def health_registry() -> Any:
    return _shared["health_registry"]

def metrics_collector() -> Any:
    return _shared["metrics_collector"]

def switch_profile_func() -> Any:
    return _shared["switch_profile"]

def known_providers() -> Dict[str, Any]:
    return _shared["known_providers"]

def provider_models() -> Dict[str, Any]:
    return _shared["provider_models"]


# ── Voice pipeline registry ───────────────────────────────────────────
# Protected with a threading lock (fix M14)

_voice_pipeline_lock = threading.Lock()
_voice_pipeline_registry: Dict[str, Any] = {}

def set_voice_pipeline(pipeline: Any) -> None:
    """Register the active voice pipeline instance."""
    with _voice_pipeline_lock:
        _voice_pipeline_registry["pipeline"] = pipeline

def get_voice_pipeline() -> Optional[Any]:
    """Get the registered voice pipeline, or None."""
    with _voice_pipeline_lock:
        return _voice_pipeline_registry.get("pipeline")

def clear_voice_pipeline() -> None:
    """Clear the registered voice pipeline (e.g. on disconnect)."""
    with _voice_pipeline_lock:
        _voice_pipeline_registry.pop("pipeline", None)

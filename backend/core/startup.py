"""
Shared application initialization for all frontends (webui, CLI, gRPC).
Extracted from backend/app.py startup event so CLI and other modes
get the same initialization path.
"""
import copy
import os
import asyncio
import logging
from typing import Optional

from backend.core.deps import get_shared, set_shared
from backend.core.paths import VAULT_DIR

logger = logging.getLogger(__name__)

# Track background tasks for clean shutdown (fix H7, N2, N8)
_background_tasks: set[asyncio.Task] = set()


def _track_task(task: asyncio.Task) -> None:
    """Register a background task for lifecycle tracking."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def init_application():
    """Initialize all shared components. Safe to call multiple times (idempotent for singletons).

    Initializes:
      - All shared singletons (settings, llm, memory, mcp, tts, agent, etc.)
      - Vault directory and default rules.md
      - Conversation session
      - TTS engine (OpenVoice only, others are lazy)
      - MCP server connections
    """
    # Capture the running event loop for thread-safe callbacks (fix N3)
    _loop = asyncio.get_running_loop()

    shared = get_shared()
    settings = shared["settings"]

    log_level = settings.get("log.level", "WARNING")
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if log_level.upper() not in valid_levels:
        logger.warning("Invalid log level: %r, falling back to WARNING", log_level)
        log_level = "WARNING"
    log_format = settings.get("log.format", "console")
    from backend.core.log_config import configure_logging
    configure_logging(level=log_level, log_format=log_format)
    memory = shared["memory"]
    mcp_client = shared["mcp"]
    tts_engine = shared["tts"]

    vault_path = settings.get("vault.path", str(VAULT_DIR))
    os.makedirs(vault_path, exist_ok=True)
    rules_path = os.path.join(vault_path, "rules.md")
    if not os.path.exists(rules_path):
        with open(rules_path, "w") as f:
            f.write("# Rules\n\nAdd your custom rules here. These will be injected into every conversation.\n")

    # Guard: only start a session if none is active (fix H10, N1)
    if not memory.has_active_session():
        memory.start_session()

    engine = settings.get("voice.engine", "edge-tts")
    if engine == "openvoice":
        logger.debug("Preloading OpenVoice TTS engine...")
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, tts_engine.get_openvoice_loaded)
            logger.debug("OpenVoice TTS engine ready")
        except Exception as e:
            logger.warning(f"OpenVoice preload failed: {e}")

    mcp_servers = copy.deepcopy(settings.get_mcp_servers())  # fix N4
    if mcp_servers:
        for s in mcp_servers:
            if s.get("name") == "shell":
                shell_mode = settings.get("shell.mode", "safe")
                shell_prefixes = settings.get("shell.allowed_prefixes", [])
                s.setdefault("env", {})
                s["env"]["AMALGAM_SHELL_MODE"] = shell_mode
                s["env"]["AMALGAM_SHELL_ALLOWED_COMMANDS"] = ",".join(shell_prefixes)
        task = asyncio.create_task(mcp_client.connect_from_settings(mcp_servers))
        _track_task(task)  # fix N2

    settings.start_watcher()
    # Pass captured loop for thread-safe callbacks (fix N3)
    settings.on_change(make_settings_reloader(mcp_client, loop=_loop))

    # ── Discover and load plugins ────────────────────────────────────
    try:
        from backend.plugins.manager import PluginManager
        plugin_mgr = PluginManager(auto_register=True)
        await plugin_mgr.discover_and_load()
        set_shared("plugin_manager", plugin_mgr)
        logger.info("Plugin system initialized with %d plugin(s)", len(plugin_mgr.plugins))
    except Exception as e:
        logger.warning(f"Plugin initialization skipped: {e}")

    # ── Register health checks and start background checker ────────────
    from backend.core.health import register_builtin_checks, get_registry

    register_builtin_checks(
        settings_obj=settings,
        llm_obj=shared.get("llm"),
        tts_obj=shared.get("tts"),
    )
    await get_registry().start_background_checker(interval=60)


def make_settings_reloader(mcp_client, *, loop):
    """Return a callback that hot-reloads components when settings change.

    Args:
        mcp_client: The MCP client instance.
        loop: The asyncio event loop captured at init time (fix N3).
    """
    from backend.core.deps import get_shared

    def _reload(settings):
        """Reload MCP servers and refresh character data on settings change."""
        shared = get_shared()
        try:
            mcp_servers = copy.deepcopy(settings.get_mcp_servers())  # fix N4
            if mcp_servers:
                for s in mcp_servers:
                    if s.get("name") == "shell":
                        shell_mode = settings.get("shell.mode", "safe")
                        shell_prefixes = settings.get("shell.allowed_prefixes", [])
                        s.setdefault("env", {})
                        s["env"]["AMALGAM_SHELL_MODE"] = shell_mode
                        s["env"]["AMALGAM_SHELL_ALLOWED_COMMANDS"] = ",".join(shell_prefixes)
                future = asyncio.run_coroutine_threadsafe(
                    mcp_client.connect_from_settings(mcp_servers), loop
                )
                def _log_future_error(f):
                    try:
                        exc = f.exception()
                        if exc:
                            logger.warning("Settings hot-reload MCP connect failed: %s", exc)
                    except asyncio.CancelledError:
                        pass
                future.add_done_callback(_log_future_error)

            # Use public API instead of private attribute (fix C3)
            settings.reload_characters()
        except Exception as e:
            logger.warning(f"Settings hot-reload failed: {e}")

    return _reload


async def shutdown_application():
    """Clean up shared resources. Call on application shutdown."""
    try:
        # Cancel tracked background tasks (fix N2)
        while _background_tasks:
            tasks = list(_background_tasks)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        from backend.core.deps import mcp, memory
        await mcp().close()
        await memory().shutdown()
        from backend.core.hot_reload import get_reloader
        get_reloader().stop()
        from backend.core.health import get_registry
        await get_registry().stop_background_checker()
        # Shutdown all plugins
        try:
            from backend.plugins.manager import PluginManager
            from backend.core.deps import get_shared
            shared = get_shared()
            plugin_mgr = shared.get("plugin_manager")
            if plugin_mgr:
                errors = await plugin_mgr.shutdown_all(timeout=10.0)
                if errors:
                    logger.warning(
                        "%d plugin(s) had shutdown errors", len(errors)
                    )
        except Exception as e:
            logger.warning(f"Plugin shutdown error: {e}")
    except Exception as e:
        logger.warning(f"Shutdown error: {e}")

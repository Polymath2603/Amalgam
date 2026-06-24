"""
Plugin system — simple event-driven hooks at lifecycle points.

Plugins register callbacks that are invoked at various points
in the agent loop, context building, and tool execution.
"""
import asyncio
import importlib
import logging
import os
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "Plugin",
    "PluginRegistry",
    "register",
    "get_registry",
    "reset_registry",
    "discover_plugins",
]


class Plugin:
    """Base plugin class with lifecycle and event hooks.

    Subclasses must set a non-empty ``name`` class attribute or override
    the ``name`` property.
    """

    name: str = ""

    def __init__(self) -> None:
        if not self.name:
            raise ValueError(
                "Plugin subclasses must set a non-empty `name` attribute"
            )
        self._enabled = True

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    async def on_initialize(self) -> None:
        """Called during plugin initialisation (async setup)."""
        pass

    async def on_shutdown(self) -> None:
        """Called during plugin shutdown (async teardown)."""
        pass

    async def on_enable(self) -> None:
        """Called when the plugin is enabled."""
        pass

    async def on_disable(self) -> None:
        """Called when the plugin is disabled."""
        pass

    # ------------------------------------------------------------------
    # Feature hooks (called by the agent loop)
    # ------------------------------------------------------------------

    async def on_tool_definition(self, tools: list[dict]) -> list[dict]:
        return tools

    async def on_system_prompt(self, prompt: str) -> str:
        return prompt

    async def on_messages(self, messages: list[dict]) -> list[dict]:
        return messages

    async def on_compaction(self, summary: str) -> str:
        return summary

    async def on_tool_result(
        self, tool_name: str, args: dict, result: str
    ) -> str:
        return result

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        return self._enabled


_HOOK_TIMEOUT: float = 30.0


async def _call_with_timeout(
    coro_factory: Callable[[], Any],
    plugin_name: str,
    hook_name: str,
    timeout: float = _HOOK_TIMEOUT,
) -> Any:
    """Await *coro_factory()* with a timeout, logging failures.

    Returns *None* on error so callers can skip the result without
    catching exceptions explicitly.
    """
    try:
        return await asyncio.wait_for(coro_factory(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(
            "Plugin '%s' %s timed out after %.1fs",
            plugin_name,
            hook_name,
            timeout,
        )
        return None
    except Exception:
        logger.exception("Plugin '%s' %s failed", plugin_name, hook_name)
        return None


class PluginRegistry:
    """Registry that manages plugin lifecycle and dispatch.

    The registry is deliberately kept simple so it can be used both as a
    standalone system and as the backing store for the richer
    ``PluginManager`` in ``backend.plugins``.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self, plugin: Plugin, *, on_conflict: str = "warn"
    ) -> None:
        """Register a plugin.

        Args:
            plugin: Plugin instance to register.
            on_conflict: What to do when a plugin with the same name
                already exists:

                - ``"warn"`` — log a warning and overwrite (default).
                - ``"raise"`` — raise :class:`ValueError`.
                - ``"skip"`` — keep the existing entry and skip the new
                  one.
        """
        if not plugin.name:
            raise ValueError("Cannot register a plugin with an empty name")

        existing = plugin.name in self._plugins
        if existing:
            if on_conflict == "raise":
                raise ValueError(
                    f"Plugin '{plugin.name}' is already registered"
                )
            if on_conflict == "skip":
                logger.info(
                    "Skipping already-registered plugin: %s", plugin.name
                )
                return
            # default: warn + overwrite
            logger.warning("Overwriting plugin: %s", plugin.name)

        self._plugins[plugin.name] = plugin
        logger.info("Registered plugin: %s", plugin.name)

    def unregister(self, name: str) -> Optional[Plugin]:
        """Remove *name* from the registry and return it (or *None*)."""
        return self._plugins.pop(name, None)

    def get(self, name: str) -> Optional[Plugin]:
        """Return the plugin registered under *name*, or *None*."""
        return self._plugins.get(name)

    @property
    def all(self) -> list[Plugin]:
        return list(self._plugins.values())

    def clear(self) -> None:
        """Remove all plugins (useful for testing)."""
        self._plugins.clear()

    # ------------------------------------------------------------------
    # Hook dispatch
    # ------------------------------------------------------------------

    async def hook_tool_definition(
        self, tools: list[dict], *, timeout: float = _HOOK_TIMEOUT
    ) -> list[dict]:
        for p in self._plugins.values():
            if not p.is_enabled():
                continue
            result = await _call_with_timeout(
                lambda p=p, tools=tools: p.on_tool_definition(tools),
                p.name,
                "on_tool_definition",
                timeout=timeout,
            )
            if result is not None:
                tools = result
        return tools

    async def hook_system_prompt(
        self, prompt: str, *, timeout: float = _HOOK_TIMEOUT
    ) -> str:
        for p in self._plugins.values():
            if not p.is_enabled():
                continue
            result = await _call_with_timeout(
                lambda p=p, prompt=prompt: p.on_system_prompt(prompt),
                p.name,
                "on_system_prompt",
                timeout=timeout,
            )
            if result is not None:
                prompt = result
        return prompt

    async def hook_messages(
        self, messages: list[dict], *, timeout: float = _HOOK_TIMEOUT
    ) -> list[dict]:
        for p in self._plugins.values():
            if not p.is_enabled():
                continue
            result = await _call_with_timeout(
                lambda p=p, messages=messages: p.on_messages(messages),
                p.name,
                "on_messages",
                timeout=timeout,
            )
            if result is not None:
                messages = result
        return messages

    async def hook_compaction(
        self, summary: str, *, timeout: float = _HOOK_TIMEOUT
    ) -> str:
        for p in self._plugins.values():
            if not p.is_enabled():
                continue
            result = await _call_with_timeout(
                lambda p=p, summary=summary: p.on_compaction(summary),
                p.name,
                "on_compaction",
                timeout=timeout,
            )
            if result is not None:
                summary = result
        return summary

    async def hook_tool_result(
        self,
        tool_name: str,
        args: dict,
        result: str,
        *,
        timeout: float = _HOOK_TIMEOUT,
    ) -> str:
        for p in self._plugins.values():
            if not p.is_enabled():
                continue
            res = await _call_with_timeout(
                lambda p=p, tool_name=tool_name, args=args,
                result=result: p.on_tool_result(
                    tool_name, args, result
                ),
                p.name,
                "on_tool_result",
                timeout=timeout,
            )
            if res is not None:
                result = res
        return result


# ------------------------------------------------------------------
# Global singleton
# ------------------------------------------------------------------

_registry = PluginRegistry()


def register(plugin: Plugin, *, on_conflict: str = "warn") -> None:
    """Convenience: register *plugin* with the global registry."""
    _registry.register(plugin, on_conflict=on_conflict)


def get_registry() -> PluginRegistry:
    """Return the global plugin registry."""
    return _registry


def reset_registry() -> None:
    """Clear the global registry (useful for testing)."""
    _registry.clear()


# ------------------------------------------------------------------
# Discovery helpers
# ------------------------------------------------------------------

def discover_plugins(
    plugin_dir: str,
    *,
    registry: Optional[PluginRegistry] = None,
    on_conflict: str = "warn",
) -> list[Plugin]:
    """Scan *plugin_dir* for plugin modules and register discovered
    plugins.

    Each file should expose a module-level ``register()`` function
    returning a dict with at least a ``"name"`` key, or a ``PluginClass``
    attribute that is a subclass of :class:`Plugin`.

    Args:
        plugin_dir: Directory to scan.
        registry: Target registry (defaults to the global singleton).
        on_conflict: Passed through to :meth:`PluginRegistry.register`.

    Returns:
        List of successfully loaded plugins.
    """
    if registry is None:
        registry = _registry

    loaded: list[Plugin] = []
    plugin_dir = os.path.abspath(plugin_dir)

    if not os.path.isdir(plugin_dir):
        logger.warning("Plugin directory not found: %s", plugin_dir)
        return loaded

    for fname in sorted(os.listdir(plugin_dir)):
        if fname.startswith("_") or not fname.endswith(".py"):
            continue
        mod_name = fname[:-3]
        mod_path = os.path.join(plugin_dir, fname)
        try:
            spec = importlib.util.spec_from_file_location(
                f"_discovered_plugin_{mod_name}", mod_path
            )
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            # Try PluginClass first, then register() function
            plugin: Optional[Plugin] = None
            plugin_class = getattr(mod, "PluginClass", None)
            if isinstance(plugin_class, type) and issubclass(plugin_class, Plugin):
                plugin = plugin_class()
            elif hasattr(mod, "register"):
                result = mod.register()
                if isinstance(result, Plugin):
                    plugin = result
                elif isinstance(result, dict):
                    name = result.get("name", mod_name)
                    basic = type(
                        "_Discovered_" + name,
                        (Plugin,),
                        {"name": name},
                    )()
                    plugin = basic

            if plugin is not None:
                registry.register(plugin, on_conflict=on_conflict)
                loaded.append(plugin)
                logger.info("Discovered plugin: %s", plugin.name)
        except Exception:
            logger.exception(
                "Failed to load plugin module: %s", mod_name
            )

    return loaded

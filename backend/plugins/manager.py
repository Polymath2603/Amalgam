"""
Plugin manager — discovers, loads, and manages plugins.

Loaded plugins are automatically bridged to the global
:class:`~backend.core.plugin.PluginRegistry` so their hooks are
available throughout the agent loop.
"""

import asyncio
import importlib.util
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from backend.core import plugin as core_plugin
from backend.plugins.base import BasePlugin, PluginMetadata

logger = logging.getLogger(__name__)

__all__ = ["PluginManager"]


class PluginManager:
    """Manages plugin lifecycle and discovery.

    Args:
        plugins_dir: Directory to search for plugin sub-directories.
            Defaults to the parent of this module.
        auto_register: If ``True`` (the default), every successfully
            loaded plugin is also registered with the global
            :class:`~backend.core.plugin.PluginRegistry`.
    """

    def __init__(
        self,
        plugins_dir: Optional[Path] = None,
        auto_register: bool = True,
    ):
        self.plugins_dir = plugins_dir or Path(__file__).parent
        self.auto_register = auto_register
        self.plugins: Dict[str, BasePlugin] = {}
        self.loaded_modules: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Discovery & loading
    # ------------------------------------------------------------------

    async def discover_and_load(
        self, configs: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> None:
        """Discover and load all plugins from the plugins directory.

        Each plugin should be a sub-directory containing a ``plugin.py``
        file that exposes a ``PluginClass`` extending :class:`BasePlugin`.

        Args:
            configs: Optional mapping of plugin name → configuration
                dict to pass to the plugin constructor.
        """
        if not self.plugins_dir.is_dir():
            logger.warning(
                "Plugins directory not found: %s", self.plugins_dir
            )
            return

        configs = configs or {}

        try :
            dirs =list (self .plugins_dir .iterdir ())
        except OSError as e :
            logger .error ("Failed to list plugins directory %s: %s",self .plugins_dir ,e )
            return 

        for plugin_dir in dirs :
            if not plugin_dir .is_dir ()or plugin_dir .name .startswith ("_"):
                continue 

            plugin_file =plugin_dir /"plugin.py"
            if plugin_file .exists ():
                await self ._load_plugin (
                plugin_dir ,plugin_file ,configs .get (plugin_dir .name )
                )

    async def _load_plugin(
        self,
        plugin_dir: Path,
        plugin_file: Path,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Load a single plugin from *plugin_file*.

        The module must define a ``PluginClass`` attribute that is a
        subclass of :class:`BasePlugin`.

        After instantiation, :meth:`BasePlugin.initialize` is called,
        which in turn calls :meth:`BasePlugin.on_initialize`.  If
        *auto_register* is enabled the plugin is also registered with the
        global :class:`~backend.core.plugin.PluginRegistry`.
        """
        try:
            spec = importlib.util.spec_from_file_location(
                f"plugins.{plugin_dir.name}", plugin_file
            )
            if spec is None or spec.loader is None:
                logger.error(
                    "Could not load spec for %s", plugin_file
                )
                return

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "PluginClass"):
                logger.warning(
                    "Plugin %s has no PluginClass defined",
                    plugin_dir.name,
                )
                return

            plugin_class: Type[BasePlugin] = module.PluginClass

            # Pass config if the constructor supports it
            try:
                plugin_instance = plugin_class(config=config)
            except TypeError:
                # Fall back to no-arg constructor for older plugins
                plugin_instance = plugin_class()

            await plugin_instance.initialize()

            self.plugins[plugin_instance.name] = plugin_instance
            self.loaded_modules[plugin_instance.name] = module

            # Bridge: register with the global PluginRegistry
            if self.auto_register:
                core_plugin.register(
                    plugin_instance, on_conflict="warn"
                )

            logger.info(
                "Loaded plugin: %s v%s",
                plugin_instance.name,
                plugin_instance.metadata.version,
            )

        except Exception:
            logger.exception(
                "Failed to load plugin from %s", plugin_file
            )

    # ------------------------------------------------------------------
    # Reload / unload
    # ------------------------------------------------------------------

    async def reload_plugin(self, name: str) -> bool:
        """Reload *name* from disk.

        Returns ``True`` on success, ``False`` if the plugin was not
        loaded.
        """
        if name not in self.plugins:
            return False

        # Remove existing entry
        old = self.plugins.pop(name)
        self.loaded_modules.pop(name, None)

        # Find the original directory and reload
        # Note: name comparison happens after loading from each candidate
        # directory; first successful match wins.
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            plugin_file = plugin_dir / "plugin.py"
            if plugin_file.exists():
                # Check if this directory matches the plugin name
                # by trying to load and comparing names
                try:
                    await self._load_plugin(plugin_dir, plugin_file)
                    if name in self.plugins:
                        logger.info("Reloaded plugin: %s", name)
                        return True
                except Exception:
                    logger.exception(
                        "Failed to reload plugin: %s", name
                    )
                    # Restore the old one
                    self.plugins[name] = old
                    return False

        logger.warning(
            "Could not find source for plugin: %s", name
        )
        self.plugins[name] = old
        return False

    def unload_plugin(self, name: str) -> bool:
        """Unload *name* from memory.

        Returns ``True`` on success.
        """
        if name not in self.plugins:
            return False
        plugin = self.plugins.pop(name)
        self.loaded_modules.pop(name, None)
        core_plugin.get_registry().unregister(name)
        logger.info("Unloaded plugin: %s", name)
        return True

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """Get a loaded plugin by name.

        Args:
            name: Plugin name.

        Returns:
            Plugin instance or *None*.
        """
        return self.plugins.get(name)

    def list_plugins(self) -> List[str]:
        """List all loaded plugin names."""
        return list(self.plugins.keys())

    def get_all_tools(self) -> Dict[str, Any]:
        """Get all tools from all enabled plugins.

        Returns:
            Dict of ``tool_name → PluginTool``.
        """
        all_tools: Dict[str, Any] = {}
        for plugin in self.plugins.values():
            if plugin.is_enabled():
                all_tools.update(plugin.tools)
        return all_tools

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown_all(
        self, timeout: float = 10.0
    ) -> List[Exception]:
        """Shutdown all loaded plugins concurrently.

        Args:
            timeout: Maximum seconds to wait for each plugin's
                :meth:`BasePlugin.on_shutdown`.

        Returns:
            List of exceptions that occurred during shutdown (empty on
            success).
        """
        errors: List[Exception] = []

        async def _shutdown_one(plugin: BasePlugin) -> Optional[Exception]:
            try:
                await asyncio.wait_for(
                    plugin.on_shutdown(), timeout=timeout
                )
                logger.info("Shutdown plugin: %s", plugin.name)
                return None
            except asyncio.TimeoutError:
                msg = (
                    f"Plugin '{plugin.name}' on_shutdown timed out "
                    f"after {timeout}s"
                )
                logger.error(msg)
                return TimeoutError(msg)
            except Exception as e:
                logger.error(
                    "Error shutting down %s: %s", plugin.name, e
                )
                return e

        results = await asyncio.gather(
            *(_shutdown_one(p) for p in list(self.plugins.values())),
            return_exceptions=True,
        )
        errors = [r for r in results if r is not None]
        return errors

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------

    async def enable_plugin(self, name: str) -> bool:
        """Enable a plugin and notify it via :meth:`BasePlugin.on_enable`.

        Returns:
            ``True`` if the plugin was found and enabled.
        """
        plugin = self.get_plugin(name)
        if not plugin:
            return False
        plugin.enable()
        await plugin.on_enable()
        return True

    async def disable_plugin(self, name: str) -> bool:
        """Disable a plugin and notify it via :meth:`BasePlugin.on_disable`.

        Returns:
            ``True`` if the plugin was found and disabled.
        """
        plugin = self.get_plugin(name)
        if not plugin:
            return False
        plugin.disable()
        await plugin.on_disable()
        return True

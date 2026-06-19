"""
Base plugin class for Amalgam framework.

Plugins are discoverable extensions that can:
- Hook into character lifecycle events
- Provide custom tools to the LLM
- Process and transform conversation context
- Integrate external services (APIs, webhooks, etc.)
- Extend VRM animations and behaviors
"""

import asyncio
import logging
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from backend.core.plugin import Plugin

logger = logging.getLogger(__name__)

__all__ = [
    "PluginMetadata",
    "PluginTool",
    "BasePlugin",
]


@dataclass
class PluginMetadata:
    """Metadata about a plugin."""

    name: str
    version: str
    author: str
    description: str
    requires: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class PluginTool:
    """Wrapper for a tool provided by a plugin."""

    def __init__(
        self,
        name: str,
        description: str,
        func: Callable,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters or {}

    async def __call__(self, *args, **kwargs):
        """Execute the tool, wrapping sync callables transparently."""
        if asyncio.iscoroutinefunction(self.func):
            return await self.func(*args, **kwargs)
        # Wrap sync function in a thread executor to avoid blocking
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.func(*args, **kwargs)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for LLM context."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


# Exceptions that should *always* propagate through hook dispatch
_SYSTEM_EXITS = (KeyboardInterrupt, SystemExit, GeneratorExit)


class BasePlugin(Plugin, ABC):
    """Base class for all plugins.

    Extends :class:`~backend.core.plugin.Plugin` with a richer tool
    system, event-based hook registration, enable/disable lifecycle,
    and the ability to accept configuration on instantiation.
    """

    def __init__(
        self,
        metadata: PluginMetadata,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize plugin.

        Args:
            metadata: Plugin metadata (name, version, …).
            config: Optional configuration dict passed by the manager.
        """
        # Name is derived from metadata, so set it before super().__init__
        self._metadata = metadata
        super().__init__()
        self._config = config or {}
        self._tools: Dict[str, PluginTool] = {}
        self._hooks: Dict[str, List[Callable]] = {}
        logger.info(
            "Initialized plugin: %s v%s", metadata.name, metadata.version
        )

    # ---- name override ---------------------------------------------------
    @property
    def name(self) -> str:
        return self.metadata.name

    @name.setter
    def name(self, value: str) -> None:
        pass  # suppress the empty-name check in Plugin.__init__

    @property
    def metadata(self) -> PluginMetadata:
        return self._metadata

    # ---- configuration ---------------------------------------------------

    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    # ---- tools -----------------------------------------------------------

    @property
    def tools(self) -> Dict[str, PluginTool]:
        """Get tools provided by this plugin."""
        return self._tools

    def register_tool(self, tool: PluginTool) -> None:
        """Register a tool provided by this plugin.

        Args:
            tool: Tool to register.
        """
        self._tools[tool.name] = tool
        logger.debug(
            "Registered tool '%s' from plugin %s", tool.name, self.name
        )

    # ---- event hooks -----------------------------------------------------

    def register_hook(self, event: str, handler: Callable) -> None:
        """Register a hook handler for an event.

        Args:
            event: Event name (e.g. ``'before_response'``,
                ``'after_memory_save'``).
            handler: Async or sync callable to handle the event.
        """
        self._hooks.setdefault(event, []).append(handler)
        logger.debug(
            "Registered hook '%s' in plugin %s", event, self.name
        )

    async def trigger_hooks(self, event: str, *args, **kwargs) -> None:
        """Trigger all handlers registered for *event*.

        System-exiting exceptions (``KeyboardInterrupt``, ``SystemExit``,
        ``GeneratorExit``) always propagate. Other exceptions are logged
        and suppressed so one failing handler does not block the others.

        Args:
            event: Event name.
            *args: Arguments forwarded to every handler.
            **kwargs: Keyword arguments forwarded to every handler.
        """
        handlers = self._hooks.get(event)
        if not handlers:
            return

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(*args, **kwargs)
                else:
                    handler(*args, **kwargs)
            except _SYSTEM_EXITS:
                raise
            except Exception as e:
                logger.error(
                    "Error in hook '%s' from %s: %s",
                    event,
                    self.name,
                    e,
                )

    # ---- lifecycle (called by PluginManager) -----------------------------

    async def on_initialize(self) -> None:
        """Called when the plugin is initialized.

        Override to perform async setup (e.g. download models,
        connect to external services).
        """
        pass

    async def on_shutdown(self) -> None:
        """Called when the plugin is shutting down.

        Override to perform cleanup.
        """
        pass

    async def on_enable(self) -> None:
        """Called when the plugin is enabled."""
        pass

    async def on_disable(self) -> None:
        """Called when the plugin is disabled."""
        pass

    async def initialize(self) -> None:
        """Initialize the plugin (backward-compatible entry point).

        The default implementation calls :meth:`on_initialize`.
        Subclasses may override but **must** call ``await super().initialize()``
        if they want :meth:`on_initialize` to still fire.
        """
        await self.on_initialize()

    # ---- character / context hooks (convenience) -------------------------

    async def on_character_loaded(self, character: Any) -> None:
        """Called when a character is loaded.

        Args:
            character: Character object.
        """
        pass

    async def on_before_response(
        self, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Hook before LLM response generation.

        Args:
            context: Conversation context.

        Returns:
            Modified context.
        """
        return context

    async def on_after_response(self, response: str) -> str:
        """Hook after LLM response generation.

        Args:
            response: Generated response.

        Returns:
            Modified response.
        """
        return response

    async def on_memory_save(
        self, memory_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Hook when saving memory.

        Args:
            memory_data: Data being saved.

        Returns:
            Modified memory data.
        """
        return memory_data

    # ---- enable / disable -------------------------------------------------

    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        """Enable the plugin."""
        self._enabled = True
        logger.info("Enabled plugin: %s", self.name)

    def disable(self) -> None:
        """Disable the plugin."""
        self._enabled = False
        logger.info("Disabled plugin: %s", self.name)

"""Core module — shared dependencies and plugin system."""

from backend.core.plugin import (
    Plugin,
    PluginRegistry,
    discover_plugins,
    get_registry,
    register,
    reset_registry,
)

__all__ = [
    "Plugin",
    "PluginRegistry",
    "discover_plugins",
    "get_registry",
    "register",
    "reset_registry",
]

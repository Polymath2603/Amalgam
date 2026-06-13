"""
Plugin system for Amalgam.

Enables extending functionality through discoverable plugins.
"""

from .base import BasePlugin, PluginMetadata, PluginTool
from .manager import PluginManager

__all__ = [
    'BasePlugin',
    'PluginMetadata',
    'PluginTool',
    'PluginManager',
]

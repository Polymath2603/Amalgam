"""
Plugin manager - discovers, loads, and manages plugins.
"""

import importlib.util
import logging
from pathlib import Path
from typing import Dict, List, Optional, Type
from .base import BasePlugin, PluginMetadata

logger = logging.getLogger(__name__)


class PluginManager:
    """Manages plugin lifecycle and discovery."""
    
    def __init__(self, plugins_dir: Optional[Path] = None):
        """Initialize plugin manager.
        
        Args:
            plugins_dir: Directory to search for plugins
        """
        self.plugins_dir = plugins_dir or Path(__file__).parent
        self.plugins: Dict[str, BasePlugin] = {}
        self.loaded_modules: Dict[str, any] = {}
    
    async def discover_and_load(self):
        """Discover and load all plugins from plugins directory.
        
        Plugins should be directories with a plugin.py file containing
        a PluginClass that extends BasePlugin.
        """
        if not self.plugins_dir.is_dir():
            logger.warning(f"Plugins directory not found: {self.plugins_dir}")
            return
        
        # Search for plugin directories
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir() or plugin_dir.name.startswith('_'):
                continue
            
            plugin_file = plugin_dir / "plugin.py"
            if plugin_file.exists():
                await self._load_plugin(plugin_dir, plugin_file)
    
    async def _load_plugin(self, plugin_dir: Path, plugin_file: Path):
        """Load a single plugin.
        
        Args:
            plugin_dir: Directory containing the plugin
            plugin_file: plugin.py file path
        """
        try:
            # Import the plugin module
            spec = importlib.util.spec_from_file_location(
                f"plugins.{plugin_dir.name}",
                plugin_file
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Look for PluginClass
            if not hasattr(module, 'PluginClass'):
                logger.warning(
                    f"Plugin {plugin_dir.name} has no PluginClass defined"
                )
                return
            
            plugin_class: Type[BasePlugin] = module.PluginClass
            
            # Instantiate and initialize
            plugin_instance = plugin_class()
            await plugin_instance.initialize()
            
            self.plugins[plugin_instance.name] = plugin_instance
            self.loaded_modules[plugin_instance.name] = module
            
            logger.info(f"Loaded plugin: {plugin_instance.name}")
        
        except Exception as e:
            logger.error(f"Failed to load plugin from {plugin_file}: {e}")
    
    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """Get a loaded plugin by name.
        
        Args:
            name: Plugin name
            
        Returns:
            Plugin instance or None
        """
        return self.plugins.get(name)
    
    def list_plugins(self) -> List[str]:
        """List all loaded plugins.
        
        Returns:
            List of plugin names
        """
        return list(self.plugins.keys())
    
    def get_all_tools(self) -> Dict[str, any]:
        """Get all tools from all enabled plugins.
        
        Returns:
            Dict of tool_name -> PluginTool
        """
        all_tools = {}
        for plugin in self.plugins.values():
            if plugin.is_enabled():
                all_tools.update(plugin.tools)
        return all_tools
    
    async def shutdown_all(self):
        """Shutdown all loaded plugins."""
        for plugin in self.plugins.values():
            try:
                await plugin.on_shutdown()
                logger.info(f"Shutdown plugin: {plugin.name}")
            except Exception as e:
                logger.error(f"Error shutting down {plugin.name}: {e}")
    
    def enable_plugin(self, name: str) -> bool:
        """Enable a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            Success status
        """
        plugin = self.get_plugin(name)
        if plugin:
            plugin.enable()
            return True
        return False
    
    def disable_plugin(self, name: str) -> bool:
        """Disable a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            Success status
        """
        plugin = self.get_plugin(name)
        if plugin:
            plugin.disable()
            return True
        return False

"""
Base plugin class for Amalgam framework.

Plugins are discoverable extensions that can:
- Hook into character lifecycle events
- Provide custom tools to the LLM
- Process and transform conversation context
- Integrate external services (APIs, webhooks, etc.)
- Extend VRM animations and behaviors
"""

from abc import ABC
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class PluginMetadata:
    """Metadata about a plugin."""
    name: str
    version: str
    author: str
    description: str
    requires: List[str] = None  # Required dependencies
    tags: List[str] = None  # Plugin categories
    
    def __post_init__(self):
        if self.requires is None:
            self.requires = []
        if self.tags is None:
            self.tags = []


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
        """Execute the tool."""
        return await self.func(*args, **kwargs)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for LLM context."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class BasePlugin(ABC):
    """Base class for all plugins."""
    
    def __init__(self, metadata: PluginMetadata):
        """Initialize plugin.
        
        Args:
            metadata: Plugin metadata
        """
        self.metadata = metadata
        self.enabled = True
        self._tools: Dict[str, PluginTool] = {}
        self._hooks: Dict[str, List[Callable]] = {}
        logger.info(f"Initialized plugin: {metadata.name} v{metadata.version}")
    
    @property
    def name(self) -> str:
        """Get plugin name."""
        return self.metadata.name
    
    @property
    def tools(self) -> Dict[str, PluginTool]:
        """Get tools provided by this plugin."""
        return self._tools
    
    def register_tool(self, tool: PluginTool):
        """Register a tool provided by this plugin.
        
        Args:
            tool: Tool to register
        """
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool '{tool.name}' from plugin {self.name}")
    
    def register_hook(self, event: str, handler: Callable):
        """Register a hook handler for an event.
        
        Args:
            event: Event name (e.g., 'before_response', 'after_memory_save')
            handler: Async callable to handle the event
        """
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(handler)
        logger.debug(f"Registered hook '{event}' in plugin {self.name}")
    
    async def trigger_hooks(self, event: str, *args, **kwargs):
        """Trigger all hooks for an event.
        
        Args:
            event: Event name
            *args: Arguments to pass to handlers
            **kwargs: Keyword arguments to pass to handlers
        """
        if event not in self._hooks:
            return
        
        for handler in self._hooks[event]:
            try:
                await handler(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in hook '{event}' from {self.name}: {e}")
    
    async def on_initialize(self):
        """Called when the plugin is initialized.
        
        Override to perform async setup.
        """
        pass
    
    async def on_shutdown(self):
        """Called when the plugin is shutting down.
        
        Override to perform cleanup.
        """
        pass
    
    async def on_character_loaded(self, character):
        """Called when a character is loaded.
        
        Args:
            character: Character object
        """
        pass
    
    async def on_before_response(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Hook before LLM response generation.
        
        Args:
            context: Conversation context
            
        Returns:
            Modified context
        """
        return context
    
    async def on_after_response(self, response: str) -> str:
        """Hook after LLM response generation.
        
        Args:
            response: Generated response
            
        Returns:
            Modified response
        """
        return response
    
    async def on_memory_save(self, memory_data: Dict[str, Any]) -> Dict[str, Any]:
        """Hook when saving memory.
        
        Args:
            memory_data: Data being saved
            
        Returns:
            Modified memory data
        """
        return memory_data
    
    async def initialize(self):
        """Initialize the plugin.
        
        Override in subclasses to perform setup.
        """
        pass
    
    def is_enabled(self) -> bool:
        """Check if plugin is enabled."""
        return self.enabled
    
    def enable(self):
        """Enable the plugin."""
        self.enabled = True
        logger.info(f"Enabled plugin: {self.name}")
    
    def disable(self):
        """Disable the plugin."""
        self.enabled = False
        logger.info(f"Disabled plugin: {self.name}")

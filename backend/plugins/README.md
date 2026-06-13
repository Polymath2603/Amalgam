# Plugin System

The Amalgam plugin system enables extending functionality through discoverable, modular plugins.

## Architecture

### BasePlugin
Core abstraction that all plugins inherit from. Provides:

- **Tools**: Custom functions available to the LLM
- **Hooks**: Event handlers for lifecycle events
- **Lifecycle methods**: `on_initialize()`, `on_shutdown()`, etc.

### PluginManager
Discovers and manages plugins from the plugins directory.

Features:
- Auto-discovery of plugin directories
- Plugin lifecycle management
- Tool aggregation from all enabled plugins
- Enable/disable plugins at runtime

## Creating a Plugin

### 1. Create Plugin Directory

```
backend/plugins/my_plugin/
├── __init__.py
└── plugin.py
```

### 2. Implement Plugin Class

```python
from backend.plugins.base import BasePlugin, PluginMetadata, PluginTool

class MyPlugin(BasePlugin):
    def __init__(self):
        metadata = PluginMetadata(
            name="my_plugin",
            version="1.0.0",
            author="Your Name",
            description="What my plugin does",
        )
        super().__init__(metadata)
    
    async def initialize(self):
        """Setup plugin - download models, etc."""
        # Register tools
        tool = PluginTool(
            name="my_tool",
            description="What the tool does",
            func=self.my_tool_func,
        )
        self.register_tool(tool)
    
    async def my_tool_func(self, arg1: str) -> str:
        return f"Result: {arg1}"
    
    async def on_before_response(self, context):
        """Modify context before LLM response."""
        return context
    
    async def on_after_response(self, response: str) -> str:
        """Modify response after LLM generation."""
        return response

# REQUIRED: Entry point for plugin system
PluginClass = MyPlugin
```

### 3. Required Structure

Every plugin must have:
- `__init__.py` - Empty or imports from plugin.py
- `plugin.py` - Contains PluginClass definition
- PluginClass must inherit from BasePlugin
- PluginClass must be assigned at module level: `PluginClass = MyPlugin`

## Plugin Hooks

Available lifecycle hooks:

### Character Hooks
- `on_character_loaded(character)` - When character is loaded

### Response Hooks
- `on_before_response(context)` - Before LLM generation
- `on_after_response(response)` - After LLM generation

### Memory Hooks
- `on_memory_save(memory_data)` - When saving to memory

### Lifecycle
- `on_initialize()` - Plugin startup
- `on_shutdown()` - Plugin shutdown

## Plugin Tools

Tools are exposed to the LLM and can be called during reasoning.

```python
tool = PluginTool(
    name="search_web",
    description="Search the web for information",
    func=self.search_web,
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query"
            }
        },
        "required": ["query"]
    }
)
self.register_tool(tool)
```

## Using the Plugin System

```python
from backend.plugins import PluginManager

# Create manager
manager = PluginManager()

# Discover and load plugins
await manager.discover_and_load()

# Get all tools
all_tools = manager.get_all_tools()

# Disable a plugin at runtime
manager.disable_plugin("my_plugin")

# Shutdown all plugins
await manager.shutdown_all()
```

## Example Plugins

### Emotion Analyzer
- **Location**: `backend/plugins/emotion_analyzer/`
- **Features**: Text emotion analysis using VADER sentiment
- **Tools**: `analyze_emotion(text)`
- **Hooks**: Injects user emotion into conversation context

## Plugin Discovery

The plugin manager searches the `backend/plugins/` directory for:
1. Subdirectories (skip those starting with `_`)
2. `plugin.py` file in each directory
3. `PluginClass` definition in the module

Plugins are loaded in directory order.

## Best Practices

1. **Minimal Dependencies**: Lazy import heavy libraries
2. **Error Handling**: Catch exceptions in hooks to prevent cascading failures
3. **Logging**: Use standard logging module
4. **Async/Await**: All lifecycle methods are async
5. **Documentation**: Include docstrings for tools and hooks
6. **Testing**: Test plugins in isolation before integrating

## Plugin Metadata

```python
PluginMetadata(
    name="unique_name",           # Snake case
    version="1.0.0",             # Semantic versioning
    author="Your Name",          # Author info
    description="What it does",  # Short description
    requires=["dependency1"],    # Optional: list of required plugins/libs
    tags=["category"],           # Optional: plugin categories
)
```

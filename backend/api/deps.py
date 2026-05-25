"""
API-layer dependency injection.
Re-exports shared singletons from backend.deps for web-specific modules.
"""
from k_core .deps import (
settings ,llm ,memory ,context_builder ,context_manager ,
vault ,mcp ,tts ,agent ,relationship ,get_shared 
)

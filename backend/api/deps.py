"""
API-layer dependency injection.
Re-exports shared singletons from backend.deps for web-specific modules.
"""
from backend.core .deps import (
settings ,llm ,memory ,context_builder ,context_manager ,
vault ,mcp ,tts ,agent ,relationship ,wakeword ,get_shared ,orchestrator 
)

"""
LLM Router — delegates to per-provider modules in backend/core/llm/.
Kept as a thin wrapper for backward compatibility.
"""
from backend .core .llm import LLMRouter 

__all__ =["LLMRouter"]

"""
Context budget management - proportional token allocation across context sections.

Allocates the available context window across different sections (system prompt, tools, 
memory, history, etc.) based on intent and model capabilities.
"""

from typing import Dict, Literal
from dataclasses import dataclass


@dataclass
class ContextBudget:
    """Token budget allocation for a single context section."""
    section: str
    tokens: int
    priority: float = 1.0
    
    def __repr__(self) -> str:
        return f"{self.section}({self.tokens}tk)"


class BudgetManager:
    """Manages proportional token budget allocation across context sections."""
    
    # Intent-specific allocation patterns
    INTENT_BUDGETS = {
        'conversation': {
            'system_core': 0.15,
            'vault_rules': 0.05,
            'tool_schema': 0.10,
            'memory_summary': 0.10,
            'memory_retrieved': 0.10,
            'relationship': 0.05,
            'history': 0.40,
            'user_msg': 0.05,
        },
        'tool_execution': {
            'system_core': 0.15,
            'vault_rules': 0.00,
            'tool_schema': 0.35,  # More space for tool definitions
            'memory_summary': 0.05,
            'memory_retrieved': 0.05,
            'relationship': 0.05,
            'history': 0.30,
            'user_msg': 0.05,
        },
        'memory_op': {
            'system_core': 0.10,
            'vault_rules': 0.02,
            'tool_schema': 0.05,
            'memory_summary': 0.25,  # More space for memory context
            'memory_retrieved': 0.25,
            'relationship': 0.05,
            'history': 0.25,
            'user_msg': 0.03,
        },
        'reflection': {
            'system_core': 0.15,
            'vault_rules': 0.02,
            'tool_schema': 0.05,
            'memory_summary': 0.10,
            'memory_retrieved': 0.10,
            'relationship': 0.10,
            'history': 0.45,  # More history for reflection
            'user_msg': 0.03,
        },
        'code': {
            'system_core': 0.20,
            'vault_rules': 0.00,
            'tool_schema': 0.20,
            'memory_summary': 0.05,
            'memory_retrieved': 0.05,
            'relationship': 0.02,
            'history': 0.45,  # Lots of history for code context
            'user_msg': 0.03,
        },
    }
    
    def __init__(self, context_limit: int = 8192, output_reserve: int = 2048):
        """Initialize budget manager.
        
        Args:
            context_limit: Total context window size
            output_reserve: Tokens reserved for model output
        """
        self.context_limit = context_limit
        self.output_reserve = output_reserve
        self.available = context_limit - output_reserve - 50  # 50 token safety margin
    
    def allocate(self, intent: str = 'conversation') -> Dict[str, ContextBudget]:
        """Allocate budget for all sections based on intent.
        
        Args:
            intent: One of 'conversation', 'tool_execution', 'memory_op', 'reflection', 'code'
            
        Returns:
            Dict mapping section name to ContextBudget
        """
        intent = intent.lower()
        if intent not in self.INTENT_BUDGETS:
            intent = 'conversation'
        
        pattern = self.INTENT_BUDGETS[intent]
        budgets = {}
        
        for section, proportion in pattern.items():
            tokens = int(self.available * proportion)
            budgets[section] = ContextBudget(
                section=section,
                tokens=max(tokens, 10),  # Minimum 10 tokens per section
                priority=proportion
            )
        
        return budgets
    
    def allocate_with_overrides(
        self, 
        intent: str = 'conversation',
        overrides: Dict[str, int] = None
    ) -> Dict[str, ContextBudget]:
        """Allocate budget with section-specific overrides.
        
        Args:
            intent: Intent type
            overrides: Dict of {section: token_count} to override defaults
            
        Returns:
            Dict of allocation with overrides applied
        """
        budgets = self.allocate(intent)
        
        if overrides:
            for section, tokens in overrides.items():
                if section in budgets:
                    budgets[section].tokens = min(tokens, self.available // 2)
        
        return budgets


def estimate_tokens(text: str, model: str = 'gpt-3.5') -> int:
    """Rough token estimation for different models.
    
    Uses simple character-to-token heuristics. For production, use
    actual tokenizer (tiktoken, transformers, etc).
    
    Args:
        text: Text to estimate
        model: Model family (gpt-3.5, gpt-4, claude, gemini)
        
    Returns:
        Estimated token count
    """
    # Rough approximation: 4 chars per token on average
    chars = len(text.strip())
    base_tokens = chars // 4
    
    # Model-specific adjustments
    if 'gpt-4' in model.lower():
        return int(base_tokens * 1.1)  # GPT-4 uses slightly more tokens
    elif 'claude' in model.lower():
        return int(base_tokens * 1.15)  # Claude tokenizer is different
    elif 'gemini' in model.lower():
        return int(base_tokens * 0.95)  # Gemini is slightly more efficient
    
    return base_tokens

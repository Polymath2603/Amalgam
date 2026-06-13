"""
Context builder - assembles the complete prompt context from components.

Uses Jinja2 templates to build system prompt with character personality,
rules, vault context, tools, and memory, respecting token budgets.
"""

from typing import Dict, List, Optional, Any
from jinja2 import Environment, PackageLoader, select_autoescape
from pathlib import Path
import logging

from .budgets import BudgetManager, estimate_tokens
from .vault_injector import VaultInjector

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds complete prompt context using Jinja2 templates."""
    
    def __init__(self, templates_dir: Optional[str] = None):
        """Initialize context builder.
        
        Args:
            templates_dir: Path to Jinja2 templates directory
        """
        if templates_dir:
            self.env = Environment(
                loader=PackageLoader('backend.core.context', templates_dir),
                autoescape=select_autoescape()
            )
        else:
            # Use default templates from package
            try:
                self.env = Environment(
                    loader=PackageLoader('backend.core.context', 'templates'),
                    autoescape=select_autoescape()
                )
            except Exception:
                logger.warning("Template directory not found, using fallback")
                self.env = None
        
        self.budget_manager = BudgetManager()
        self.vault_injector = VaultInjector()
    
    def build_system_prompt(
        self,
        character: Dict[str, Any],
        intent: str = 'conversation',
        vault_context: Optional[str] = None,
        **kwargs
    ) -> str:
        """Build complete system prompt for the character.
        
        Args:
            character: Character definition dict
            intent: Intent type for budget allocation
            vault_context: Optional vault rules/context
            **kwargs: Additional template variables
            
        Returns:
            Complete system prompt
        """
        if not self.env:
            return self._build_system_prompt_fallback(character, vault_context)
        
        try:
            template = self.env.get_template('system_prompt.j2')
            
            context = {
                'character_name': character.get('name', 'Assistant'),
                'personality': character.get('personality', ''),
                'characteristics': character.get('characteristics', ''),
                'interaction_style': character.get('interaction_style', ''),
                'system_prompt': character.get('system_prompt', ''),
                'vault_context': vault_context or '',
                'vocabulary': character.get('vocabulary', []),
                'quirks': character.get('quirks', []),
                'forbidden': character.get('forbidden', []),
                **kwargs
            }
            
            return template.render(context)
        
        except Exception as e:
            logger.warning(f"Template rendering failed: {e}, using fallback")
            return self._build_system_prompt_fallback(character, vault_context)
    
    def _build_system_prompt_fallback(
        self,
        character: Dict[str, Any],
        vault_context: Optional[str] = None
    ) -> str:
        """Fallback system prompt builder without templates.
        
        Args:
            character: Character definition
            vault_context: Optional vault context
            
        Returns:
            System prompt
        """
        base = character.get('system_prompt', 'You are a helpful assistant.')
        
        if vault_context:
            base += f"\n\n## Rules\n{vault_context}"
        
        personality = character.get('personality', '')
        if personality:
            base += f"\n\nPersonality: {personality}"
        
        characteristics = character.get('characteristics', '')
        if characteristics:
            base += f"\nCharacteristics: {characteristics}"
        
        return base.strip()
    
    def build_tool_section(
        self,
        tools: List[Dict[str, Any]],
        intent: str = 'conversation',
        **kwargs
    ) -> str:
        """Build tool definitions section.
        
        Args:
            tools: List of tool definitions
            intent: Intent type
            **kwargs: Additional template variables
            
        Returns:
            Tool definitions section
        """
        if not self.env or not tools:
            return self._build_tool_section_fallback(tools)
        
        try:
            template = self.env.get_template('tool_section.j2')
            return template.render(tools=tools, intent=intent, **kwargs)
        except Exception as e:
            logger.warning(f"Tool template rendering failed: {e}, using fallback")
            return self._build_tool_section_fallback(tools)
    
    def _build_tool_section_fallback(self, tools: List[Dict[str, Any]]) -> str:
        """Fallback tool section builder.
        
        Args:
            tools: List of tool definitions
            
        Returns:
            Tool definitions text
        """
        if not tools:
            return ""
        
        lines = ["## Available Tools\n"]
        for tool in tools:
            name = tool.get('name', 'unknown')
            desc = tool.get('description', '')
            lines.append(f"- **{name}**: {desc}")
        
        return '\n'.join(lines)
    
    def allocate_budgets(self, intent: str = 'conversation') -> Dict[str, int]:
        """Get token budget allocation for intent.
        
        Args:
            intent: Intent type
            
        Returns:
            Dict of section -> token count
        """
        budgets = self.budget_manager.allocate(intent)
        return {section: budget.tokens for section, budget in budgets.items()}
    
    def truncate_to_budget(self, text: str, max_tokens: int, model: str = 'gpt-3.5') -> str:
        """Truncate text to fit within token budget.
        
        Args:
            text: Text to truncate
            max_tokens: Maximum tokens allowed
            model: Model family for token estimation
            
        Returns:
            Truncated text
        """
        estimated = estimate_tokens(text, model)
        
        if estimated <= max_tokens:
            return text
        
        # Simple truncation by ratio
        max_chars = int(len(text) * (max_tokens / estimated))
        return text[:max_chars].rsplit(' ', 1)[0] + "..."

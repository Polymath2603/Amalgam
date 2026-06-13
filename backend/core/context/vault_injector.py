"""
Vault rules injection - extracts and injects character rules and context from vault.

Integrates with the vault system to pull relevant rules, constraints, and contextual
information for the current character and session.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class VaultInjector:
    """Injects vault rules and context into the system prompt."""
    
    def __init__(self, vault_path: Optional[str] = None):
        """Initialize vault injector.
        
        Args:
            vault_path: Path to vault directory (markdown notes)
        """
        self.vault_path = Path(vault_path) if vault_path else None
    
    def extract_rules(self, vault_dir: Optional[Path] = None) -> str:
        """Extract behavior rules from vault/rules.md if it exists.
        
        Args:
            vault_dir: Vault directory path
            
        Returns:
            Rules text (empty string if not found)
        """
        vault_dir = vault_dir or self.vault_path
        if not vault_dir:
            return ""
        
        rules_file = vault_dir / "rules.md"
        if rules_file.exists():
            try:
                content = rules_file.read_text()
                # Extract content after first H1 heading
                lines = content.split('\n')
                start_idx = next((i for i, line in enumerate(lines) if line.startswith('# ')), 0)
                return '\n'.join(lines[start_idx+1:]).strip()
            except Exception as e:
                logger.warning(f"Failed to read vault rules: {e}")
                return ""
        
        return ""
    
    def extract_character_context(
        self,
        character_name: str,
        vault_dir: Optional[Path] = None
    ) -> str:
        """Extract character-specific context from vault.
        
        Looks for character-named files or sections in vault.
        
        Args:
            character_name: Name of the character
            vault_dir: Vault directory path
            
        Returns:
            Character context text (empty if not found)
        """
        vault_dir = vault_dir or self.vault_path
        if not vault_dir:
            return ""
        
        # Look for character-specific file
        char_file = vault_dir / f"{character_name.lower().replace(' ', '_')}.md"
        if char_file.exists():
            try:
                return char_file.read_text().strip()
            except Exception as e:
                logger.warning(f"Failed to read character context: {e}")
        
        return ""
    
    def inject_into_prompt(
        self,
        base_prompt: str,
        rules: Optional[str] = None,
        char_context: Optional[str] = None,
        injection_point: str = "CHARACTER_RULES"
    ) -> str:
        """Inject vault content into system prompt.
        
        Args:
            base_prompt: Base system prompt template
            rules: Rules to inject
            char_context: Character context to inject
            injection_point: Placeholder in prompt to inject at
            
        Returns:
            Prompt with injected content
        """
        prompt = base_prompt
        
        if injection_point in prompt:
            injected = []
            if rules:
                injected.append(f"## Rules\n{rules}")
            if char_context:
                injected.append(f"## Character Context\n{char_context}")
            
            if injected:
                injection_text = "\n\n".join(injected)
                prompt = prompt.replace(injection_point, injection_text)
            else:
                prompt = prompt.replace(injection_point, "")
        
        return prompt.strip()
    
    def prepare_rules_section(
        self,
        character_name: str,
        vault_dir: Optional[Path] = None,
        max_tokens: int = 200
    ) -> str:
        """Prepare a rules section for context injection.
        
        Args:
            character_name: Character name
            vault_dir: Vault directory
            max_tokens: Maximum tokens for rules section (rough estimate)
            
        Returns:
            Rules section text
        """
        rules = self.extract_rules(vault_dir)
        char_context = self.extract_character_context(character_name, vault_dir)
        
        # Combine and truncate if needed
        combined = f"{rules}\n{char_context}".strip()
        
        if combined:
            # Rough token estimate: 4 chars per token
            max_chars = max_tokens * 4
            if len(combined) > max_chars:
                combined = combined[:max_chars] + "..."
        
        return combined

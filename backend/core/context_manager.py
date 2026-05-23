"""
Token-budget-aware context selection.
Prioritizes content for inclusion in the LLM context window:
summary > relevant facts > relationship > recent history > vault content.
"""
import logging 
from typing import List ,Dict ,Optional 

from backend .utils .tokens import estimate_tokens ,estimate_message_list_tokens ,select_messages_within_budget ,truncate_to_token_limit 

logger =logging .getLogger (__name__ )


SYSTEM_PROMPT_OVERHEAD =50 
TURN_OVERHEAD =8 


class ContextManager :
    def __init__ (self ,settings =None ):
        self .settings =settings 

    def _get_token_budget (self )->int :
        """Get the total context token budget from settings, with default."""
        if self .settings :
            return self .settings .get ("llm.context_token_limit",8192 )
        return 8192 

    def _get_max_tokens (self )->int :
        """Get the per-response max_tokens from settings."""
        if self .settings :
            return self .settings .get ("llm.max_tokens",2048 )
        return 2048 

    def estimate_system_prompt (self ,system_prompt :str )->int :
        """Estimate the token cost of the full system prompt."""
        return estimate_tokens (system_prompt )+SYSTEM_PROMPT_OVERHEAD 

    def build_context (
    self ,
    system_prompt :str ,
    history :List [Dict ],
    summary :str ="",
    relevant :List [Dict ]=None ,
    vault_content :str ="",
    relationship_context :str ="",
    user_message :str ="",
    model :Optional [str ]=None ,
    )->dict :
        """Build a context payload that fits within the token budget.
        
        Priority order (highest to lowest):
        1. System prompt (mandatory)
        2. Summary (previous session)
        3. Relevant past messages (semantic)
        4. Relationship context
        5. Recent message history
        6. Vault content
        7. Current user message (mandatory)
        
        Returns dict with:
          - system_prompt: str (may be truncated)
          - history: list of messages (filtered to fit)
          - summary: str (may be truncated)
          - vault_content: str (may be truncated)
          - budget_used: int
          - budget_total: int
          - truncated: list of what was cut
        """
        budget =self ._get_token_budget ()
        truncated =[]


        user_msg_tokens =estimate_tokens (user_message ,model )+TURN_OVERHEAD 
        max_response =self ._get_max_tokens ()
        reserved =user_msg_tokens +max_response +50 

        available =budget -reserved 


        sys_tokens =estimate_tokens (system_prompt ,model )+SYSTEM_PROMPT_OVERHEAD 
        if sys_tokens >available :
            system_prompt =truncate_to_token_limit (system_prompt ,available -SYSTEM_PROMPT_OVERHEAD ,model )
            sys_tokens =estimate_tokens (system_prompt ,model )+SYSTEM_PROMPT_OVERHEAD 
            truncated .append ("system_prompt")
        available -=sys_tokens 


        summary_tokens =0 
        if summary :
            summary_tokens =estimate_tokens (summary ,model )
            if summary_tokens >available :
                summary =truncate_to_token_limit (summary ,available ,model )
                summary_tokens =estimate_tokens (summary ,model )
                truncated .append ("summary")
            available -=summary_tokens 


        relevant_tokens =0 
        if relevant :
            relevant_tokens =estimate_message_list_tokens (relevant ,model )
            if relevant_tokens >available :

                keep =[]
                for item in reversed (relevant ):
                    item_tokens =estimate_tokens (item .get ("content",""),model )+TURN_OVERHEAD 
                    if item_tokens <=available :
                        available -=item_tokens 
                        keep .insert (0 ,item )
                        relevant_tokens =sum (estimate_message_list_tokens (keep ,model ))
                    else :
                        truncated .append ("relevant_context")
                relevant =keep 
            else :
                available -=relevant_tokens 


        rel_tokens =0 
        if relationship_context :
            rel_tokens =estimate_tokens (relationship_context ,model )
            if rel_tokens >available :
                relationship_context =truncate_to_token_limit (relationship_context ,available ,model )
                rel_tokens =estimate_tokens (relationship_context ,model )
                truncated .append ("relationship_context")
            available -=rel_tokens 


        history_tokens =estimate_message_list_tokens (history ,model )
        if history_tokens >available :
            history =select_messages_within_budget (history ,available ,model )
            history_tokens =estimate_message_list_tokens (history ,model )
            truncated .append ("history")
        available -=history_tokens 


        vault_tokens =0 
        if vault_content :
            vault_tokens =estimate_tokens (vault_content ,model )
            if vault_tokens >available :
                vault_content =truncate_to_token_limit (vault_content ,available ,model )
                vault_tokens =estimate_tokens (vault_content ,model )
                truncated .append ("vault_content")
            available -=vault_tokens 

        budget_used =budget -available 

        if truncated :
            logger .debug (f"Context truncated: {', '.join (truncated )} (used {budget_used }/{budget })")

        return {
        "system_prompt":system_prompt ,
        "history":history ,
        "summary":summary ,
        "vault_content":vault_content ,
        "budget_used":budget_used ,
        "budget_total":budget ,
        "truncated":truncated ,
        }

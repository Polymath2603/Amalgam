"""
Context Builder — assembles the system prompt from character personality, additional instructions,
tools, and conversation context. The custom prompt is ADDITIVE, not an override.
"""
import os 
import logging 
from typing import List ,Dict 

logger =logging .getLogger (__name__ )


class ContextBuilder :
    def __init__ (self ,settings =None ):
        self .settings =settings 

    @property 
    def _characters (self )->Dict [str ,Dict ]:
        if self .settings :
            return self .settings .get_characters ()
        return {}

    def get_character (self ,character_id :str )->Dict :
        return self ._characters .get (character_id ,{})

    def list_characters (self )->Dict [str ,Dict ]:
        return self ._characters 

    def build (self ,tools :List [Dict ],history :List [Dict ],user_msg :str ,
    character_id :str =None ,additional_prompt :str ="",
    summary :str ="",relevant :List [Dict ]=None )->list :
        """Build the full message list. additional_prompt is ADDITIVE to the character's personality."""

        if not character_id and self .settings :
            character_id =self .settings .get ("character.active","amalgam")
        character =self ._characters .get (character_id ,{})


        sys_prompt =self ._build_character_prompt (character ,additional_prompt )


        if tools :
            sys_prompt +="\n\n## Available Tools\n"
            for t in tools :
                sys_prompt +=f"- **{t ['name']}**: {t ['description']}\n"
                if 'parameters'in t and t ['parameters'].get ('properties'):
                    params =t ['parameters']['properties']
                    param_strs =[f"{k } ({v .get ('type','string')})"for k ,v in params .items ()]
                    sys_prompt +=f"  Parameters: {', '.join (param_strs )}\n"
            sys_prompt +=('\nTo use a tool, respond EXACTLY with:\n'
            '```tool\n{"name": "tool_name", "arguments": {"param": "value"}}\n```\n')


        if summary :
            sys_prompt +=f"\n\n## Previous Conversation Summary\n{summary }\n"


        if relevant :
            sys_prompt +="\n\n## Relevant Past Context\n"
            for r in relevant :
                sys_prompt +=f"- {r ['role']}: {r ['content']}\n"


        messages =[{"role":"system","content":sys_prompt }]
        for h in history :
            messages .append ({"role":h ["role"],"content":h ["content"]})
        messages .append ({"role":"user","content":user_msg })

        return messages 

    def _build_character_prompt (self ,character :Dict ,additional_prompt :str ="")->str :
        """Build system prompt. Character personality is the base, additional_prompt is appended."""
        if not character :
            base ="You are a helpful AI assistant. Be concise and direct."
        else :
            name =character .get ("name","Assistant")
            system_prompt =character .get ("system_prompt","")
            personality =character .get ("personality","")
            characteristics =character .get ("characteristics","")
            interaction_style =character .get ("interaction_style","")
            vocabulary =character .get ("vocabulary",[])
            dialogue_examples =character .get ("dialogue_examples",[])

            base =system_prompt or f"You are {name }, a helpful AI assistant."

            if personality :
                base +=f"\n\nPersonality type: {personality }"
            if characteristics :
                base +=f"\nCharacteristics: {characteristics }"
            if interaction_style :
                base +=f"\nInteraction style: {interaction_style }"

            if vocabulary :
                base +="\n\n## Signature Phrases\n"
                for phrase in vocabulary :
                    base +=f"- \"{phrase }\"\n"

            if dialogue_examples :
                base +="\n\n## Dialogue Examples\n"
                for example in dialogue_examples :
                    base +=f"- \"{example }\"\n"


        if additional_prompt and additional_prompt .strip ():
            base +=f"\n\n## Additional Instructions\n{additional_prompt .strip ()}\n"


        vault_rules_path ="user_data/vault/rules.md"
        if os .path .exists (vault_rules_path ):
            try :
                with open (vault_rules_path ,"r")as f :
                    vault_rules =f .read ().strip ()
                if vault_rules and not vault_rules .startswith ("# Rules\n\nAdd your custom rules"):
                    base +=f"\n\n## Rules\n{vault_rules }\n"
            except Exception :
                pass 


        base +="\n\n## Emotion Expressions\nWhen expressing emotions, embed a tag like [happy], [sad], [angry], [surprised], [thinking], or [relaxed] in your response. Use them naturally — not every message needs one. Example: \"That's wonderful! [happy] I'd love to help.\"\n"

        return base 

    def build_from_messages (self ,messages :list ,new_user_msg :str )->list :
        messages .append ({"role":"user","content":new_user_msg })
        return messages 

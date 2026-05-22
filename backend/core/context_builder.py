import os 
import logging 
from typing import List ,Dict 

logger =logging .getLogger (__name__ )

PROJECT_ROOT =os .path .abspath (os .path .join (os .path .dirname (__file__ ),"..",".."))

VRM_EXPRESSIONS =["happy","angry","sad","relaxed","surprised","blink"]

EMOTION_TAGS =[
"happy","sad","angry","surprised","thinking","relaxed",
"confused","shy","jealous","bored","suspicious","victory",
"sleep","love","excited"
]


_PROMPT_TEMPLATE ="""\
# Identity
{identity}

# Environment
You exist inside a browser-based chat interface called Amalgam.
- Your responses are displayed as chat messages in a web UI
- The user is communicating with you via text or voice input
- You have a 3D VRM avatar that can show facial expressions and perform full-body animations
- Your voice is synthesized through TTS (text-to-speech) and can carry emotional tone
- You have access to a personal knowledge vault for persistent information
- Images sent by the user are visible to you
- You can use connected tools to interact with the local system

# Communication System
You can express yourself through three independent tag systems, layered on top of your speech.

## Voice Emotion — /[[emotion]]
Controls the emotional tone of your spoken (TTS) voice. Place inline where the emotion should shift.
{emotion_tags}
Rules:
- Close tags exactly — /[[emotion]] with double brackets, no trailing letters
- Wrong: /[[happys (trailing s). Correct: /[[happy]]
- Use one emotion tag per response to set your vocal tone
- Express vocal tone only — this does not affect the avatar's face

## Facial Expression — /((expression))
Controls the VRM avatar's facial blend shapes independently of your voice.
{expression_tags}
Rules:
- Close tags exactly — /((expression)) with double parens
- Use one expression tag per response to set the avatar's facial expression
- Use independently from emotions — a happy voice could have a surprised face
- The expression persists until changed by a subsequent tag

## Body Animation — /**action**/
Triggers full-body VRM animations.
{action_tags}
Rules:
- Use an action marker when your character would physically gesture (bow, wave, nod, react)
- Keep descriptions brief and natural: /**nods**/, /**waves**/, /**considers**/
- Not every line needs an action — reserve for meaningful moments

# Response Guidelines
## Tone
{character_style}

## Formatting
- Keep responses concise and natural — this is a conversation, not a document
- Never output markdown code fences (```) around your response — you are already in a chat interface
- Do not use bullet points, numbered lists, or excessive bold text unless the user specifically asks for structure
- Write in natural prose and paragraphs
- Always include at least one emotion /[[emotion]] tag and one expression /((expression)) tag in every response. Use body /**action**/ markers when your character would physically gesture.
- Use warm, engaging language. Be direct but not terse.
- Never use emojis unless the user does first

## Reasoning
For complex questions, internal deliberation, or multi-step reasoning, wrap your thinking in <think>...</think> tags before responding. The thinking content will be shown or hidden based on the user's preference.
Example: <think>The user is asking about X. Let me recall what I know about X from previous context and the available tools.</think>Here is my answer...

## Edge Cases
- If a request is ambiguous, make a reasonable attempt before asking for clarification
- If a tool fails or returns an unexpected result, report it clearly and suggest alternatives
- If asked about something outside your knowledge, be honest — use <think> to reason through what you do know
- If the user provides an image, examine it carefully and incorporate what you see into your response
{vault_rules}\
{tool_section}\
{summary_section}\
{relevant_section}\
{reasoning_note}\
"""


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

    def _get_available_animations (self ,character_id :str =None )->List [str ]:
        names =[]
        default_dir =os .path .join (PROJECT_ROOT ,"characters","default","anim")
        if os .path .exists (default_dir ):
            for f in sorted (os .listdir (default_dir )):
                if f .endswith (".vrma"):
                    name =f .replace (".vrma","")
                    name =name .replace (".bvh","")
                    names .append (name )
        if character_id and character_id !="default":
            char_dir =os .path .join (PROJECT_ROOT ,"characters",character_id ,"anim")
            if os .path .exists (char_dir ):
                for f in sorted (os .listdir (char_dir )):
                    if f .endswith (".vrma"):
                        name =f .replace (".vrma","")
                        name =name .replace (".bvh","")
                        names .append (name )
        return names 

    def build (self ,tools :List [Dict ],history :List [Dict ],user_msg :str ,
    character_id :str =None ,additional_prompt :str ="",
    summary :str ="",relevant :List [Dict ]=None ,
    tts_emotions :List [str ]=None ,expression_names :List [str ]=None )->list :
        if not character_id and self .settings :
            character_id =self .settings .get ("character.active","amalgam")
        character =self ._characters .get (character_id ,{})

        sys_prompt =self ._build_character_prompt (
        character ,additional_prompt ,character_id ,
        tts_emotions =tts_emotions ,expression_names =expression_names 
        )

        tool_section =self ._build_tool_section (tools )
        summary_section =self ._build_summary_section (summary )
        relevant_section =self ._build_relevant_section (relevant )

        sys_prompt =sys_prompt .format (
        tool_section =tool_section ,
        summary_section =summary_section ,
        relevant_section =relevant_section ,
        )

        messages =[{"role":"system","content":sys_prompt }]
        for h in history :
            messages .append ({"role":h ["role"],"content":h ["content"]})
        messages .append ({"role":"user","content":user_msg })

        return messages 

    def _build_tool_section (self ,tools :List [Dict ])->str :
        if not tools :
            return ""
        lines =["\n\n# Available Tools"]
        for t in tools :
            lines .append (f"\n## {t ['name']}")
            lines .append (t ['description'])
            if 'parameters'in t and t ['parameters'].get ('properties'):
                params =t ['parameters']['properties']
                for k ,v in params .items ():
                    lines .append (f"  - {k } ({v .get ('type','string')})")
        lines .append (
        '\n\nTo invoke a tool, respond with a tool block:\n'
        '```tool\n{"name": "<tool_name>", "arguments": {"<param>": "<value>"}}\n```'
        )
        return "\n".join (lines )

    def _build_summary_section (self ,summary :str )->str :
        if not summary :
            return ""
        return f"\n\n# Conversation Summary (Previous Session)\n{summary }"

    def _build_relevant_section (self ,relevant :List [Dict ])->str :
        if not relevant :
            return ""
        lines =["\n\n# Relevant Past Context"]
        for r in relevant :
            lines .append (f"- {r ['role']}: {r ['content']}")
        return "\n".join (lines )

    def _build_character_prompt (self ,character :Dict ,additional_prompt :str ="",
    character_id :str =None ,
    tts_emotions :List [str ]=None ,
    expression_names :List [str ]=None )->str :
        name =character .get ("name","Assistant")if character else "Assistant"
        system_prompt =character .get ("system_prompt","")if character else ""
        personality =character .get ("personality","")if character else ""
        characteristics =character .get ("characteristics","")if character else ""
        interaction_style =character .get ("interaction_style","")if character else ""
        vocabulary =character .get ("vocabulary",[])if character else []
        dialogue_examples =character .get ("dialogue_examples",[])if character else []


        identity =system_prompt or f"You are {name }, a helpful AI assistant."
        style_parts =[]
        if personality :
            style_parts .append (f"Personality: {personality }")
        if characteristics :
            style_parts .append (f"Traits: {characteristics }")
        if interaction_style :
            style_parts .append (f"Style: {interaction_style }")
        if vocabulary :
            style_parts .append (f"Signature phrases: {' '.join (f'\"{p }\"'for p in vocabulary )}")
        character_style ="\n".join (style_parts )if style_parts else "Be warm, natural, and engaging."

        if dialogue_examples :
            character_style +="\n\n## Dialogue Examples"
            for ex in dialogue_examples :
                character_style +=f'\n- "{ex }"'

        if additional_prompt and additional_prompt .strip ():
            character_style +=f"\n\n## Additional Instructions\n{additional_prompt .strip ()}"


        emotions =tts_emotions or EMOTION_TAGS 
        emotion_tags ="\n".join (f"  - /[[{e }]]"for e in emotions )
        emotion_tags =f"Available:\n{emotion_tags }"


        expressions =expression_names or VRM_EXPRESSIONS 
        expression_tags ="\n".join (f"  - /(({e }))"for e in expressions )
        expression_tags =f"Available:\n{expression_tags }"


        anims =self ._get_available_animations (character_id )
        if anims :
            anim_lines ="\n".join (f"  - /**{a }**/"for a in anims )
            action_tags =f"Available animations:\n{anim_lines }"
        else :
            action_tags ="No predefined animations — use descriptive /**action**/ markers (e.g. /**nods**/, /**waves happily**/). These will animate the avatar semantically."


        vault_rules_path =os .path .join (PROJECT_ROOT ,"user_data/vault/rules.md")
        vault_rules =""
        if os .path .exists (vault_rules_path ):
            try :
                with open (vault_rules_path ,"r")as f :
                    content =f .read ().strip ()
                if content and not content .startswith ("# Rules\n\nAdd your custom rules"):
                    vault_rules =f"\n\n## Persistent Rules\n{content }"
            except Exception :
                pass 


        reasoning_note ="\n\nFor reasoning models, use <think>your reasoning</think> before your response."

        rendered =_PROMPT_TEMPLATE .format (
        identity =identity ,
        emotion_tags =emotion_tags ,
        expression_tags =expression_tags ,
        action_tags =action_tags ,
        character_style =character_style ,
        vault_rules =vault_rules ,
        tool_section ="{tool_section}",
        summary_section ="{summary_section}",
        relevant_section ="{relevant_section}",
        reasoning_note =reasoning_note ,
        )
        return rendered 

    def build_from_messages (self ,messages :list ,new_user_msg :str )->list :
        messages .append ({"role":"user","content":new_user_msg })
        return messages 

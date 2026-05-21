import json 
import re 
import asyncio 
from typing import AsyncIterator 

from backend .core .memory import Memory 
from backend .core .context_builder import ContextBuilder 
from backend .core .llm_router import LLMRouter 


DEFAULT_EMOTION_TAGS =[
"happy","sad","angry","surprised","thinking","relaxed",
"confused","shy","jealous","bored","suspicious","victory",
"sleep","love","excited"
]
DEFAULT_EXPRESSION_NAMES =["happy","angry","sad","relaxed","surprised","blink"]


def _build_emotion_re (tags ):
    return re .compile (r'/\[\[('+'|'.join (re .escape (t )for t in tags )+r')\]\]',re .IGNORECASE )

def _build_expression_re (names ):
    return re .compile (r'/\(\(('+'|'.join (re .escape (n )for n in names )+r')\)\)',re .IGNORECASE )

ACTION_RE =re .compile (r'/\*\*(.+?)\*\*/',re .DOTALL )
THINK_RE =re .compile (r'<think>(.*?)</think>',re .DOTALL )


class Agent :
    def __init__ (self ,mcp_client =None ,llm =None ,memory =None ,context_builder =None ,settings =None ,
    emotion_tags =None ,expression_names =None ):
        self .settings =settings 
        self .llm =llm or LLMRouter (settings =settings )
        self .memory =memory or Memory (llm_router =self .llm )
        self .context_builder =context_builder or ContextBuilder (settings =settings )
        self .mcp_client =mcp_client 

        self ._emotion_tags =emotion_tags or DEFAULT_EMOTION_TAGS 
        self ._expression_names =expression_names or DEFAULT_EXPRESSION_NAMES 
        self ._build_regexes ()

    def _build_regexes (self ):
        self ._emotion_re =_build_emotion_re (self ._emotion_tags )
        self ._expression_re =_build_expression_re (self ._expression_names )

    def update_emotion_tags (self ,tags ):
        self ._emotion_tags =tags 
        self ._build_regexes ()

    def update_expression_names (self ,names ):
        self ._expression_names =names 
        self ._build_regexes ()

    def update_settings (self ,settings ):
        self .settings =settings 
        self .context_builder .settings =settings 

    async def handle_user_input (self ,text :str ,images :list =None )->AsyncIterator [str ]:
        await self .memory .add_turn ("user",text )

        iterations =0 
        current_input =text 

        while iterations <5 :
            iterations +=1 
            tools =self .mcp_client .get_tool_schema ()if self .mcp_client else []
            history =self .memory .get_recent ()
            summary =self .memory .get_summary ()
            relevant =await self .memory .get_relevant (current_input )

            character_id =None 
            additional_prompt =""
            if self .settings :
                character_id =self .settings .get ("character.active","amalgam")
                additional_prompt =self .settings .get ("character.system_prompt","")

            messages =self .context_builder .build (
            tools ,history ,current_input ,
            character_id =character_id ,
            additional_prompt =additional_prompt ,
            summary =summary ,
            relevant =relevant ,
            tts_emotions =self ._emotion_tags ,
            expression_names =self ._expression_names ,
            )

            if images :
                last_text =messages [-1 ]["content"]
                content =[{"type":"text","text":last_text }]if last_text else []
                for img in images :
                    content .append ({"type":"image_url","image_url":{"url":img }})
                messages [-1 ]["content"]=content 

            full_response =""
            clean_yielded =0 
            tool_detected =False 
            tool_block =""
            in_tool_block =False 

            try :
                async for token in self .llm .stream (messages ):
                    if not tool_detected and "```tool"in full_response +token :
                        in_tool_block =True 
                        tool_detected =True 

                    if in_tool_block :
                        tool_block +=token 
                        if "```\n"in tool_block [7 :]or tool_block .endswith ("```"):
                            try :
                                start_idx =tool_block .find ("{")
                                end_idx =tool_block .rfind ("}")+1 
                                if start_idx !=-1 and end_idx !=-1 :
                                    tool_call =json .loads (tool_block [start_idx :end_idx ])
                                    name =tool_call .get ("name")
                                    args =tool_call .get ("arguments",{})

                                    yield f"\n[Calling tool: {name }]\n"

                                    result ="No MCP client"
                                    if self .mcp_client :
                                        result =await self .mcp_client .call_tool (name ,args )

                                    current_input =f"Tool result for {name }: {result }"
                                    await self .memory .add_turn ("assistant",full_response )
                                    await self .memory .add_turn ("system",current_input )
                                    break 
                            except Exception as e :
                                yield f"\n[Error parsing tool call: {e }]\n"
                                if full_response .strip ():
                                    await self .memory .add_turn ("assistant",full_response .strip ())
                                current_input =f"Tool parse error: {e }"
                                break 
                    else :
                        full_response +=token 


                        in_think ='<think>'in full_response and '</think>'not in full_response 
                        if in_think :
                            continue 


                        think_match =THINK_RE .search (full_response )
                        if think_match :
                            yield ('__thinking__',think_match .group (1 ).strip ())
                            full_response =THINK_RE .sub ('',full_response )
                            clean_yielded =0 


                        for m in self ._emotion_re .finditer (full_response ):
                            yield ('__emotion__',m .group (1 ))
                        full_response =self ._emotion_re .sub ('',full_response )


                        for m in self ._expression_re .finditer (full_response ):
                            yield ('__expression__',m .group (1 ))
                        full_response =self ._expression_re .sub ('',full_response )


                        action_found =False 
                        for m in ACTION_RE .finditer (full_response ):
                            content =m .group (1 ).strip ()
                            if content :
                                yield ('__roleplay__',content )
                                action_found =True 
                        if action_found :
                            full_response =ACTION_RE .sub ('',full_response )
                            clean_yielded =0 


                        full_response =re .sub (r'/\[\[.*?\]\]','',full_response )
                        full_response =re .sub (r'/\(\(.*?\)\)','',full_response )

                        full_response =re .sub (r'/\[\[[^\]\s]*','',full_response )
                        full_response =re .sub (r'/\(\([^\)\s]*','',full_response )


                        if len (full_response )>clean_yielded :
                            chunk =full_response [clean_yielded :]

                            incomplete_emotion =re .search (r'/\[\[[^\[\]]*$',chunk )
                            incomplete_expr =re .search (r'/\(\([^()]*$',chunk )
                            incomplete_action =re .search (r'/\*\*[^*]*$',chunk )
                            starts =[]
                            for m in [incomplete_emotion ,incomplete_expr ,incomplete_action ]:
                                if m :
                                    starts .append (m .start ())
                            if starts :
                                cutoff =min (starts )
                                yield chunk [:cutoff ]
                            else :
                                yield chunk 
                                clean_yielded =len (full_response )
            finally :
                if not in_tool_block and full_response .strip ():
                    await self .memory .add_turn ("assistant",full_response .strip ())

            if not in_tool_block :
                return 

        if iterations >=5 :
            yield "\n[Max tool iterations reached.]\n"

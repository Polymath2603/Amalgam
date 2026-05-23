import json 
import logging 
import re 
from typing import AsyncIterator 

from backend .core .memory import Memory 
from backend .core .context_builder import ContextBuilder 
from backend .core .llm import LLMRouter 
from backend .core .plugin import get_registry as get_plugin_registry 

logger =logging .getLogger (__name__ )

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

ACTION_RE =re .compile (r'/\*\*(.+?)\*\*/?',re .DOTALL )
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

    def _process_tags (self ,text :str ):
        """Find and extract tag markers from text. Yields (tag_type, value) tuples."""
        for m in THINK_RE .finditer (text ):
            yield ('__thinking__',m .group (1 ).strip ())
        for m in self ._emotion_re .finditer (text ):
            yield ('__emotion__',m .group (1 ))
        for m in self ._expression_re .finditer (text ):
            yield ('__expression__',m .group (1 ))
        for m in ACTION_RE .finditer (text ):
            content =m .group (1 ).strip ()
            if content :
                yield ('__roleplay__',content )

    def _strip_all_tags (self ,text :str )->str :
        text =THINK_RE .sub ('',text )
        text =self ._emotion_re .sub ('',text )
        text =self ._expression_re .sub ('',text )
        text =ACTION_RE .sub ('',text )
        text =re .sub (r'/\[\[.*?\]\]','',text )
        text =re .sub (r'/\(\(.*?\)\)','',text )
        text =re .sub (r'\[\[.*?\]\]','',text )
        text =re .sub (r'\(\(.*?\)\)','',text )
        text =re .sub (r'/[a-zA-Z]+\]\]','',text )
        text =re .sub (r'/[a-zA-Z]+\)\)','',text )
        return text 

    def _clean_remaining_tags (self ,text :str )->str :
        text =re .sub (r'/\[\[[^\]\s]*','',text )
        text =re .sub (r'/\(\([^\)\s]*','',text )
        text =re .sub (r'\[\[[^\]\s]*','',text )
        text =re .sub (r'\(\([^\)\s]*','',text )
        text =re .sub (r'/[a-zA-Z]+\]\]','',text )
        text =re .sub (r'/[a-zA-Z]+\)\)','',text )
        text =re .sub (r'/ [a-zA-Z]+','',text )
        text =re .sub (r'[a-zA-Z]*\]\]','',text )
        text =re .sub (r'[a-zA-Z]*\)\)','',text )
        text =re .sub (r'\s*/\s*$','',text )
        return text .strip ()

    async def handle_user_input (self ,text :str ,images :list =None ,relationship_context :str ="")->AsyncIterator [str ]:
        await self .memory .add_turn ("user",text )

        iterations =0 
        current_input =text 
        native_tools =self .llm .supports_native_tools ()
        last_tool_call =None 

        while iterations <5 :
            iterations +=1 
            tools =self .mcp_client .get_tool_schema ()if self .mcp_client else []
            history =self .memory .get_recent ()
            summary =self .memory .get_summary ()
            relevant =await self .memory .get_relevant (current_input )

            character_id =None 
            additional_prompt =""
            if self .settings :
                character_id =self .settings .get ("character.active","default")
                additional_prompt =self .settings .get ("character.system_prompt","")

            plugins =get_plugin_registry ()
            tools =await plugins .hook_tool_definition (tools )
            messages =self .context_builder .build (
            tools ,history ,current_input ,
            character_id =character_id ,
            additional_prompt =additional_prompt ,
            summary =summary ,
            relevant =relevant ,
            tts_emotions =self ._emotion_tags ,
            expression_names =self ._expression_names ,
            relationship_context =relationship_context ,
            native_tools_available =native_tools ,
            )
            messages =await plugins .hook_messages (messages )

            if images :
                last_text =messages [-1 ]["content"]
                content =[{"type":"text","text":last_text }]if last_text else []
                for img in images :
                    content .append ({"type":"image_url","image_url":{"url":img }})
                messages [-1 ]["content"]=content 

            tool_called =False 
            in_tool_block =False 
            accumulated =""
            _last_clean =""

            try :
                logger .debug (f"agent: starting llm stream provider={self .llm .provider }, native_tools={native_tools }")
                token_count =0 

                if native_tools and tools :
                    logger .debug (f"agent: using native tool calling with {len (tools )} tools")
                    async for item in self .llm .stream_with_tools (messages ,tools ):
                        token_count +=1 
                        if isinstance (item ,str ):
                            accumulated +=item 
                            in_think ='<think>'in accumulated and '</think>'not in accumulated 
                            if in_think :
                                continue 
                            tags =list (self ._process_tags (accumulated ))
                            cleaned =self ._strip_all_tags (accumulated )
                            for tag_type ,tag_val in tags :
                                yield (tag_type ,tag_val )
                            common_len =0 
                            for a ,b in zip (cleaned ,_last_clean ):
                                if a ==b :
                                    common_len +=1 
                                else :
                                    break 
                            delta =cleaned [common_len :]
                            if delta :
                                yield delta 
                            _last_clean =cleaned 
                            accumulated =cleaned 
                        elif isinstance (item ,dict )and item .get ("type")=="tool_use":
                            tool_called =True 
                            tool_name =item ["name"]
                            tool_args =item .get ("arguments",{})
                            tool_id =item .get ("id","")
                            if accumulated .strip ():
                                await self .memory .add_turn ("assistant",accumulated .strip ())
                            tool_sig =(tool_name ,frozenset ((k ,str (v ))for k ,v in sorted (tool_args .items ())))
                            if tool_sig ==last_tool_call :
                                msg =f"Repeated identical tool call to {tool_name } — not retrying. Respond based on the previous result."
                                yield ("__error__",msg )
                                current_input =msg 
                                await self .memory .add_turn ("system",current_input )
                                break 
                            last_tool_call =tool_sig 
                            yield ("__tool__",f"Calling tool: {tool_name }")
                            result ="No MCP client"
                            if self .mcp_client :
                                result =await self .mcp_client .call_tool (tool_name ,tool_args )
                            result =await plugins .hook_tool_result (tool_name ,tool_args ,result )
                            if result .startswith ("COMMAND_BLOCKED:"):
                                blocked_cmd =result [len ("COMMAND_BLOCKED:"):]
                                yield ("__permission__",blocked_cmd )
                                yield ("__tool__",f"Command blocked — needs permission: {blocked_cmd }")
                                current_input =f"Tool result for {tool_name }: BLOCKED — {blocked_cmd }"
                            else :
                                current_input =f"Tool result for {tool_name } (call_id={tool_id }): {result }"
                            await self .memory .add_turn ("system",current_input )
                            break 
                else :
                    logger .debug (f"agent: using text-fenced tool calling (tools={bool (tools )}, native={native_tools })")
                    tool_block_buf =""
                    in_tool_block =False 
                    async for token in self .llm .stream (messages ):
                        token_count +=1 
                        if not in_tool_block and "```tool"in accumulated +token +tool_block_buf :
                            in_tool_block =True 

                        if in_tool_block :
                            tool_block_buf +=token 
                            if "```\n"in tool_block_buf or tool_block_buf .endswith ("```"):
                                try :
                                    start_idx =tool_block_buf .find ("{")
                                    end_idx =tool_block_buf .rfind ("}")+1 
                                    if start_idx !=-1 and end_idx !=-1 :
                                        tool_call =json .loads (tool_block_buf [start_idx :end_idx ])
                                        name =tool_call .get ("name")
                                        args =tool_call .get ("arguments",{})
                                        if accumulated .strip ():
                                            await self .memory .add_turn ("assistant",accumulated .strip ())
                                        tool_sig =(name ,frozenset ((k ,str (v ))for k ,v in sorted (args .items ())))
                                        if tool_sig ==last_tool_call :
                                            msg =f"Repeated identical tool call to {name } — not retrying. Respond based on the previous result."
                                            yield ("__error__",msg )
                                            current_input =msg 
                                            await self .memory .add_turn ("system",current_input )
                                            tool_called =True 
                                            break 
                                        last_tool_call =tool_sig 
                                        yield ("__tool__",f"Calling tool: {name }")
                                        result ="No MCP client"
                                        if self .mcp_client :
                                            result =await self .mcp_client .call_tool (name ,args )
                                        result =await plugins .hook_tool_result (name ,args ,result )
                                        if result .startswith ("COMMAND_BLOCKED:"):
                                            blocked_cmd =result [len ("COMMAND_BLOCKED:"):]
                                            yield ("__permission__",blocked_cmd )
                                            yield ("__tool__",f"Command blocked — needs permission: {blocked_cmd }")
                                        current_input =f"Tool result for {name }: {result }"
                                        await self .memory .add_turn ("system",current_input )
                                        tool_called =True 
                                        break 
                                except Exception as e :
                                    yield f"\n[Error parsing tool call: {e }]\n"
                                    if accumulated .strip ():
                                        await self .memory .add_turn ("assistant",accumulated .strip ())
                                    current_input =f"Tool parse error: {e }"
                                    await self .memory .add_turn ("system",current_input )
                                    tool_called =True 
                                    break 
                            else :
                                accumulated +=token 
                        else :
                            accumulated +=token 
                            in_think ='<think>'in accumulated and '</think>'not in accumulated 
                            if in_think :
                                continue 
                            tags =list (self ._process_tags (accumulated ))
                            cleaned =self ._strip_all_tags (accumulated )
                            for tag_type ,tag_val in tags :
                                yield (tag_type ,tag_val )
                            common_len =0 
                            for a ,b in zip (cleaned ,_last_clean ):
                                if a ==b :
                                    common_len +=1 
                                else :
                                    break 
                            delta =cleaned [common_len :]
                            if delta :
                                yield delta 
                            _last_clean =cleaned 
                            accumulated =cleaned 

                if not tool_called :
                    if accumulated .strip ():
                        final_text =self ._clean_remaining_tags (accumulated )
                        if _last_clean ==""and final_text :
                            yield final_text 
                        await self .memory .add_turn ("assistant",accumulated .strip ())
                    break 

            except Exception as e :
                logger .error (f"agent: stream exception: {type (e ).__name__ }: {e }")
                yield ("__error__",str (e ))
                if accumulated .strip ():
                    await self .memory .add_turn ("assistant",accumulated .strip ())
                break 
            finally :
                if in_tool_block :
                    logger .warning ("agent: stream ended mid-tool-block")
                    in_tool_block =False 

        if iterations >=5 :
            yield "\n[Max tool iterations reached.]\n"

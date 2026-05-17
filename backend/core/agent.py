"""
Agent — handles user input, manages conversation loop with tool detection.
Uses message-based prompting for proper multi-turn conversations.
"""
import json 
import re 
import asyncio 
from typing import AsyncIterator 

EMOTION_RE =re .compile (r'\[(happy|sad|angry|surprised|thinking|relaxed|confused)\]')
from backend .core .memory import Memory 
from backend .core .context_builder import ContextBuilder 
from backend .core .llm_router import LLMRouter 


class Agent :
    def __init__ (self ,mcp_client =None ,llm =None ,memory =None ,context_builder =None ,settings =None ):
        self .settings =settings 
        self .llm =llm or LLMRouter (settings =settings )
        self .memory =memory or Memory (llm_router =self .llm )
        self .context_builder =context_builder or ContextBuilder (settings =settings )
        self .mcp_client =mcp_client 

    def update_settings (self ,settings ):
        """Update settings reference for all components."""
        self .settings =settings 
        self .context_builder .settings =settings 

    async def handle_user_input (self ,text :str )->AsyncIterator [str ]:
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
            relevant =relevant 
            )

            full_response =""
            tool_detected =False 
            tool_block =""
            in_tool_block =False 

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
                            current_input =f"Tool parse error: {e }"
                            break 
                else :

                    emotion_match =EMOTION_RE .search (token )
                    if emotion_match :
                        yield ('__emotion__',emotion_match .group (1 ))
                        token =EMOTION_RE .sub ('',token )
                    full_response +=token 
                    if token :
                        yield token 

            if not in_tool_block :
                await self .memory .add_turn ("assistant",full_response )
                return 

        if iterations >=5 :
            yield "\n[Max tool iterations reached.]\n"

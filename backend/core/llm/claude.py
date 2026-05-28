"""Anthropic Claude provider via Messages API.
Supports native tool_use via the tools parameter.
"""
import json 
import logging 
from typing import AsyncIterator ,List ,Dict ,Any 

import httpx 

from .base import LLMProvider 

logger =logging .getLogger (__name__ )


class ClaudeProvider (LLMProvider ):
    def __init__ (self ,settings ):
        super ().__init__ (settings )
        self ._api_key =""
        self ._model ="claude-sonnet-4-20250514"
        self ._base_url ="https://api.anthropic.com/v1"
        self ._load_config ()
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))

    def _load_config (self ):
        if self .settings :
            self ._api_key =self .settings .get ("provider.claude.api_key","")
            self ._model =self .settings .get ("provider.claude.model","claude-sonnet-4-20250514")
            self ._base_url =self .settings .get ("provider.claude.base_url","https://api.anthropic.com/v1")

    def supports_native_tools (self )->bool :
        return bool (self ._api_key )

    def _convert_tools (self ,tools :List [Dict [str ,Any ]])->list :
        """Convert our tool schema to Claude's tools format."""
        claude_tools =[]
        for t in tools :
            claude_tools .append ({
            "name":t ["name"],
            "description":t .get ("description",""),
            "input_schema":t .get ("parameters",{"type":"object","properties":{}}),
            })
        return claude_tools 

    def _convert_content (self ,content :Any )->Any :
        if isinstance (content ,str ):
            return content 
        if isinstance (content ,list ):
            converted =[]
            for block in content :
                if isinstance (block ,dict )and block .get ("type")=="image_url":
                    url =block .get ("image_url",{}).get ("url","")
                    if url .startswith ("data:"):
                        media_type ,_ ,b64_data =url [5 :].partition (";base64,")
                        converted .append ({
                        "type":"image",
                        "source":{
                        "type":"base64",
                        "media_type":media_type ,
                        "data":b64_data ,
                        },
                        })
                    else :
                        converted .append (block )
                else :
                    converted .append (block )
            return converted 
        return content 

    def _build_messages (self ,messages :list )->list :
        result =[]
        for m in messages :
            role =m .get ("role","user")
            content =m .get ("content","")
            if role =="system":
                continue 
            result .append ({"role":role ,"content":self ._convert_content (content )})
        return result 

    def _get_system (self ,messages :list )->str :
        for m in messages :
            if m .get ("role")=="system":
                return m .get ("content","")
        return ""

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        async for item in self .stream_with_tools (messages ,[]):
            if isinstance (item ,str ):
                yield item 

    async def stream_with_tools (
    self ,messages :list ,tools :List [Dict [str ,Any ]]
    )->AsyncIterator :
        if not self ._api_key :
            raise RuntimeError ("[Error: Claude API key not set. Go to Settings > Providers.]")

        max_tokens =self .get_max_output_tokens ()
        url =f"{self ._base_url .rstrip ('/')}/messages"
        system =self ._get_system (messages )
        body ={
        "model":self ._model ,
        "messages":self ._build_messages (messages ),
        "stream":True ,
        "max_tokens":max_tokens ,
        "temperature":self .temperature ,
        }
        if system :
            body ["system"]=system 
        if tools :
            body ["tools"]=self ._convert_tools (tools )

        headers ={
        "x-api-key":self ._api_key ,
        "anthropic-version":"2023-06-01",
        "Content-Type":"application/json",
        }


        pending_tools :Dict [int ,dict ]={}

        try :
            async with self ._client .stream ("POST",url ,json =body ,headers =headers )as response :
                if response .status_code !=200 :
                    err =await response .aread ()
                    raise RuntimeError (self ._format_error (response .status_code ,err .decode ()))
                async for line in response .aiter_lines ():
                    if line .startswith ("data: "):
                        json_str =line [6 :].strip ()
                        if json_str =="[DONE]":
                            break 
                        try :
                            data =json .loads (json_str )
                            event_type =data .get ("type")

                            if event_type =="content_block_start":
                                idx =data .get ("index",0 )
                                block =data .get ("content_block",{})
                                if block .get ("type")=="tool_use":
                                    pending_tools [idx ]={
                                    "id":block ["id"],
                                    "name":block ["name"],
                                    "arguments":"",
                                    }

                            elif event_type =="content_block_delta":
                                idx =data .get ("index",0 )
                                delta =data .get ("delta",{})
                                dt =delta .get ("type")
                                if dt =="text_delta":
                                    text =delta .get ("text","")
                                    if text :
                                        yield text 
                                elif dt =="input_json_delta":
                                    if idx in pending_tools :
                                        pending_tools [idx ]["arguments"]+=delta .get ("partial_json","")

                            elif event_type =="content_block_stop":
                                idx =data .get ("index",0 )
                                if idx in pending_tools :
                                    pt =pending_tools .pop (idx )
                                    try :
                                        args =json .loads (pt ["arguments"])if pt ["arguments"]else {}
                                    except json .JSONDecodeError :
                                        args ={}
                                    yield {
                                    "type":"tool_use",
                                    "id":pt ["id"],
                                    "name":pt ["name"],
                                    "arguments":args ,
                                    }

                        except json .JSONDecodeError :
                            pass 
        except RuntimeError :
            raise 
        except Exception as e :
            logger .error (f"Claude stream error: {e }")
            raise RuntimeError (f"[Error connecting to Claude: {e }]")from e 

    async def generate (self ,messages :list )->str :
        if not self ._api_key :
            return "[Error: Claude API key not set]"
        max_tokens =self .get_max_output_tokens ()
        url =f"{self ._base_url .rstrip ('/')}/messages"
        system =self ._get_system (messages )
        body ={
        "model":self ._model ,
        "messages":self ._build_messages (messages ),
        "max_tokens":max_tokens ,
        "temperature":self .temperature ,
        }
        if system :
            body ["system"]=system 
        headers ={
        "x-api-key":self ._api_key ,
        "anthropic-version":"2023-06-01",
        "Content-Type":"application/json",
        }
        try :
            response =await self ._client .post (url ,json =body ,headers =headers )
            if response .status_code ==200 :
                data =response .json ()
                content =data .get ("content",[])
                return "".join (block .get ("text","")for block in content if block .get ("type")=="text")
            else :
                return self ._format_error (response .status_code ,response .text )
        except Exception as e :
            logger .error (f"Claude generate error: {e }")
            return f"Error: {e }"

    async def close (self ):
        await self ._client .aclose ()

    def _format_error (self ,status_code :int ,body :str )->str :
        import re as _re 
        try :
            data =json .loads (body )
            err =data .get ("error",{})
            if isinstance (err ,dict ):
                msg =err .get ("message",str (err ))
                first_sentence =_re .split (r'(?<=[.!?])\s+',msg .strip ())[0 ]
                if status_code ==429 :
                    return f"API rate limit exceeded. {first_sentence }."
                return first_sentence 
            return str (err )
        except (json .JSONDecodeError ,KeyError ,TypeError ):
            pass 
        return body [:200 ]if body else f"API Error {status_code }"

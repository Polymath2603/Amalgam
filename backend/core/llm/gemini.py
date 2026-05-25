"""Gemini provider.
Uses Gemini's OpenAI-compatible endpoint for streaming.
Supports native tool calling via the OpenAI-compatible tools format.
"""
import json 
import logging 
from typing import AsyncIterator ,List ,Dict ,Any 

import httpx 

from .base import LLMProvider 

logger =logging .getLogger (__name__ )


class GeminiProvider (LLMProvider ):
    def __init__ (self ,settings ):
        super ().__init__ (settings )
        self ._api_key =""
        self ._model ="gemini-2.0-flash"
        self ._base_url ="https://generativelanguage.googleapis.com/v1beta"
        self ._load_config ()
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))

    def _load_config (self ):
        if self .settings :
            self ._api_key =self .settings .get ("provider.gemini.api_key","")
            self ._model =self .settings .get ("provider.gemini.model","gemini-2.0-flash")
            self ._base_url =self .settings .get ("provider.gemini.base_url",
            "https://generativelanguage.googleapis.com/v1beta")

    def supports_native_tools (self )->bool :
        return bool (self ._api_key )

    def _convert_tools (self ,tools :List [Dict [str ,Any ]])->list :
        """Convert our tool schema to OpenAI's tools format (Gemini via OpenAI-compat API)."""
        openai_tools =[]
        for t in tools :
            openai_tools .append ({
            "type":"function",
            "function":{
            "name":t ["name"],
            "description":t .get ("description",""),
            "parameters":t .get ("parameters",{"type":"object","properties":{}}),
            },
            })
        return openai_tools 

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        async for item in self .stream_with_tools (messages ,[]):
            if isinstance (item ,str ):
                yield item 

    async def stream_with_tools (
    self ,messages :list ,tools :List [Dict [str ,Any ]]
    )->AsyncIterator :
        if not self ._api_key :
            logger .warning ("Gemini API key not set — returning error to user")
            yield "[Error: Gemini API key not set. Go to Settings > Providers.]"
            return 

        max_tokens =self .settings .get ("llm.max_tokens",2048 )if self .settings else 2048 
        url =f"{self ._base_url }/openai/chat/completions"
        headers ={"Authorization":f"Bearer {self ._api_key }","Content-Type":"application/json"}
        body ={
        "model":self ._model ,
        "messages":messages ,
        "stream":True ,
        "temperature":self .temperature ,
        "max_tokens":max_tokens ,
        }
        if tools :
            body ["tools"]=self ._convert_tools (tools )
            body ["tool_choice"]="auto"

        pending_tool_calls :Dict [int ,dict ]={}

        try :
            async with self ._client .stream ("POST",url ,json =body ,headers =headers )as response :
                if response .status_code !=200 :
                    err =await response .aread ()
                    raise RuntimeError (_format_error (response .status_code ,err .decode ()))
                async for line in response .aiter_lines ():
                    if line .startswith ("data: "):
                        json_str =line [6 :].strip ()
                        if json_str =="[DONE]":
                            return 
                        try :
                            data =json .loads (json_str )
                            choices =data .get ("choices",[])
                            for c in choices :
                                delta =c .get ("delta",{})

                                text =delta .get ("content","")
                                if text :
                                    yield text 

                                tool_calls =delta .get ("tool_calls",[])
                                for tc in tool_calls :
                                    idx =tc .get ("index",0 )
                                    if idx not in pending_tool_calls :
                                        pending_tool_calls [idx ]={"id":"","name":"","arguments":""}
                                    pt =pending_tool_calls [idx ]
                                    func =tc .get ("function",{})
                                    if tc .get ("id"):
                                        pt ["id"]=tc ["id"]
                                    if func .get ("name"):
                                        pt ["name"]=func ["name"]
                                    if func .get ("arguments"):
                                        pt ["arguments"]+=func ["arguments"]

                                finish_reason =c .get ("finish_reason")
                                if finish_reason =="tool_calls":
                                    for idx in sorted (pending_tool_calls .keys ()):
                                        pt =pending_tool_calls [idx ]
                                        if pt ["id"]and pt ["name"]:
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
                                    pending_tool_calls .clear ()

                        except json .JSONDecodeError :
                            logger .warning (f"Gemini: failed to parse SSE line: {line [:200 ]}")
                            pass 
        except RuntimeError :
            raise 
        except Exception as e :
            logger .error (f"Gemini stream error: {e }")
            yield f"[Error connecting to Gemini: {e }]"

    async def generate (self ,messages :list )->str :
        if not self ._api_key :
            return "[Error: Gemini API key not set]"
        max_tokens =self .settings .get ("llm.max_tokens",2048 )if self .settings else 2048 
        url =f"{self ._base_url }/openai/chat/completions"
        headers ={"Authorization":f"Bearer {self ._api_key }","Content-Type":"application/json"}
        body ={"model":self ._model ,"messages":messages ,"temperature":self .temperature ,"max_tokens":max_tokens }
        try :
            response =await self ._client .post (url ,json =body ,headers =headers )
            if response .status_code ==200 :
                choices =response .json ().get ("choices",[])
                if choices :
                    return choices [0 ].get ("message",{}).get ("content","")
            else :
                return _format_error (response .status_code ,response .text )
        except Exception as e :
            logger .error (f"Gemini generate error: {e }")
            return f"Error: {e }"
        return ""

    async def get_embedding (self ,text :str )->List [float ]:
        if not self ._api_key :
            return []
        url =f"{self ._base_url }/models/text-embedding-004:embedContent"
        headers ={"Authorization":f"Bearer {self ._api_key }","Content-Type":"application/json"}
        body ={"content":{"parts":[{"text":text }]}}
        try :
            response =await self ._client .post (url ,headers =headers ,json =body )
            if response .status_code ==200 :
                return response .json ().get ("embedding",{}).get ("values",[])
        except Exception :
            pass 
        return []

    async def fetch_models (self )->List [str ]:
        if not self ._api_key :
            logger .warning ("Gemini API key not set — cannot fetch models")
            return []
        try :
            url ="https://generativelanguage.googleapis.com/v1beta/models"
            response =await self ._client .get (url ,headers ={"Authorization":f"Bearer {self ._api_key }"},timeout =10.0 )
            if response .status_code ==200 :
                models =response .json ().get ("models",[])
                return [
                m ["name"].replace ("models/","")
                for m in models 
                if "generateContent"in m .get ("supportedGenerationMethods",[])
                ]
        except Exception as e :
            logger .error (f"Gemini models fetch error: {e }")
        return []

    async def close (self ):
        await self ._client .aclose ()


def _format_error (status_code :int ,body :str )->str :
    import json 
    import re as _re 
    message =body .strip ()
    if not message :
        return f"API Error {status_code }"
    try :
        data =json .loads (body )
        if isinstance (data ,list )and data :
            data =data [0 ]
        if isinstance (data ,dict )and "error"in data :
            err =data ["error"]
            if isinstance (err ,dict ):
                msg =err .get ("message",str (err ))
                code =err .get ("code",status_code )
                try :
                    code =int (code )
                except (ValueError ,TypeError ):
                    pass 
                first_sentence =_re .split (r'(?<=[.!?])\s+',msg .strip ())[0 ]
                if code ==429 :
                    return f"API rate limit exceeded. {first_sentence }."
                return first_sentence 
            return str (err )
    except (json .JSONDecodeError ,IndexError ,KeyError ,TypeError ):
        pass 
    if len (message )>200 :
        message =message [:200 ].rsplit (' ',1 )[0 ]+'...'
    return message 

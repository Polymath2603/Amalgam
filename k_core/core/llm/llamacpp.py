"""LlamaCpp provider — local server with /completion endpoint."""
import json 
import logging 
from typing import AsyncIterator 

import httpx 

from .base import LLMProvider 

logger =logging .getLogger (__name__ )


class LlamaCppProvider (LLMProvider ):
    def __init__ (self ,settings ):
        super ().__init__ (settings )
        self ._url ="http://localhost:8080"
        self ._model =""
        self ._load_config ()
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))

    def _load_config (self ):
        if self .settings :
            self ._url =self .settings .get ("provider.llamacpp.base_url","http://localhost:8080")
            self ._model =self .settings .get ("provider.llamacpp.model","")

    def _build_prompt (self ,messages :list )->str :
        prompt =""
        for m in messages :
            role =m .get ("role","user")
            content =m .get ("content","")
            if role =="system":
                prompt +=f"System: {content }\n"
            elif role =="user":
                prompt +=f"User: {content }\n"
            else :
                prompt +=f"Assistant: {content }\n"
        prompt +="Assistant:"
        return prompt 

    def _get_stop_tokens (self )->list :
        stop =["User:","System:"]
        name ="Assistant"
        if self .settings :
            char =self .settings .get_active_character ()
            name =char .get ("name","Assistant")if char else "Assistant"
        stop .append (f"{name }:")
        return stop 

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        url =f"{self ._url .rstrip ('/')}/completion"
        prompt =self ._build_prompt (messages )
        max_tokens =self .settings .get ("llm.max_tokens",2048 )if self .settings else 2048 
        body ={
        "prompt":prompt ,
        "stream":True ,
        "n_predict":max_tokens ,
        "temperature":self .temperature ,
        "cache_prompt":True ,
        "stop":self ._get_stop_tokens (),
        }
        try :
            async with self ._client .stream ("POST",url ,json =body )as response :
                if response .status_code !=200 :
                    err =await response .aread ()
                    raise RuntimeError (f"Error: LlamaCpp returned {response .status_code } - {err .decode ()[:200 ]}")
                async for line in response .aiter_lines ():
                    if line .startswith ("data: "):
                        json_str =line [6 :].strip ()
                        if json_str =="[DONE]":
                            return 
                        try :
                            data =json .loads (json_str )
                            content =data .get ("content","")
                            if content :
                                yield content 
                            if data .get ("stop"):
                                return 
                        except json .JSONDecodeError :
                            pass 
        except RuntimeError :
            raise 
        except Exception as e :
            logger .error (f"LlamaCpp stream error: {e }")
            raise RuntimeError (f"[Error connecting to LlamaCpp: {e }]")from e 

    async def generate (self ,messages :list )->str :
        url =f"{self ._url .rstrip ('/')}/completion"
        prompt =self ._build_prompt (messages )
        max_tokens =self .settings .get ("llm.max_tokens",2048 )if self .settings else 2048 
        body ={
        "prompt":prompt ,
        "stream":False ,
        "n_predict":max_tokens ,
        "temperature":self .temperature ,
        "stop":self ._get_stop_tokens (),
        }
        try :
            response =await self ._client .post (url ,json =body )
            if response .status_code ==200 :
                return response .json ().get ("content","")
        except Exception as e :
            logger .error (f"LlamaCpp generate error: {e }")
            return f"Error: {e }"
        return ""

    async def close (self ):
        await self ._client .aclose ()

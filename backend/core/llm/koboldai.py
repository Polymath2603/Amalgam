"""KoboldAI provider — local server with /api/v1/generate or streaming."""
import json 
import logging 
from typing import AsyncIterator 

import httpx 

from .base import LLMProvider 

logger =logging .getLogger (__name__ )


class KoboldAIProvider (LLMProvider ):
    def __init__ (self ,settings ):
        super ().__init__ (settings )
        self ._url ="http://localhost:5001"
        self ._model =""
        self ._load_config ()
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))

    def _load_config (self ):
        if self .settings :
            self ._url =self .settings .get ("provider.koboldai.base_url","http://localhost:5001")
            self ._model =self .settings .get ("provider.koboldai.model","")

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

    def _get_stop_sequence (self )->list :
        stop =["User:","System:"]
        name ="Assistant"
        if self .settings :
            char =self .settings .get_active_character ()
            name =char .get ("name","Assistant")if char else "Assistant"
        stop .append (f"{name }:")
        return stop 

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        prompt =self ._build_prompt (messages )
        stop =self ._get_stop_sequence ()
        max_tokens =self .settings .get ("llm.max_tokens",2048 )if self .settings else 2048 

        try :
            async with self ._client .stream (
            "POST",
            f"{self ._url .rstrip ('/')}/api/extra/generate/stream",
            json ={"prompt":prompt ,"stop_sequence":stop ,"max_length":max_tokens ,"temperature":self .temperature },
            )as response :
                if response .status_code !=200 :
                    err =await response .aread ()
                    raise RuntimeError (f"Error: KoboldAI returned {response .status_code } - {err .decode ()[:200 ]}")
                buffer =""
                async for chunk in response .aiter_bytes ():
                    buffer +=chunk .decode ()
                    while "\n"in buffer :
                        line ,buffer =buffer .split ("\n",1 )
                        line =line .strip ()
                        if line .startswith ("data:"):
                            try :
                                data =json .loads (line [5 :])
                                token =data .get ("token","")
                                if token :
                                    yield token 
                            except json .JSONDecodeError :
                                pass 
        except RuntimeError :
            raise 
        except Exception as e :
            logger .error (f"KoboldAI stream error: {e }")
            raise RuntimeError (f"[Error connecting to KoboldAI: {e }]")from e 

    async def generate (self ,messages :list )->str :
        prompt =self ._build_prompt (messages )
        stop =self ._get_stop_sequence ()
        max_tokens =self .settings .get ("llm.max_tokens",2048 )if self .settings else 2048 
        try :
            response =await self ._client .post (
            f"{self ._url .rstrip ('/')}/api/v1/generate",
            json ={"prompt":prompt ,"stop_sequence":stop ,"max_length":max_tokens ,"temperature":self .temperature },
            )
            if response .status_code ==200 :
                results =response .json ().get ("results",[])
                return "".join (r .get ("text","")for r in results )
        except Exception as e :
            logger .error (f"KoboldAI generate error: {e }")
            return f"Error: {e }"
        return ""

    async def close (self ):
        await self ._client .aclose ()

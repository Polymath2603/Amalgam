import json 
import logging 
from typing import AsyncIterator ,List 

import httpx 

from .base import LLMProvider 

logger =logging .getLogger (__name__ )


class OllamaProvider (LLMProvider ):
    def __init__ (self ,settings ):
        super ().__init__ (settings )
        self ._url ="http://localhost:11434"
        self ._model =""
        self ._embed_model ="nomic-embed-text"
        self ._timeout =120.0 
        self ._load_config ()
        self ._client =None 
        self ._ensure_client ()

    def _ensure_client (self ):
        if self ._client is None :
            self ._client =httpx .AsyncClient (timeout =httpx .Timeout (self ._timeout ,connect =10.0 ))

    def _reset_client (self ):
        if self ._client :
            try :
                import asyncio 
                loop =asyncio .get_event_loop ()
                if loop .is_running ():
                    loop .create_task (self ._client .aclose ())
            except Exception :
                pass 
        self ._client =None 

    def _load_config (self ):
        if self .settings :
            self ._url =self .settings .get ("provider.ollama.base_url","http://localhost:11434")
            self ._model =self .settings .get ("provider.ollama.model","")
            self ._embed_model =self .settings .get ("provider.ollama.embed_model","nomic-embed-text")

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        self ._ensure_client ()
        try :
            max_tokens =self .get_max_output_tokens ()
            async with self ._client .stream (
            "POST",
            f"{self ._url }/api/chat",
            json ={"model":self ._model ,"messages":messages ,"stream":True ,"options":{"num_predict":max_tokens ,"temperature":self .temperature }},
            )as response :
                if response .status_code !=200 :
                    raise RuntimeError (f"Error: Ollama returned {response .status_code }")
                async for line in response .aiter_lines ():
                    if line :
                        try :
                            data =json .loads (line )
                            msg =data .get ("message",{})
                            if "content"in msg :
                                yield msg ["content"]
                        except json .JSONDecodeError :
                            pass 
        except RuntimeError :
            self ._reset_client ()
            raise 
        except Exception as e :
            logger .error (f"Ollama stream error ({type (e ).__name__ }): {e }")
            self ._reset_client ()
            raise RuntimeError (f"[Ollama error: {type (e ).__name__ }: {e }]")from e 

    async def generate (self ,messages :list )->str :
        self ._ensure_client ()
        try :
            max_tokens =self .get_max_output_tokens ()
            response =await self ._client .post (
            f"{self ._url }/api/chat",
            json ={"model":self ._model ,"messages":messages ,"stream":False ,"options":{"num_predict":max_tokens ,"temperature":self .temperature }},
            )
            if response .status_code ==200 :
                msg =response .json ().get ("message",{})
                return msg .get ("content","")
        except Exception as e :
            logger .error (f"Ollama generate error ({type (e ).__name__ }): {e }")
            self ._reset_client ()
            return f"Error: {e }"
        return ""

    async def get_embedding (self ,text :str )->List [float ]:
        self ._ensure_client ()
        try :
            response =await self ._client .post (
            f"{self ._url }/api/embeddings",
            json ={"model":self ._embed_model ,"prompt":text },
            )
            if response .status_code ==200 :
                return response .json ().get ("embedding",[])
        except Exception as e :
            logger .warning ("Ollama embedding request failed (%s): %s",type (e ).__name__ ,e )
            self ._reset_client ()
        return []

    async def fetch_models (self )->List [str ]:
        self ._ensure_client ()
        try :
            response =await self ._client .get (f"{self ._url }/api/tags",timeout =5.0 )
            if response .status_code ==200 :
                return [m ["name"]for m in response .json ().get ("models",[])]
        except Exception as e :
            logger .warning ("Ollama fetch models failed: %s",e )
        return []

    async def close (self ):
        if self ._client :
            await self ._client .aclose ()
            self ._client =None 

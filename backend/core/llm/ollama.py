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
        self ._load_config ()
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))

    def _load_config (self ):
        if self .settings :
            self ._url =self .settings .get ("provider.ollama.base_url","http://localhost:11434")
            self ._model =self .settings .get ("provider.ollama.model","")

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        try :
            async with self ._client .stream (
            "POST",
            f"{self ._url }/api/chat",
            json ={"model":self ._model ,"messages":messages ,"stream":True },
            )as response :
                if response .status_code !=200 :
                    yield f"Error: Ollama returned {response .status_code }"
                    return 
                async for line in response .aiter_lines ():
                    if line :
                        try :
                            data =json .loads (line )
                            msg =data .get ("message",{})
                            if "content"in msg :
                                yield msg ["content"]
                        except json .JSONDecodeError :
                            pass 
        except Exception as e :
            logger .error (f"Ollama stream error: {e }")
            yield f"[Error connecting to Ollama: {e }]"

    async def generate (self ,messages :list )->str :
        try :
            response =await self ._client .post (
            f"{self ._url }/api/chat",
            json ={"model":self ._model ,"messages":messages ,"stream":False },
            )
            if response .status_code ==200 :
                msg =response .json ().get ("message",{})
                return msg .get ("content","")
        except Exception as e :
            logger .error (f"Ollama generate error: {e }")
            return f"Error: {e }"
        return ""

    async def get_embedding (self ,text :str )->List [float ]:
        try :
            response =await self ._client .post (
            f"{self ._url }/api/embeddings",
            json ={"model":self ._model ,"prompt":text },
            )
            if response .status_code ==200 :
                return response .json ().get ("embedding",[])
        except Exception :
            pass 
        return []

    async def fetch_models (self )->List [str ]:
        try :
            response =await self ._client .get (f"{self ._url }/api/tags",timeout =5.0 )
            if response .status_code ==200 :
                return [m ["name"]for m in response .json ().get ("models",[])]
        except Exception :
            pass 
        return []

    async def close (self ):
        await self ._client .aclose ()

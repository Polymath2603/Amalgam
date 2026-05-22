import json 
import logging 
from typing import AsyncIterator ,List 

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

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        if not self ._api_key :
            logger .warning ("Gemini API key not set — returning error to user")
            yield "[Error: Gemini API key not set. Go to Settings > Providers.]"
            return 

        url =f"{self ._base_url }/openai/chat/completions"
        headers ={"Authorization":f"Bearer {self ._api_key }","Content-Type":"application/json"}
        body ={"model":self ._model ,"messages":messages ,"stream":True ,"temperature":self .temperature ,"max_tokens":2048 }

        try :
            async with self ._client .stream ("POST",url ,json =body ,headers =headers )as response :
                if response .status_code !=200 :
                    err =await response .aread ()
                    yield _format_error (response .status_code ,err .decode ())
                    return 
                async for line in response .aiter_lines ():
                    if line .startswith ("data: "):
                        json_str =line [6 :].strip ()
                        if json_str =="[DONE]":
                            return 
                        try :
                            data =json .loads (json_str )
                            for c in data .get ("choices",[]):
                                content =c .get ("delta",{}).get ("content","")
                                if content :
                                    yield content 
                        except json .JSONDecodeError :
                            pass 
        except Exception as e :
            logger .error (f"Gemini stream error: {e }")
            yield f"[Error connecting to Gemini: {e }]"

    async def generate (self ,messages :list )->str :
        if not self ._api_key :
            return "[Error: Gemini API key not set]"
        url =f"{self ._base_url }/openai/chat/completions"
        headers ={"Authorization":f"Bearer {self ._api_key }","Content-Type":"application/json"}
        body ={"model":self ._model ,"messages":messages ,"temperature":self .temperature ,"max_tokens":2048 }
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
        url =f"{self ._base_url }/models/text-embedding-004:embedContent?key={self ._api_key }"
        body ={"content":{"parts":[{"text":text }]}}
        try :
            response =await self ._client .post (url ,json =body )
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
            url =f"https://generativelanguage.googleapis.com/v1beta/models?key={self ._api_key }"
            response =await self ._client .get (url ,timeout =10.0 )
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
                if code ==429 :
                    return f"Quota exceeded. {msg }"
                return msg 
            return str (err )
    except (json .JSONDecodeError ,IndexError ,KeyError ,TypeError ):
        pass 
    if len (message )>200 :
        message =message [:200 ].rsplit (' ',1 )[0 ]+'...'
    return message 

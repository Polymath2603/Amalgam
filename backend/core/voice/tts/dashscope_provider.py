"""DashScope CosyVoice TTS provider — Alibaba Cloud."""
import json 
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider, retry_http 

logger =logging .getLogger (__name__ )


class DashScopeProvider (TTSProvider ):
    def __init__ (self ,voice ="longxiaochun"):
        super ().__init__ (voice )
        self ._api_key =""
        self ._model ="cosyvoice-v1"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))

    def configure (self ,api_key :str ,model :str ="cosyvoice-v1"):
        self ._api_key =api_key 
        self ._model =model 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        if not text .strip ()or not self ._api_key :
            if not self ._api_key :
                logger .warning ("DashScope API key not configured")
            return np .zeros (0 ,dtype =np .float32 ),None ,16000 

        url ="https://dashscope.aliyuncs.com/api/v1/services/aigc/text2audio/audio-synthesis"
        headers ={
        "Authorization":f"Bearer {self ._api_key }",
        "Content-Type":"application/json",
        }
        body ={
        "model":self ._model ,
        "input":{"text":text },
        "parameters":{"voice":self .voice },
        }

        try :
            response =await retry_http (self ._client ,"POST",url ,json =body ,headers =headers )
            if response is None or response .status_code !=200 :
                logger .error ("DashScope TTS error or request failed")
                return np .zeros (0 ,dtype =np .float32 ),None ,16000 

            audio_np =np .frombuffer (response .content ,dtype =np .int16 ).astype (np .float32 )/32767.0 
            return audio_np ,None ,16000 
        except httpx .HTTPStatusError as e :
            logger .error (f"DashScope TTS HTTP error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,16000 
        except httpx .RequestError as e :
            logger .error (f"DashScope TTS request error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,16000 
        except Exception as e :
            logger .error (f"DashScope TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,16000 

    async def close (self ):
        await self ._client .aclose ()

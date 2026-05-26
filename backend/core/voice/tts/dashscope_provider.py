"""DashScope CosyVoice TTS provider — Alibaba Cloud."""
import json 
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider 

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
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

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
            response =await self ._client .post (url ,json =body ,headers =headers )
            if response .status_code !=200 :
                logger .error (f"DashScope TTS error {response .status_code }: {response .text [:200 ]}")
                return np .zeros (0 ,dtype =np .float32 ),[],16000 

            audio_np =np .frombuffer (response .content ,dtype =np .int16 ).astype (np .float32 )/32767.0 
            visemes =["A"]*(len (text )//2 )
            return audio_np ,visemes ,16000 
        except Exception as e :
            logger .error (f"DashScope TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

    async def close (self ):
        await self ._client .aclose ()

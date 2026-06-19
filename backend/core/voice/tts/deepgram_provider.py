"""Deepgram TTS provider."""
import json 
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class DeepgramProvider (TTSProvider ):
    def __init__ (self ,voice ="aura-asteria-en"):
        super ().__init__ (voice )
        self ._api_key =""
        self ._model ="aura-2"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,api_key :str ,model :str ="aura-2"):
        self ._api_key =api_key 
        self ._model =model 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        if not text .strip ()or not self ._api_key :
            if not self ._api_key :
                logger .warning ("Deepgram API key not configured")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 

        url =f"https://api.deepgram.com/v1/speak"
        headers ={
        "Authorization":f"Token {self ._api_key }",
        "Content-Type":"application/json",
        }
        params ={"model":self ._model ,"encoding":"linear16","sample_rate":24000 }
        body ={"text":text }

        try :
            async with self ._client .stream ("POST",url ,json =body ,headers =headers ,params =params )as resp :
                if resp .status_code !=200 :
                    error_text =await resp .aread ()
                    logger .error (f"Deepgram TTS error {resp .status_code }: {error_text [:200 ]}")
                    return np .zeros (0 ,dtype =np .float32 ),None ,24000 
                audio_bytes =await resp .aread ()

            audio_np =np .frombuffer (audio_bytes ,dtype =np .int16 ).astype (np .float32 )/32767.0 
            return audio_np ,None ,24000 
        except httpx .HTTPStatusError as e :
            logger .error (f"Deepgram TTS HTTP error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 
        except httpx .RequestError as e :
            logger .error (f"Deepgram TTS request error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 
        except Exception as e :
            logger .error (f"Deepgram TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 

    async def close (self ):
        await self ._client .aclose ()

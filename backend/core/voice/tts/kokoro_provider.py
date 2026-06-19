"""Kokoro TTS provider — local TTS via Kokoro API."""
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider, decode_wav, retry_http 

logger =logging .getLogger (__name__ )


class KokoroProvider (TTSProvider ):
    def __init__ (self ,voice ="af_heart"):
        super ().__init__ (voice )
        self ._url ="http://127.0.0.1:8880"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,url :str =None ):
        if url :
            self ._url =url .rstrip ("/")

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        url =f"{self ._url .rstrip ('/')}/tts"
        body ={"text":text ,"voice":self .voice }
        try :
            response =await retry_http (self ._client ,"POST",url ,json =body ,
            headers ={"Content-Type":"application/json"})
            if response is None or response .status_code !=200 :
                logger .error ("Kokoro TTS error or request failed")
                return np .zeros (0 ,dtype =np .float32 ),None ,24000 

            audio_np ,sr =decode_wav (response .content )
            return audio_np ,None ,sr 
        except httpx .HTTPStatusError as e :
            logger .error (f"Kokoro TTS HTTP error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 

        except httpx .RequestError as e :
            logger .error (f"Kokoro TTS request error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 
        except Exception as e :
            logger .error (f"Kokoro TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 

    async def close (self ):
        await self ._client .aclose ()

"""Piper TTS provider — local TTS via Piper HTTP server."""
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider, decode_wav, retry_http 

logger =logging .getLogger (__name__ )


class PiperProvider (TTSProvider ):
    def __init__ (self ,voice ="en_US-lessac-medium"):
        super ().__init__ (voice )
        import os
        self ._url =os .environ .get ("AMALGAM_PIPER_URL","http://127.0.0.1:5000")
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,url :str =None ):
        if url :
            self ._url =url .rstrip ("/")

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        import urllib .parse 
        url =f"{self ._url .rstrip ('/')}/?text={urllib .parse .quote (text )}"
        try :
            response =await retry_http (self ._client ,"GET",url )
            if response is None or response .status_code !=200 :
                logger .error ("Piper TTS error or request failed")
                return np .zeros (0 ,dtype =np .float32 ),None ,22050 

            audio_np ,sr =decode_wav (response .content )
            return audio_np ,None ,sr 
        except httpx .HTTPStatusError as e :
            logger .error (f"Piper TTS HTTP error: {e }")

        except httpx .RequestError as e :
            logger .error (f"Piper TTS request error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,22050 
        except Exception as e :
            logger .error (f"Piper TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,22050 

    async def close (self ):
        await self ._client .aclose ()

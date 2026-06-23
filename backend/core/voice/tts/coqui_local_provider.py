"""Coqui Local TTS provider — local TTS via Coqui API server."""
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider, decode_wav, retry_http 

logger =logging .getLogger (__name__ )


class CoquiLocalProvider (TTSProvider ):
    def __init__ (self ,voice ="default"):
        super ().__init__ (voice )
        import os
        self ._url =os .environ .get ("AMALGAM_COQUI_URL","http://127.0.0.1:5002")
        self ._speaker_id =""
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,url :str =None ,speaker_id :str =""):
        if url :
            self ._url =url .rstrip ("/")
        self ._speaker_id =speaker_id 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        url =f"{self ._url .rstrip ('/')}/api/tts"
        headers ={"text":text }
        if self ._speaker_id :
            headers ["speaker-id"]=self ._speaker_id 
        try :
            response =await retry_http (self ._client ,"POST",url ,headers =headers )
            if response is None or response .status_code !=200 :
                logger .error ("Coqui TTS error or request failed")
                return np .zeros (0 ,dtype =np .float32 ),None ,24000 

            audio_np ,sr =decode_wav (response .content )
            return audio_np ,None ,sr 
        except httpx .HTTPStatusError as e :
            logger .error (f"Coqui TTS HTTP error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 

        except httpx .RequestError as e :
            logger .error (f"Coqui TTS request error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 
        except Exception as e :
            logger .error (f"Coqui TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 

    async def close (self ):
        await self ._client .aclose ()

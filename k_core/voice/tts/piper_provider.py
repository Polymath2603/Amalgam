"""Piper TTS provider — local TTS via Piper HTTP server."""
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class PiperProvider (TTSProvider ):
    def __init__ (self ,voice ="en_US-lessac-medium"):
        super ().__init__ (voice )
        self ._url ="http://127.0.0.1:5000"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,url :str =None ):
        if url :
            self ._url =url .rstrip ("/")

    async def synthesize (self ,text :str ,ref_audio :str =None )->tuple :
        import urllib .parse 
        url =f"{self ._url .rstrip ('/')}/?text={urllib .parse .quote (text )}"
        try :
            response =await self ._client .get (url )
            if response .status_code !=200 :
                logger .error (f"Piper TTS error {response .status_code }")
                return np .zeros (0 ,dtype =np .float32 ),[],22050 

            audio_bytes =response .content 
            import io 
            import wave 
            with io .BytesIO (audio_bytes )as buf :
                with wave .open (buf ,"rb")as wf :
                    sr =wf .getframerate ()
                    frames =wf .readframes (wf .getnframes ())
                    audio_np =np .frombuffer (frames ,dtype =np .int16 ).astype (np .float32 )/32767.0 
            return audio_np ,[],sr 
        except Exception as e :
            logger .error (f"Piper TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],22050 

    async def close (self ):
        await self ._client .aclose ()

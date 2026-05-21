"""Kokoro TTS provider — local TTS via Kokoro API."""
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class KokoroProvider (TTSProvider ):
    def __init__ (self ,voice ="af_heart"):
        super ().__init__ (voice )
        self ._url ="http://127.0.0.1:8880"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,url :str =None ):
        if url :
            self ._url =url .rstrip ("/")

    async def synthesize (self ,text :str ,ref_audio :str =None )->tuple :
        url =f"{self ._url .rstrip ('/')}/tts"
        body ={"text":text ,"voice":self .voice }
        try :
            response =await self ._client .post (url ,json =body ,
            headers ={"Content-Type":"application/json"})
            if response .status_code !=200 :
                logger .error (f"Kokoro TTS error {response .status_code }")
                return np .zeros (0 ,dtype =np .float32 ),[],24000 

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
            logger .error (f"Kokoro TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],24000 

    async def close (self ):
        await self ._client .aclose ()

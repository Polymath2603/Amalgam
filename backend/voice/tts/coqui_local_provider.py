"""Coqui Local TTS provider — local TTS via Coqui API server."""
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class CoquiLocalProvider (TTSProvider ):
    def __init__ (self ,voice ="default"):
        super ().__init__ (voice )
        self ._url ="http://127.0.0.1:5002"
        self ._speaker_id =""
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,url :str =None ,speaker_id :str =""):
        if url :
            self ._url =url .rstrip ("/")
        self ._speaker_id =speaker_id 

    async def synthesize (self ,text :str ,ref_audio :str =None )->tuple :
        url =f"{self ._url .rstrip ('/')}/api/tts"
        headers ={"text":text }
        if self ._speaker_id :
            headers ["speaker-id"]=self ._speaker_id 
        try :
            response =await self ._client .post (url ,headers =headers )
            if response .status_code !=200 :
                logger .error (f"Coqui TTS error {response .status_code }")
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
            logger .error (f"Coqui TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],24000 

    async def close (self ):
        await self ._client .aclose ()

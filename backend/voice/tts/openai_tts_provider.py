"""OpenAI TTS provider — cloud TTS via OpenAI API."""
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class OpenAITTSProvider (TTSProvider ):
    def __init__ (self ,voice ="alloy"):
        super ().__init__ (voice )
        self ._api_key =""
        self ._model ="tts-1"
        self ._base_url ="https://api.openai.com/v1"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,api_key :str ,model :str ="tts-1",base_url :str =None ):
        self ._api_key =api_key 
        self ._model =model 
        if base_url :
            self ._base_url =base_url .rstrip ("/")

    async def synthesize (self ,text :str ,ref_audio :str =None )->tuple :
        if not self ._api_key :
            logger .warning ("OpenAI TTS API key not set")
            return np .zeros (0 ,dtype =np .float32 ),[],24000 

        url =f"{self ._base_url }/audio/speech"
        headers ={
        "Authorization":f"Bearer {self ._api_key }",
        "Content-Type":"application/json",
        }
        body ={
        "model":self ._model ,
        "input":text ,
        "voice":self .voice ,
        "response_format":"wav",
        }
        try :
            response =await self ._client .post (url ,json =body ,headers =headers )
            if response .status_code ==200 :
                audio_bytes =response .content 
                import io 
                import wave 
                import struct 
                with io .BytesIO (audio_bytes )as buf :
                    with wave .open (buf ,"rb")as wf :
                        sr =wf .getframerate ()
                        frames =wf .readframes (wf .getnframes ())
                        audio_np =np .frombuffer (frames ,dtype =np .int16 ).astype (np .float32 )/32767.0 
                return audio_np ,[],sr 
            else :
                logger .error (f"OpenAI TTS error {response .status_code }: {response .text [:200 ]}")
        except Exception as e :
            logger .error (f"OpenAI TTS error: {e }")
        return np .zeros (0 ,dtype =np .float32 ),[],24000 

    async def close (self ):
        await self ._client .aclose ()

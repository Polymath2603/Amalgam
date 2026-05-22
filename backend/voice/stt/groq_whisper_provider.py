"""Groq Whisper STT provider — Groq's OpenAI-compatible Whisper API."""
import logging 
import numpy as np 
import httpx 

from .base import STTProvider 
from .utils import numpy_to_wav 

logger =logging .getLogger (__name__ )


class GroqWhisperProvider (STTProvider ):
    def __init__ (self ,api_key ="",model ="whisper-large-v3"):
        super ().__init__ ()
        self ._api_key =api_key 
        self ._model =model 
        self ._base_url ="https://api.groq.com/openai/v1"

    def configure (self ,api_key :str ,model :str ="whisper-large-v3",base_url :str =None ):
        self ._api_key =api_key 
        self ._model =model 
        if base_url :
            self ._base_url =base_url .rstrip ("/")

    def transcribe (self ,audio_np :np .ndarray )->str :
        if not self ._api_key :
            logger .warning ("Groq Whisper API key not set")
            return ""

        wav_bytes =numpy_to_wav (audio_np )
        try :
            resp =httpx .post (
            f"{self ._base_url }/audio/transcriptions",
            headers ={"Authorization":f"Bearer {self ._api_key }"},
            files ={"file":("audio.wav",wav_bytes ,"audio/wav")},
            data ={"model":self ._model ,"response_format":"text"},
            timeout =120 ,
            )
            if resp .status_code ==200 :
                text =resp .text .strip ()
                logger .debug (f"Groq Whisper STT: {text }")
                return text 
            else :
                logger .error (f"Groq Whisper API error {resp .status_code }: {resp .text [:200 ]}")
        except Exception as e :
            logger .error (f"Groq Whisper STT error: {e }")
        return ""



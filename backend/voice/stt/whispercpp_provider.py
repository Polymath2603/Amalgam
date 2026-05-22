"""Whisper.cpp STT provider — local Whisper.cpp server."""
import logging 
import numpy as np 
import httpx 

from .base import STTProvider 
from .utils import numpy_to_wav 

logger =logging .getLogger (__name__ )


class WhisperCppProvider (STTProvider ):
    def __init__ (self ):
        super ().__init__ ()
        self ._url ="http://127.0.0.1:8080"

    def configure (self ,url :str =None ):
        if url :
            self ._url =url .rstrip ("/")

    def transcribe (self ,audio_np :np .ndarray )->str :
        wav_bytes =numpy_to_wav (audio_np )
        try :
            files ={"file":("audio.wav",wav_bytes ,"audio/wav")}
            resp =httpx .post (
            f"{self ._url .rstrip ('/')}/inference",
            files =files ,
            timeout =120 ,
            )
            if resp .status_code ==200 :
                text =resp .json ().get ("text","").strip ()
                logger .debug (f"Whisper.cpp STT: {text }")
                return text 
            else :
                logger .error (f"Whisper.cpp API error {resp .status_code }: {resp .text [:200 ]}")
        except Exception as e :
            logger .error (f"Whisper.cpp STT error: {e }")
        return ""



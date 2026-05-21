"""OpenAI Whisper API STT provider — cloud-based alternative to faster-whisper."""
import io 
import logging 
import wave 
import numpy as np 
import httpx 

from .base import STTProvider 

logger =logging .getLogger (__name__ )


class OpenAIWhisperProvider (STTProvider ):
    """STT via OpenAI Whisper API. Requires API key."""

    def __init__ (self ,api_key ="",model ="whisper-1"):
        super ().__init__ ()
        self ._api_key =api_key 
        self ._model =model 
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))

    def configure (self ,api_key :str ,model :str ="whisper-1"):
        self ._api_key =api_key 
        self ._model =model 

    def transcribe (self ,audio_np :np .ndarray )->str :
        """Transcribe 16kHz float32 numpy array via OpenAI Whisper API."""
        if not self ._api_key :
            logger .warning ("OpenAI Whisper API key not set")
            return ""

        wav_bytes =self ._numpy_to_wav (audio_np )
        try :
            import httpx as sync_httpx 
            resp =sync_httpx .post (
            "https://api.openai.com/v1/audio/transcriptions",
            headers ={"Authorization":f"Bearer {self ._api_key }"},
            files ={"file":("audio.wav",wav_bytes ,"audio/wav")},
            data ={"model":self ._model ,"response_format":"text"},
            timeout =120 ,
            )
            if resp .status_code ==200 :
                text =resp .text .strip ()
                logger .info (f"OpenAI Whisper STT: {text }")
                return text 
            else :
                logger .error (f"OpenAI Whisper API error {resp .status_code }: {resp .text [:200 ]}")
        except Exception as e :
            logger .error (f"OpenAI Whisper STT error: {e }")
        return ""

    def _numpy_to_wav (self ,audio_np :np .ndarray ,sr :int =16000 )->bytes :
        """Convert float32 numpy array to WAV bytes."""
        import struct 
        pcm =(audio_np *32767 ).astype ("int16").tobytes ()
        data_size =len (pcm )
        header =struct .pack (
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',36 +data_size ,b'WAVE',
        b'fmt ',16 ,1 ,1 ,sr ,sr *2 ,2 ,16 ,
        b'data',data_size 
        )
        return header +pcm 

    async def close (self ):
        await self ._client .aclose ()

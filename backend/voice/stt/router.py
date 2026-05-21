import logging 
from .faster_whisper_provider import FasterWhisperProvider 
from .openai_whisper_provider import OpenAIWhisperProvider 
from .groq_whisper_provider import GroqWhisperProvider 
from .whispercpp_provider import WhisperCppProvider 

logger =logging .getLogger (__name__ )


class STTRouter :
    SUPPORTED_ENGINES ={"faster-whisper","openai-whisper","groq-whisper","whispercpp"}

    def __init__ (self ,engine ="faster-whisper"):
        self .engine =engine 
        self ._providers ={
        "faster-whisper":FasterWhisperProvider (),
        "openai-whisper":OpenAIWhisperProvider (),
        "groq-whisper":GroqWhisperProvider (),
        "whispercpp":WhisperCppProvider (),
        }

    def _current (self ):
        return self ._providers .get (self .engine ,self ._providers ["faster-whisper"])

    def configure_openai (self ,api_key :str ,model :str ="whisper-1"):
        self ._providers ["openai-whisper"].configure (api_key ,model )

    def configure_groq (self ,api_key :str ,model :str ="whisper-large-v3",base_url :str =None ):
        self ._providers ["groq-whisper"].configure (api_key ,model ,base_url )

    def configure_whispercpp (self ,url :str =None ):
        self ._providers ["whispercpp"].configure (url )

    def transcribe (self ,audio_np )->str :
        return self ._current ().transcribe (audio_np )

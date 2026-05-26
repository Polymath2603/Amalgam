import logging 

logger =logging .getLogger (__name__ )


class STTRouter :
    SUPPORTED_ENGINES ={"browser","faster-whisper","openai-whisper","groq-whisper","whispercpp","deepgram"}

    _PROVIDER_CLASSES =None 

    @classmethod 
    def _get_provider_classes (cls ):
        if cls ._PROVIDER_CLASSES is None :
            from .browser_provider import BrowserSTTProvider 
            from .faster_whisper_provider import FasterWhisperProvider 
            from .openai_whisper_provider import OpenAIWhisperProvider 
            from .groq_whisper_provider import GroqWhisperProvider 
            from .whispercpp_provider import WhisperCppProvider 
            from .deepgram_provider import DeepgramSTTProvider 
            cls ._PROVIDER_CLASSES ={
            "browser":BrowserSTTProvider ,
            "faster-whisper":FasterWhisperProvider ,
            "openai-whisper":OpenAIWhisperProvider ,
            "groq-whisper":GroqWhisperProvider ,
            "whispercpp":WhisperCppProvider ,
            "deepgram":DeepgramSTTProvider ,
            }
        return cls ._PROVIDER_CLASSES 

    def __init__ (self ,engine ="browser"):
        self .engine =engine 
        self ._providers ={}

    def _ensure (self ,name ):
        if name not in self ._providers :
            cls =self ._get_provider_classes ().get (name )
            if cls is None :
                raise ValueError (f"Unknown STT engine: {name }")
            self ._providers [name ]=cls ()
        return self ._providers [name ]

    def _current (self ):
        return self ._ensure (self .engine )

    def configure_openai (self ,api_key :str ,model :str ="whisper-1"):
        self ._ensure ("openai-whisper").configure (api_key ,model )

    def configure_groq (self ,api_key :str ,model :str ="whisper-large-v3",base_url :str =None ):
        self ._ensure ("groq-whisper").configure (api_key ,model ,base_url )

    def configure_whispercpp (self ,url :str =None ):
        self ._ensure ("whispercpp").configure (url )

    def configure_deepgram (self ,api_key :str ,model :str ="nova-2"):
        self ._ensure ("deepgram").configure (api_key ,model )

    def transcribe (self ,audio_np )->str :
        return self ._current ().transcribe (audio_np )

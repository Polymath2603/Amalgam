import logging 
import asyncio 
import numpy as np 

logger =logging .getLogger (__name__ )


class TTSRouter :
    SUPPORTED_ENGINES ={"edge-tts","openvoice","elevenlabs","openai-tts",
    "speecht5","alltalk","piper","coqui-local","kokoro"}

    _PROVIDER_CLASSES =None 

    @classmethod 
    def _get_provider_classes (cls ):
        if cls ._PROVIDER_CLASSES is None :
            from .edge_tts_provider import EdgeTTSProvider 
            from .openvoice_provider import OpenVoiceProvider 
            from .elevenlabs_provider import ElevenLabsProvider 
            from .openai_tts_provider import OpenAITTSProvider 
            from .speecht5_provider import SpeechT5Provider 
            from .alltalk_provider import AllTalkProvider 
            from .piper_provider import PiperProvider 
            from .coqui_local_provider import CoquiLocalProvider 
            from .kokoro_provider import KokoroProvider 
            cls ._PROVIDER_CLASSES ={
            "edge-tts":EdgeTTSProvider ,
            "openvoice":OpenVoiceProvider ,
            "elevenlabs":ElevenLabsProvider ,
            "openai-tts":OpenAITTSProvider ,
            "speecht5":SpeechT5Provider ,
            "alltalk":AllTalkProvider ,
            "piper":PiperProvider ,
            "coqui-local":CoquiLocalProvider ,
            "kokoro":KokoroProvider ,
            }
        return cls ._PROVIDER_CLASSES 

    def __init__ (self ,voice ="en-US-AriaNeural",engine ="edge-tts"):
        self .engine =engine 
        self ._lock =asyncio .Lock ()
        self ._providers ={}
        self ._voice =voice 

    def _ensure (self ,name ,voice =None ):
        if name not in self ._providers :
            cls =self ._get_provider_classes ().get (name )
            if cls is None :
                raise ValueError (f"Unknown TTS engine: {name }")
            self ._providers [name ]=cls (voice or self ._voice )
        return self ._providers [name ]

    def _current (self ):
        return self ._ensure (self .engine )

    @property 
    def voice (self ):
        return self ._voice 

    @voice .setter 
    def voice (self ,val ):
        self ._voice =val 
        for p in self ._providers .values ():
            p .voice =val 

    def get_supported_emotions (self ):
        return self ._current ().supported_emotions 

    def get_openvoice_loaded (self ):
        ov =self ._ensure ("openvoice")
        return ov .get_openvoice_loaded ()

    def configure_elevenlabs (self ,api_key: "REDACTED"):
        self ._ensure ("elevenlabs").configure (api_key ,model )

    def configure_openai_tts (self ,api_key :str ,model :str ="tts-1",base_url :str =None ):
        self ._ensure ("openai-tts").configure (api_key ,model ,base_url )

    def configure_alltalk (self ,url :str =None ,language :str ="en",version :str ="v2",
    rvc_voice :str ="",rvc_pitch :str ="0"):
        self ._ensure ("alltalk").configure (url ,language ,version ,rvc_voice ,rvc_pitch )

    def configure_piper (self ,url :str =None ):
        self ._ensure ("piper").configure (url )

    def configure_coqui (self ,url :str =None ,speaker_id :str =""):
        self ._ensure ("coqui-local").configure (url ,speaker_id )

    def configure_kokoro (self ,url :str =None ):
        self ._ensure ("kokoro").configure (url )

    _SR_MAP ={
    "elevenlabs":44100 ,
    "openai-tts":24000 ,
    "speecht5":16000 ,
    "edge-tts":16000 ,
    "alltalk":24000 ,
    "piper":22050 ,
    "coqui-local":24000 ,
    "kokoro":24000 ,
    "openvoice":22050 ,
    }

    async def synthesize (self ,text :str ,ref_audio :str =None )->tuple :
        if not text .strip ():
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        provider =self ._current ()
        async with self ._lock :
            if self .engine =="openvoice":
                result =await provider .synthesize (text ,ref_audio =ref_audio )
                if isinstance (result ,tuple )and len (result )>=3 :
                    audio ,visemes ,*_ =result 
                else :
                    audio ,visemes =result 
                if len (audio )>0 :
                    return audio ,visemes ,22050 
                logger .warning ("OpenVoice failed, falling back to edge-tts")
                fallback =self ._ensure ("edge-tts")
                result =await fallback .synthesize (text )
                if isinstance (result ,tuple )and len (result )>=3 :
                    audio ,visemes ,*_ =result 
                else :
                    audio ,visemes =result 
                return audio ,visemes ,16000 
            else :
                result =await provider .synthesize (text ,ref_audio =ref_audio )
                if isinstance (result ,tuple )and len (result )>=3 :
                    audio ,visemes ,sr =result 
                else :
                    audio ,visemes =result 
                    sr =self ._SR_MAP .get (self .engine ,16000 )
                return audio ,visemes ,sr 

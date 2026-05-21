import logging 
import asyncio 
import numpy as np 

from .edge_tts_provider import EdgeTTSProvider 
from .openvoice_provider import OpenVoiceProvider 
from .elevenlabs_provider import ElevenLabsProvider 
from .openai_tts_provider import OpenAITTSProvider 
from .speecht5_provider import SpeechT5Provider 
from .alltalk_provider import AllTalkProvider 
from .piper_provider import PiperProvider 
from .coqui_local_provider import CoquiLocalProvider 
from .kokoro_provider import KokoroProvider 

logger =logging .getLogger (__name__ )


class TTSRouter :
    SUPPORTED_ENGINES ={"edge-tts","openvoice","elevenlabs","openai-tts",
    "speecht5","alltalk","piper","coqui-local","kokoro"}

    def __init__ (self ,voice ="en-US-AriaNeural",engine ="edge-tts"):
        self .engine =engine 
        self ._lock =asyncio .Lock ()
        self ._providers ={
        "edge-tts":EdgeTTSProvider (voice ),
        "openvoice":OpenVoiceProvider (voice ),
        "elevenlabs":ElevenLabsProvider (voice ),
        "openai-tts":OpenAITTSProvider ("alloy"),
        "speecht5":SpeechT5Provider ("default"),
        "alltalk":AllTalkProvider ("female_01.wav"),
        "piper":PiperProvider ("en_US-lessac-medium"),
        "coqui-local":CoquiLocalProvider ("default"),
        "kokoro":KokoroProvider ("af_heart"),
        }
        self .voice =voice 

    def _current (self ):
        return self ._providers .get (self .engine ,self ._providers ["edge-tts"])

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
        ov =self ._providers ["openvoice"]
        return ov .get_openvoice_loaded ()

    def configure_elevenlabs (self ,api_key: "REDACTED"):
        self ._providers ["elevenlabs"].configure (api_key ,model )

    def configure_openai_tts (self ,api_key :str ,model :str ="tts-1",base_url :str =None ):
        self ._providers ["openai-tts"].configure (api_key ,model ,base_url )

    def configure_alltalk (self ,url :str =None ,language :str ="en",version :str ="v2",
    rvc_voice :str ="",rvc_pitch :str ="0"):
        self ._providers ["alltalk"].configure (url ,language ,version ,rvc_voice ,rvc_pitch )

    def configure_piper (self ,url :str =None ):
        self ._providers ["piper"].configure (url )

    def configure_coqui (self ,url :str =None ,speaker_id :str =""):
        self ._providers ["coqui-local"].configure (url ,speaker_id )

    def configure_kokoro (self ,url :str =None ):
        self ._providers ["kokoro"].configure (url )

    async def synthesize (self ,text :str ,ref_audio :str =None )->tuple :
        if not text .strip ():
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        provider =self ._current ()
        async with self ._lock :
            if self .engine =="openvoice":
                audio ,visemes =await provider .synthesize (text ,ref_audio =ref_audio )
                if len (audio )>0 :
                    return audio ,visemes ,22050 
                logger .warning ("OpenVoice failed, falling back to edge-tts")
                fallback =self ._providers ["edge-tts"]
                audio ,visemes =await fallback .synthesize (text )
                return audio ,visemes ,16000 
            else :
                audio ,visemes =await provider .synthesize (text ,ref_audio =ref_audio )
                sr_map ={
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
                sr =sr_map .get (self .engine ,16000 )
                return audio ,visemes ,sr 

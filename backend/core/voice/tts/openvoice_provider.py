import logging 
import asyncio 
import numpy as np 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class OpenVoiceProvider (TTSProvider ):
    """Local voice cloning via OpenVoice."""

    def __init__ (self ,voice =""):
        super ().__init__ (voice )
        self ._ov_engine =None 

    def _get_engine (self ):
        if self ._ov_engine is None :
            from backend .core .voice .openvoice_engine import OpenVoiceEngine 
            self ._ov_engine =OpenVoiceEngine ()
        return self ._ov_engine 

    def get_openvoice_loaded (self ):
        ov =self ._get_engine ()
        ov ._ensure_loaded ()
        return True 

    async def synthesize (self ,text :str ,ref_audio :str =None ,**kwargs )->tuple :
        if not text .strip ():
            return np .zeros (0 ,dtype =np .float32 ),[],22050 
        if not ref_audio :
            logger .error ("OpenVoice requires a reference audio path")
            return np .zeros (0 ,dtype =np .float32 ),[]

        ov =self ._get_engine ()
        try :
            loop =asyncio .get_event_loop ()
            result =await loop .run_in_executor (None ,ov .synthesize ,text ,ref_audio )
            if not result or not isinstance (result ,tuple )or len (result )<2 :
                logger .error (f"OpenVoice returned invalid result: {type (result )}")
                return np .zeros (0 ,dtype =np .float32 ),[]
            audio_np ,sr =result 
            if not isinstance (audio_np ,np .ndarray ):
                audio_np =np .array (audio_np ,dtype =np .float32 )if audio_np is not None else np .zeros (0 ,dtype =np .float32 )
            return audio_np ,None 
        except Exception as e :
            logger .error (f"OpenVoice TTS Error: {type (e ).__name__ }: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None

"""MLX TTS provider — Apple Silicon local TTS via mlx-audio or mlx-tts."""
import logging 
import platform 
import numpy as np 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class MLXProvider (TTSProvider ):
    def __init__ (self ,voice ="default"):
        super ().__init__ (voice )
        self ._model =None 
        self ._processor =None 
        self ._sr =24000 

    def _ensure_model (self ):
        if self ._model is not None :
            return 
        if platform .system ()!="Darwin":
            raise RuntimeError ("MLX TTS requires macOS (Apple Silicon)")

        try :
            import mlx .core as mx 
            from mlx_audio .tts import TTS as MLXTTS 
            self ._model =MLXTTS (self .voice if self .voice !="default"else "mlx-community/XTTS-v2")
            logger .debug ("MLX TTS model loaded")
        except ImportError :
            raise ImportError ("MLX TTS requires 'mlx-audio' package. Install with: pip install mlx-audio")
        except Exception as e :
            logger .error (f"MLX TTS load error: {e }")
            raise 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        import asyncio 

        if not text .strip ():
            return np .zeros (0 ,dtype =np .float32 ),[],self ._sr 

        try :
            self ._ensure_model ()
        except Exception as e :
            logger .error (f"MLX TTS init error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],self ._sr 

        loop =asyncio .get_event_loop ()

        def _sync_synth ():
            audio =self ._model .generate (text )
            if isinstance (audio ,tuple ):
                audio =audio [0 ]
            if hasattr (audio ,"numpy"):
                audio =audio .numpy ()
            return audio .astype (np .float32 )

        try :
            audio_np =await loop .run_in_executor (None ,_sync_synth )
            return audio_np ,None ,self ._sr 
        except Exception as e :
            logger .error (f"MLX TTS synthesis error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,self ._sr 

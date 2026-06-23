"""SpeechT5 provider — Hugging Face model for local TTS."""
import asyncio 
import logging 

import numpy as np 
import torch 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class SpeechT5Provider (TTSProvider ):
    def __init__ (self ,voice ="default"):
        super ().__init__ (voice )
        self ._model =None 
        self ._processor =None 
        self ._speaker_embeddings =None 
        logger .warning (
            "SpeechT5 will download ~2 GB of model data on first synthesize() call. "
            "Ensure sufficient disk space and network connectivity."
        )

    def _ensure_model (self ):
        if self ._model is not None :
            return 
        try :
            from transformers import SpeechT5Processor ,SpeechT5ForTextToSpeech ,SpeechT5HifiGan 
            logger .debug ("Loading SpeechT5 model...")
            self ._processor =SpeechT5Processor .from_pretrained ("microsoft/speecht5_tts")
            self ._model =SpeechT5ForTextToSpeech .from_pretrained ("microsoft/speecht5_tts")
            self ._vocoder =SpeechT5HifiGan .from_pretrained ("microsoft/speecht5_hifigan")

            import datasets 
            emb_dataset =datasets .load_dataset ("Matthijs/cmu-arctic-xvectors",split ="validation")
            self ._speaker_embeddings =torch .tensor (emb_dataset [7306 ]["xvector"]).unsqueeze (0 )
            logger .debug ("SpeechT5 model loaded")
        except ImportError as e :
            logger .error (f"SpeechT5 dependencies missing: {e }")
            raise 
        except Exception as e :
            logger .error (f"SpeechT5 load error: {e }")
            raise 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        try :
            loop =asyncio .get_event_loop ()
            result =await loop .run_in_executor (None ,self ._synthesize_sync ,text )
            return result 
        except Exception as e :
            logger .error (f"SpeechT5 synthesis error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,16000 

    def _synthesize_sync (self ,text :str )->tuple :
        self ._ensure_model ()
        inputs =self ._processor (text =text ,return_tensors ="pt")
        with torch .no_grad ():
            speech =self ._model .generate_speech (
            inputs ["input_ids"],
            self ._speaker_embeddings ,
            vocoder =self ._vocoder ,
            )
        audio_np =speech .squeeze ().numpy ().astype (np .float32 )
        return audio_np ,None ,16000 

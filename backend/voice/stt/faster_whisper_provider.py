import logging 
import numpy as np 
from faster_whisper import WhisperModel 

from .base import STTProvider 

logger =logging .getLogger (__name__ )


class FasterWhisperProvider (STTProvider ):
    """Local STT via faster-whisper. Runs on CPU with int8 quantization."""

    def __init__ (self ,model_size ="base"):
        super ().__init__ ()
        self .model_size =model_size 
        self ._model =None 

    def _ensure_model (self ):
        if self ._model is None :
            logger .info (f"Loading faster-whisper model '{self .model_size }'...")
            self ._model =WhisperModel (self .model_size ,device ="cpu",compute_type ="int8")

    def transcribe (self ,audio_np :np .ndarray )->str :
        self ._ensure_model ()
        segments ,info =self ._model .transcribe (audio_np ,beam_size =5 )
        text =" ".join ([segment .text for segment in segments ]).strip ()
        logger .info (f"STT: {text }")
        return text 

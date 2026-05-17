import numpy as np 
import logging 
from faster_whisper import WhisperModel 

logger =logging .getLogger (__name__ )

class STT :
    def __init__ (self ,model_size ="base"):
        logger .info (f"Loading faster-whisper model '{model_size }'...")
        self .model =WhisperModel (model_size ,device ="cpu",compute_type ="int8")

    def transcribe (self ,audio_np :np .ndarray )->str :
        """Transcribes a 16kHz numpy array."""
        segments ,info =self .model .transcribe (audio_np ,beam_size =5 )
        text =" ".join ([segment .text for segment in segments ]).strip ()
        logger .info (f"STT: {text }")
        return text 

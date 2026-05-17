import webrtcvad 
import numpy as np 
import logging 

logger =logging .getLogger (__name__ )

class VAD :
    def __init__ (self ,mode =3 ):
        self .vad =webrtcvad .Vad ()
        self .vad .set_mode (mode )
        self .sample_rate =16000 

    def process (self ,audio_bytes :bytes )->bool :
        """Returns True if the audio frame contains speech."""


        try :
            return self .vad .is_speech (audio_bytes ,self .sample_rate )
        except Exception as e :
            logger .debug (f"VAD Error: {e }")
            return False 

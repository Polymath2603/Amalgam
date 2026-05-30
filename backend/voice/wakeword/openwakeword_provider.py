import logging 
import threading 
from typing import Optional ,Callable 

import numpy as np 
import sounddevice as sd 

from backend .voice .wakeword .base import WakeWordProvider 

logger =logging .getLogger (__name__ )

RATE =16000 
CHUNK =960 
CHANNELS =1 


class OpenWakeWordProvider (WakeWordProvider ):
    def __init__ (self ,on_detected :Optional [Callable [[str ],None ]]=None ):
        super ().__init__ (on_detected )
        self ._model =None 
        self ._stream =None 
        self ._thread =None 
        self ._stop_event =threading .Event ()
        self ._running =False 

    def start (self ):
        if self ._running :
            return 
        try :
            from openwakeword import Model as OWWModel 
        except ImportError :
            logger .error (
            "openwakeword not installed. Run: pip install openwakeword"
            )
            raise 
        try :
            self ._model =OWWModel (
            wakeword_models =["hey_amalgam","alexa"],
            enable_speex_noise_suppression =True ,
            )
        except Exception :
            logger .warning ("Speex noise suppression unavailable, falling back to raw")
            self ._model =OWWModel (wakeword_models =["hey_amalgam","alexa"])

        self ._stop_event .clear ()
        self ._running =True 
        self ._thread =threading .Thread (target =self ._listen_loop ,daemon =True )
        self ._thread .start ()
        logger .info ("Wake word listening started (openwakeword)")

    def stop (self ):
        self ._running =False 
        self ._stop_event .set ()
        if self ._stream :
            try :
                self ._stream .close ()
            except Exception :
                pass 
            self ._stream =None 
        if self ._thread and self ._thread .is_alive ():
            self ._thread .join (timeout =2 )
        self ._thread =None 
        self ._model =None 
        logger .info ("Wake word listening stopped")

    @property 
    def is_running (self )->bool :
        return self ._running 

    def feed_audio (self ,chunk :bytes ):
        if not self ._model :
            return 
        audio =np .frombuffer (chunk ,dtype =np .int16 ).astype (np .float32 )/32768.0 
        prediction =self ._model .predict (audio )
        for ww_name in self ._model .prediction_data :
            scores =self ._model .prediction_data [ww_name ]["scores"]
            if scores and scores [-1 ]>0.5 :
                logger .info (f"Wake word detected: {ww_name }")
                if self ._on_detected :
                    self ._on_detected (ww_name )
                break 

    def _listen_loop (self ):
        try :
            with sd .RawInputStream (
            samplerate =RATE ,
            blocksize =CHUNK ,
            channels =CHANNELS ,
            dtype ="int16",
            )as stream :
                self ._stream =stream 
                while self ._running and not self ._stop_event .is_set ():
                    chunk ,_ =stream .read (CHUNK )
                    self .feed_audio (chunk )
        except Exception as e :
            logger .error (f"Wake word mic error: {e }")
            self ._running =False 

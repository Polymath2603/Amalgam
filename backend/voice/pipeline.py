"""Voice input pipeline — microphone capture, VAD, STT, callback.
Designed to run in a background thread via run_in_executor.
"""
import numpy as np 
import logging 

logger =logging .getLogger (__name__ )


class VoicePipeline :
    def __init__ (self ,agent_callback =None ):
        self .agent_callback =agent_callback 
        self ._listening =False 
        self ._vad =None 
        self ._stt =None 

    def _ensure_models (self ):
        if self ._vad is None :
            from backend .voice .vad import VAD 
            self ._vad =VAD ()
        if self ._stt is None :
            from backend .voice .stt import STT 
            self ._stt =STT ()

    def listen_loop (self ):
        """Blocking listen loop for background thread. Monitors mic via sounddevice."""
        try :
            import sounddevice as sd 
        except ImportError :
            logger .warning ("sounddevice not installed. Voice input unavailable.")
            return 

        self ._ensure_models ()
        self ._listening =True 
        logger .info ("VoicePipeline: Listening for speech...")


        audio_queue =bytearray ()
        recording =bytearray ()
        is_recording =False 
        silence_frames =0 

        def audio_callback (indata ,frames ,time ,status ):
            audio_queue .extend (bytes (indata ))

        stream =sd .RawInputStream (
        samplerate =16000 ,blocksize =480 ,dtype ='int16',channels =1 ,
        callback =audio_callback 
        )

        try :
            with stream :
                while self ._listening :
                    if len (audio_queue )<960 :
                        sd .sleep (30 )
                        continue 


                    chunk =bytes (audio_queue )
                    audio_queue .clear ()

                    samples =np .frombuffer (chunk ,dtype =np .int16 ).astype (np .float32 )/32768.0 
                    energy =np .sqrt (np .mean (samples **2 ))

                    if energy >0.01 :
                        if not is_recording :
                            is_recording =True 
                            recording =bytearray ()
                            silence_frames =0 
                            logger .info ("VoicePipeline: Speech detected")
                        recording .extend (chunk )
                        silence_frames =0 
                    elif is_recording :
                        recording .extend (chunk )
                        silence_frames +=1 
                        if silence_frames >33 :
                            is_recording =False 
                            silence_frames =0 

                            audio_data =np .frombuffer (bytes (recording ),dtype =np .int16 ).astype (np .float32 )/32768.0 
                            if len (audio_data )>8000 :
                                logger .info ("VoicePipeline: Transcribing...")
                                text =self ._stt .transcribe (audio_data )
                                if text and self .agent_callback :
                                    self .agent_callback (text )
                            recording =bytearray ()
        except Exception as e :
            logger .error (f"VoicePipeline error: {e }")
        finally :
            self ._listening =False 
            logger .info ("VoicePipeline: Stopped")

    def stop_listening (self ):
        self ._listening =False 

"""Voice input pipeline — microphone capture, VAD, STT, callback.
Designed to run in a background thread via run_in_executor.
Supports pluggable STT engines via STTRouter.
"""
import numpy as np 
import logging 

from backend .voice .stt .router import STTRouter 

logger =logging .getLogger (__name__ )


class VoicePipeline :
    def __init__ (self ,agent_callback =None ,stt_engine ="faster-whisper"):
        self .agent_callback =agent_callback 
        self ._listening =False 
        self ._vad =None 
        self ._stt =STTRouter (engine =stt_engine )

    def configure_openai_stt (self ,api_key :str ,model :str ="whisper-1"):
        self ._stt .configure_openai (api_key ,model )

    def configure_groq_stt (self ,api_key :str ,model :str ="whisper-large-v3",base_url :str =None ):
        self ._stt .configure_groq (api_key ,model ,base_url )

    def configure_whispercpp_stt (self ,url :str =None ):
        self ._stt .configure_whispercpp (url )

    def _ensure_models (self ):
        if self ._vad is None :
            from backend .voice .vad import VAD 
            self ._vad =VAD ()

    def listen_loop (self ):
        """Blocking listen loop for background thread. Monitors mic via sounddevice."""
        try :
            import sounddevice as sd 
            import queue 
        except ImportError :
            logger .warning ("sounddevice or queue not installed. Voice input unavailable.")
            return 

        self ._ensure_models ()
        self ._listening =True 
        logger .info (f"VoicePipeline: Listening for speech (STT: {self ._stt .engine })...")

        audio_q =queue .Queue ()

        def audio_callback (indata ,frames ,time ,status ):
            if status :
                logger .warning (f"Audio input status: {status }")
            audio_q .put (bytes (indata ))

        stream =sd .RawInputStream (
        samplerate =16000 ,blocksize =480 ,dtype ='int16',channels =1 ,
        callback =audio_callback 
        )

        recording =bytearray ()
        is_recording =False 
        silence_frames =0 
        FRAME_SIZE =960 

        try :
            with stream :
                while self ._listening :
                    try :
                        chunk =audio_q .get (timeout =0.1 )
                    except queue .Empty :
                        continue 

                    for i in range (0 ,len (chunk ),FRAME_SIZE ):
                        frame =chunk [i :i +FRAME_SIZE ]
                        if len (frame )<FRAME_SIZE :
                            continue 

                        is_speech =self ._vad .process (frame )
                        samples =np .frombuffer (frame ,dtype =np .int16 ).astype (np .float32 )/32768.0 
                        energy =np .sqrt (np .mean (samples **2 ))
                        speech_detected =is_speech or (energy >0.1 )

                        if speech_detected :
                            if not is_recording :
                                is_recording =True 
                                recording =bytearray ()
                                silence_frames =0 
                                logger .info ("VoicePipeline: Speech detected")
                            recording .extend (frame )
                            silence_frames =0 
                        elif is_recording :
                            recording .extend (frame )
                            silence_frames +=1 
                            if silence_frames >33 :
                                is_recording =False 
                                silence_frames =0 

                                audio_data =np .frombuffer (bytes (recording ),dtype =np .int16 ).astype (np .float32 )/32768.0 
                                if len (audio_data )>8000 :
                                    logger .info (f"VoicePipeline: Transcribing {len (audio_data )/16000 :.1f}s of audio...")
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

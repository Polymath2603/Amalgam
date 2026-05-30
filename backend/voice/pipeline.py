"""Voice input pipeline — microphone capture, VAD, STT, callback.
Designed to run in a background thread via run_in_executor.
Supports pluggable STT engines via STTRouter.
"""
import concurrent .futures 
import threading 
import numpy as np 
import logging 

from backend .voice .stt .router import STTRouter 

logger =logging .getLogger (__name__ )


class VoicePipeline :
    def __init__ (self ,agent_callback =None ,stt_engine ="browser",settings =None ,
    on_speech_start =None ):
        self .agent_callback =agent_callback 
        self .on_speech_start =on_speech_start 
        self ._stop_event =threading .Event ()
        self ._vad =None 
        self ._stt =STTRouter (engine =stt_engine )
        self ._stt_executor =concurrent .futures .ThreadPoolExecutor (max_workers =1 ,thread_name_prefix ="stt")
        self ._stream =None 
        self ._settings =settings or {}

    def configure_openai_stt (self ,api_key :str ,model :str ="whisper-1"):
        self ._stt .configure_openai (api_key ,model )

    def configure_groq_stt (self ,api_key :str ,model :str ="whisper-large-v3",base_url :str =None ):
        self ._stt .configure_groq (api_key ,model ,base_url )

    def configure_whispercpp_stt (self ,url :str =None ):
        self ._stt .configure_whispercpp (url )

    def configure_deepgram_stt (self ,api_key :str ,model :str ="nova-2"):
        self ._stt .configure_deepgram (api_key ,model )

    def _ensure_models (self ):
        if self ._vad is None :
            from backend .voice .vad import VAD 
            vad_mode =self ._settings .get ("voice.vad_mode",2 )
            self ._vad =VAD (mode =vad_mode )

    def _on_stt_done (self ,future ):
        try :
            result =future .result ()
            if result is not None and result .strip ()and self .agent_callback :
                self .agent_callback (result )
        except concurrent .futures .CancelledError :
            pass 
        except Exception as e :
            logger .error (f"STT transcription failed: {e }")

    def listen_loop (self ):
        """Blocking listen loop for background thread. Monitors mic via sounddevice."""
        try :
            import sounddevice as sd 
            import queue 
        except ImportError :
            logger .warning ("sounddevice or queue not installed. Voice input unavailable.")
            return 

        self ._ensure_models ()
        self ._stop_event .clear ()
        logger .debug (f"VoicePipeline: Listening for speech (STT: {self ._stt .engine })...")

        audio_q =queue .Queue ()

        def audio_callback (indata ,frames ,time ,status ):
            if status :
                logger .warning (f"Audio input status: {status }")
            audio_q .put (bytes (indata ))

        self ._stream =sd .RawInputStream (
        samplerate =16000 ,blocksize =480 ,dtype ='int16',channels =1 ,
        callback =audio_callback 
        )

        recording =bytearray ()
        is_recording =False 
        silence_frames =0 
        frame_size =self ._settings .get ("voice.vad_frame_size",960 )
        energy_threshold =self ._settings .get ("voice.vad_energy_threshold",0.02 )
        max_silence_frames =self ._settings .get ("voice.vad_silence_frames",33 )

        try :
            with self ._stream :
                while not self ._stop_event .is_set ():
                    try :
                        chunk =audio_q .get (timeout =0.1 )
                    except queue .Empty :
                        continue 

                    for i in range (0 ,len (chunk ),frame_size ):
                        frame =chunk [i :i +frame_size ]
                        if len (frame )<frame_size :
                            continue 

                        is_speech =self ._vad .process (frame )
                        samples =np .frombuffer (frame ,dtype =np .int16 ).astype (np .float32 )/32768.0 
                        energy =np .sqrt (np .mean (samples **2 ))
                        speech_detected =is_speech or (energy >energy_threshold )

                        if speech_detected :
                            if not is_recording :
                                is_recording =True 
                                recording =bytearray ()
                                silence_frames =0 
                                logger .debug ("VoicePipeline: Speech detected")
                                if self .on_speech_start :
                                    try :
                                        self .on_speech_start ()
                                    except Exception as e :
                                        logger .error (f"VoicePipeline: on_speech_start error: {e }")
                            recording .extend (frame )
                            silence_frames =0 
                        elif is_recording :
                            recording .extend (frame )
                            silence_frames +=1 
                            if silence_frames >max_silence_frames :
                                is_recording =False 
                                silence_frames =0 

                                audio_data =np .frombuffer (bytes (recording ),dtype =np .int16 ).astype (np .float32 )/32768.0 
                                if len (audio_data )>8000 :
                                    logger .debug (f"VoicePipeline: Transcribing {len (audio_data )/16000 :.1f}s of audio...")
                                    future =self ._stt_executor .submit (self ._stt .transcribe ,audio_data )
                                    future .add_done_callback (self ._on_stt_done )
                                recording =bytearray ()
        except Exception as e :
            logger .error (f"VoicePipeline error: {e }")
        finally :
            logger .debug ("VoicePipeline: Stopped")

    def stop_listening (self ):
        self ._stop_event .set ()
        if self ._stream is not None :
            try :
                self ._stream .close ()
            except Exception :
                pass 
        self ._stt_executor .shutdown (wait =False )

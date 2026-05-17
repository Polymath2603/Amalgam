import asyncio 
import numpy as np 
import logging 

logger =logging .getLogger (__name__ )
from backend .voice .vad import VAD 
from backend .voice .stt import STT 
from backend .voice .tts import TTS 
from backend .voice .viseme_mapper import map_phonemes 
from backend .voice .audio_player import AudioPlayer 

class VoicePipeline :
    def __init__ (self ,agent_callback =None ):
        self .vad =VAD ()
        self .stt =STT ()
        self .tts =TTS ()
        self .player =AudioPlayer ()
        self .agent_callback =agent_callback 
        self ._interrupt_event =asyncio .Event ()
        self ._listening =False 

    async def listen_loop (self ):
        """Full-duplex background loop: monitors mic, interrupts speaking, transcribes."""
        try :
            import sounddevice as sd 
        except ImportError :
            logger .warning ("sounddevice not installed. Mock listen loop.")
            self ._listening =True 
            while self ._listening :
                await asyncio .sleep (1.0 )
            return 

        self ._listening =True 
        logger .info ("VoicePipeline: Real listen loop started. Listening for speech...")

        loop =asyncio .get_event_loop ()
        audio_queue =asyncio .Queue ()

        def callback (indata ,frames ,time ,status ):
            loop .call_soon_threadsafe (audio_queue .put_nowait ,bytes (indata ))


        try :
            stream =sd .RawInputStream (samplerate =16000 ,blocksize =480 ,dtype ='int16',channels =1 ,callback =callback )
            with stream :
                buffer =[]
                silence_frames =0 
                is_recording =False 

                while self ._listening :
                    try :
                        chunk =await asyncio .wait_for (audio_queue .get (),timeout =1.0 )
                    except asyncio .TimeoutError :
                        continue 

                    is_speech =self .vad .process (chunk )

                    if is_speech :
                        if not is_recording :
                            self .interrupt ()
                            is_recording =True 
                            buffer =[]
                            logger .info ("VoicePipeline: Interrupted! Listening to user...")
                        buffer .append (chunk )
                        silence_frames =0 
                    elif is_recording :
                        buffer .append (chunk )
                        silence_frames +=1 

                        if silence_frames >33 :
                            is_recording =False 
                            logger .info ("VoicePipeline: Speech ended, processing STT...")

                            audio_data =b''.join (buffer )
                            audio_np =np .frombuffer (audio_data ,dtype =np .int16 ).astype (np .float32 )/32768.0 


                            if len (audio_np )>8000 :
                                text =await loop .run_in_executor (None ,self .stt .transcribe ,audio_np )
                                if text and self .agent_callback :
                                    asyncio .create_task (self .agent_callback (text ))
        except Exception as e :
            logger .error (f"Error in listen loop: {e }")

    def stop_listening (self ):
        self ._listening =False 

    async def speak (self ,text :str ,viseme_callback =None ):
        self .reset_interrupt ()
        audio ,visemes =await self .tts .synthesize (text )

        if viseme_callback and visemes :
            asyncio .create_task (viseme_callback (visemes ))

        if self ._interrupt_event .is_set ():
            return 

        self .player .play (audio )
        duration =len (audio )/16000.0 

        try :
            await asyncio .wait_for (self ._interrupt_event .wait (),timeout =duration )
        except asyncio .TimeoutError :
            pass 
        finally :
            self .player .stop ()

    def interrupt (self ):
        self ._interrupt_event .set ()
        self .player .stop ()

    def reset_interrupt (self ):
        self ._interrupt_event .clear ()

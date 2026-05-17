"""
TTS — Text-to-Speech with pluggable engines.
Supports edge-tts (cloud) and openvoice (local voice cloning).
"""
import os 
import shutil 
import asyncio 
import tempfile 
import edge_tts 
import numpy as np 
import subprocess 
from scipy .io import wavfile 
import logging 

logger =logging .getLogger (__name__ )


class TTS :
    def __init__ (self ,voice ="en-US-AriaNeural",engine ="edge-tts"):
        self .voice =voice 
        self .engine =engine 
        self ._ov_engine =None 
        self ._has_ffmpeg =shutil .which ("ffmpeg")is not None 
        if not self ._has_ffmpeg :
            logger .warning ("ffmpeg not found. Edge-TTS will fail. Install ffmpeg.")

    def _get_openvoice (self ):
        """Lazy-load the OpenVoice engine on first use."""
        if self ._ov_engine is None :
            from .openvoice_engine import OpenVoiceEngine 
            self ._ov_engine =OpenVoiceEngine ()
        return self ._ov_engine 

    async def synthesize (self ,text :str ,ref_audio :str =None )->tuple :
        """Synthesizes text and returns audio (float32) and visemes.

        For edge-tts: returns 16kHz audio.
        For openvoice: returns audio at converter sample rate (22050Hz).
        """
        if not text .strip ():
            return np .zeros (0 ,dtype =np .float32 ),[]

        if self .engine =="openvoice":
            return await self ._synthesize_openvoice (text ,ref_audio )
        else :
            return await self ._synthesize_edge_tts (text )

    async def _synthesize_edge_tts (self ,text :str )->tuple :
        """Cloud TTS via edge-tts."""
        fd_mp3 ,temp_mp3 =tempfile .mkstemp (suffix =".mp3")
        fd_wav ,temp_wav =tempfile .mkstemp (suffix =".wav")
        os .close (fd_mp3 )
        os .close (fd_wav )

        try :
            communicate =edge_tts .Communicate (text ,self .voice )
            await communicate .save (temp_mp3 )

            subprocess .run ([
            "ffmpeg","-y","-i",temp_mp3 ,
            "-ar","16000","-ac","1",temp_wav 
            ],stdout =subprocess .DEVNULL ,stderr =subprocess .DEVNULL ,check =True )

            sample_rate ,data =wavfile .read (temp_wav )

            if data .dtype ==np .int16 :
                audio_np =data .astype (np .float32 )/32768.0 
            else :
                audio_np =data .astype (np .float32 )

            visemes =["A"]*(len (text )//2 )
            return audio_np ,visemes 

        except Exception as e :
            logger .error (f"TTS Error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[]

        finally :
            for p in (temp_mp3 ,temp_wav ):
                try :
                    os .remove (p )
                except OSError :
                    pass 

    async def _synthesize_openvoice (self ,text :str ,ref_audio :str =None )->tuple :
        """Local voice cloning via OpenVoice (runs in thread executor)."""
        ov =self ._get_openvoice ()

        if not ref_audio :
            logger .error ("OpenVoice requires a reference audio path")
            return np .zeros (0 ,dtype =np .float32 ),[]

        try :
            loop =asyncio .get_event_loop ()
            audio_np ,sr =await loop .run_in_executor (
            None ,ov .synthesize ,text ,ref_audio 
            )
            visemes =["A"]*(len (text )//2 )
            return audio_np ,visemes 

        except Exception as e :
            logger .error (f"OpenVoice TTS Error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[]

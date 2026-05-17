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
        self ._lock =asyncio .Lock ()
        if not self ._has_ffmpeg :
            logger .warning ("ffmpeg not found. Edge-TTS will fail. Install ffmpeg.")

    def _get_openvoice (self ):
        """Lazy-load the OpenVoice engine on first use."""
        if self ._ov_engine is None :
            from .openvoice_engine import OpenVoiceEngine 
            self ._ov_engine =OpenVoiceEngine ()
        return self ._ov_engine 

    def get_openvoice_loaded (self ):
        """Force-load OpenVoice engine (for startup preload)."""
        ov =self ._get_openvoice ()
        ov ._ensure_loaded ()
        return True 

    async def synthesize (self ,text :str ,ref_audio :str =None )->tuple :
        """Synthesizes text and returns audio (float32), visemes, and sample rate.

        For edge-tts: returns 16kHz audio.
        For openvoice: returns audio at converter sample rate (22050Hz).
        Falls back to edge-tts if openvoice fails.
        Serialized via lock to prevent concurrent model access.
        Returns: (audio_np, visemes, sample_rate)
        """
        if not text .strip ():
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        async with self ._lock :
            if self .engine =="openvoice":
                audio ,visemes =await self ._synthesize_openvoice (text ,ref_audio )
                if len (audio )>0 :
                    return audio ,visemes ,22050 

                logger .warning ("OpenVoice failed, falling back to edge-tts")
                audio ,visemes =await self ._synthesize_edge_tts (text )
                return audio ,visemes ,16000 
            else :
                audio ,visemes =await self ._synthesize_edge_tts (text )
                return audio ,visemes ,16000 

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
            logger .error (f"Edge-TTS Error: {type (e ).__name__ }: {e }")
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
            result =await loop .run_in_executor (
            None ,ov .synthesize ,text ,ref_audio 
            )
            if not result or not isinstance (result ,tuple )or len (result )<2 :
                logger .error (f"OpenVoice returned invalid result: {type (result )}")
                return np .zeros (0 ,dtype =np .float32 ),[]
            audio_np ,sr =result 
            if not isinstance (audio_np ,np .ndarray ):
                audio_np =np .array (audio_np ,dtype =np .float32 )if audio_np is not None else np .zeros (0 ,dtype =np .float32 )
            logger .info (f"OpenVoice synthesized: {len (audio_np )} samples, sr={sr }")
            visemes =["A"]*(len (text )//2 )
            return audio_np ,visemes 

        except Exception as e :
            logger .error (f"OpenVoice TTS Error: {type (e ).__name__ }: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[]

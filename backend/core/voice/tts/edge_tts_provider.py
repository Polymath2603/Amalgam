import os 
import shutil 
import asyncio 
import tempfile 
import logging 

import edge_tts 
import numpy as np 
from scipy .io import wavfile 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class EdgeTTSProvider (TTSProvider ):
    """Cloud TTS via Microsoft Edge TTS."""

    FALLBACK_VOICE ="en-US-AriaNeural"

    EMOTION_SSML ={
    "happy":{"rate":"+10%","pitch":"+2st"},
    "sad":{"rate":"-5%","pitch":"-2st"},
    "angry":{"rate":"+5%","pitch":"+3st"},
    "surprised":{"rate":"+10%","pitch":"+3st"},
    "thinking":{"rate":"0%","pitch":"0st"},
    "relaxed":{"rate":"-5%","pitch":"-2st"},
    "confused":{"rate":"0%","pitch":"0st"},
    "shy":{"rate":"-5%","pitch":"-1st"},
    "excited":{"rate":"+10%","pitch":"+4st"},
    "love":{"rate":"-3%","pitch":"+2st"},
    "victory":{"rate":"+10%","pitch":"+3st"},
    }

    def __init__ (self ,voice ="en-US-AriaNeural"):
        super ().__init__ (voice )
        self ._has_ffmpeg =shutil .which ("ffmpeg")is not None 
        if not self ._has_ffmpeg :
            logger .warning ("ffmpeg not found. Edge-TTS will fail. Install ffmpeg.")
        self ._valid_voices =None 

    async def _ensure_valid_voice (self ):
        if self ._valid_voices is None :
            try :
                voices =await edge_tts .list_voices ()
                self ._valid_voices ={v ['ShortName']for v in voices }
            except Exception as e :
                logger .warning ("Failed to fetch Edge-TTS voices: %s",e )
                self ._valid_voices =set ()
        if self .voice not in self ._valid_voices :
            logger .warning (f"Edge-TTS voice '{self .voice }' not available, falling back to '{self .FALLBACK_VOICE }'")
            self .voice =self .FALLBACK_VOICE 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        if not text .strip ():
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        await self ._ensure_valid_voice ()

        fd_mp3 ,temp_mp3 =tempfile .mkstemp (suffix =".mp3")
        fd_wav ,temp_wav =tempfile .mkstemp (suffix =".wav")
        os .close (fd_mp3 )
        os .close (fd_wav )

        try :
            prosody =self .EMOTION_SSML .get (emotion )
            if prosody :
                ssml =f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"><prosody rate="{prosody ["rate"]}" pitch="{prosody ["pitch"]}">{text }</prosody></speak>'
                communicate =edge_tts .Communicate (ssml ,self .voice )
            else :
                communicate =edge_tts .Communicate (text ,self .voice )
            await communicate .save (temp_mp3 )

            proc =await asyncio .create_subprocess_exec (
            "ffmpeg","-y","-i",temp_mp3 ,
            "-ar","16000","-ac","1",temp_wav ,
            stdout =asyncio .subprocess .DEVNULL ,stderr =asyncio .subprocess .DEVNULL 
            )
            await proc .wait ()
            if proc .returncode !=0 :
                logger .error (f"ffmpeg failed with code {proc .returncode }")
                return np .zeros (0 ,dtype =np .float32 ),[]

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

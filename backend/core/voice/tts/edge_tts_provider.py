import os 
import shutil 
import asyncio 
import tempfile 
import logging 

try:
    import edge_tts 
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    _EDGE_TTS_AVAILABLE = False

import numpy as np 
from scipy .io import wavfile 

from .base import TTSProvider 
from .word_to_viseme import viseme_schedule_from_words 

logger =logging .getLogger (__name__ )

TICKS_PER_SECOND =10_000_000 


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
        if not _EDGE_TTS_AVAILABLE :
            logger .warning ("edge_tts package not installed. TTS will fail. Install with: pip install edge-tts")
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

        if not _EDGE_TTS_AVAILABLE :
            logger .warning (f"edge_tts not installed — skipping TTS for: {text[:40]}...")
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
                communicate =edge_tts .Communicate (ssml ,self .voice ,boundary ="WordBoundary")
            else :
                communicate =edge_tts .Communicate (text ,self .voice ,boundary ="WordBoundary")

            audio_chunks =[]
            word_events =[]
            async for chunk in communicate .stream ():
                if chunk ["type"]=="audio":
                    audio_chunks .append (chunk ["data"])
                elif chunk ["type"]=="WordBoundary":
                    word_events .append ({
                    "text":chunk ["text"],
                    "offset":chunk ["offset"],
                    "duration":chunk ["duration"],
                    })

            if not audio_chunks :
                logger .error ("Edge-TTS: no audio chunks received")
                return np .zeros (0 ,dtype =np .float32 ),[],16000 

            with open (temp_mp3 ,"wb")as f :
                for c in audio_chunks :
                    f .write (c )

            proc =await asyncio .create_subprocess_exec (
            "ffmpeg","-y","-i",temp_mp3 ,
            "-ar","16000","-ac","1",temp_wav ,
            stdout =asyncio .subprocess .DEVNULL ,stderr =asyncio .subprocess .DEVNULL 
            )
            await proc .wait ()
            if proc .returncode !=0 :
                logger .error (f"ffmpeg failed with code {proc .returncode }")
                return np .zeros (0 ,dtype =np .float32 ),[],16000 

            sample_rate ,data =wavfile .read (temp_wav )
            if data .dtype ==np .int16 :
                audio_np =data .astype (np .float32 )/32768.0 
            else :
                audio_np =data .astype (np .float32 )

            word_boundaries =[]
            for ev in word_events :
                start_sec =ev ["offset"]/TICKS_PER_SECOND 
                end_sec =(ev ["offset"]+ev ["duration"])/TICKS_PER_SECOND 
                word_boundaries .append ({
                "text":ev ["text"],
                "start":start_sec ,
                "end":end_sec ,
                })

            viseme_schedule =viseme_schedule_from_words (word_boundaries )
            logger .debug (f"Edge-TTS: {len (audio_np )} samples, {len (viseme_schedule )} visemes")
            return audio_np ,viseme_schedule ,sample_rate 

        except Exception as e :
            logger .error (f"Edge-TTS Error: {type (e ).__name__ }: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        finally :
            for p in (temp_mp3 ,temp_wav ):
                try :
                    os .remove (p )
                except OSError :
                    pass 

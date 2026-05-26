"""
TTS preview API routes.
"""
import os 
import base64 
import struct 
import logging 

from fastapi import APIRouter 
from backend .api .deps import settings 
from backend .core .voice .tts import TTS 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["tts"])


@router .post ("/api/tts/preview")
async def tts_preview (body :dict ):
    text =body .get ("text","Hello, I am your assistant.")
    engine =settings ().get ("voice.engine","edge-tts")
    char =settings ().get_active_character ()

    if engine =="openvoice":
        ref_audio =char .get ("voice_ref")if char else None 
        if not ref_audio :
            char_dir =char .get ("_dir","")if char else ""
            if char_dir :
                for name in ("voice.pth","voice.wav"):
                    candidate =os .path .join (char_dir ,name )
                    if os .path .exists (candidate ):
                        ref_audio =candidate 
                        break 
        if not ref_audio :
            return {"audio":None ,"error":"No voice_ref set. Place a voice.pth or voice.wav in the character directory."}
        temp_tts =TTS (engine ="openvoice")
        audio ,_ ,sr =await temp_tts .synthesize (text ,ref_audio =ref_audio )
    else :
        voice =char .get ("voice","en-US-AriaNeural")if char else "en-US-AriaNeural"
        temp_tts =TTS (voice =voice )
        audio ,_ ,sr =await temp_tts .synthesize (text )

    if len (audio )>0 :
        pcm =(audio *32767 ).astype ("int16").tobytes ()
        nch =1 
        bps =16 
        data_size =len (pcm )
        header =struct .pack ('<4sI4s4sIHHIIHH4sI',
        b'RIFF',36 +data_size ,b'WAVE',
        b'fmt ',16 ,1 ,nch ,sr ,sr *nch *bps //8 ,nch *bps //8 ,bps ,
        b'data',data_size )
        wav_bytes =header +pcm 
        b64 =base64 .b64encode (wav_bytes ).decode ()
        return {"audio":b64 ,"format":"wav"}
    return {"audio":None }

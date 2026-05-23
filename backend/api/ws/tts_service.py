"""
TTS synthesis service — module-level functions for sentence streaming and direct speak.
Extracted from server.py to avoid re-creating closures per message.
"""
import asyncio 
import base64 
import struct 
import os 
import logging 

from fastapi import WebSocket 
from backend .api .deps import tts ,settings 

logger =logging .getLogger (__name__ )


_ws_stream_idx =0 


async def synthesize_sentence (sentence_text :str ,sentence_idx :int ,stream_id :int ,
ws :WebSocket ,emotion :str ="neutral"):
    """TTS a single sentence and send audio over WebSocket."""
    global _ws_stream_idx 
    try :
        if stream_id !=_ws_stream_idx :
            logger .debug (f"TTS sentence {sentence_idx }: skipped (stale stream)")
            return 
        char =settings ().get_active_character ()
        ref_audio =None 
        if tts ().engine =="openvoice":
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
                logger .warning ("No voice_ref for OpenVoice, skipping TTS")
                return 
        result =await asyncio .wait_for (
        tts ().synthesize (sentence_text ,ref_audio =ref_audio ,emotion =emotion ),
        timeout =60.0 
        )
        audio_np ,_ ,sr =result 
        logger .debug (f"TTS sentence {sentence_idx }: {len (audio_np )} samples, sr={sr }")
        if len (audio_np )>0 :
            pcm =(audio_np *32767 ).astype ("int16").tobytes ()
            data_size =len (pcm )
            header =struct .pack (
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',36 +data_size ,b'WAVE',
            b'fmt ',16 ,1 ,1 ,sr ,sr *1 *16 //8 ,
            1 *16 //8 ,16 ,
            b'data',data_size 
            )
            wav_bytes =header +pcm 
            b64_audio =base64 .b64encode (wav_bytes ).decode ()
            duration =len (audio_np )/sr 
            await ws .send_json ({
            "type":"tts_audio",
            "audio":b64_audio ,
            "format":"wav",
            "duration":round (duration ,2 ),
            "sentence_idx":sentence_idx ,
            "emotion":emotion 
            })
            logger .debug (f"TTS sentence {sentence_idx }: sent {duration :.2f}s audio (emotion={emotion })")
        else :
            logger .warning (f"TTS sentence {sentence_idx }: empty audio")
    except asyncio .TimeoutError :
        logger .error (f"TTS sentence {sentence_idx }: timed out after 60s")
    except Exception as tts_err :
        logger .error (f"TTS error for sentence {sentence_idx }: {type (tts_err ).__name__ }: {tts_err }")


async def synthesize_now (text :str ,ws :WebSocket ,emotion :str ="neutral"):
    """Synthesize TTS for text and send audio directly (used by speak button)."""
    try :
        char =settings ().get_active_character ()
        ref_audio =None 
        if tts ().engine =="openvoice":
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
                logger .warning ("No voice_ref for OpenVoice, skipping speak")
                return 
        result =await asyncio .wait_for (tts ().synthesize (text ,ref_audio =ref_audio ,emotion =emotion ),timeout =60.0 )
        audio_np ,_ ,sr =result 
        if len (audio_np )>0 :
            pcm =(audio_np *32767 ).astype ("int16").tobytes ()
            data_size =len (pcm )
            header =struct .pack (
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',36 +data_size ,b'WAVE',
            b'fmt ',16 ,1 ,1 ,sr ,sr *1 *16 //8 ,
            1 *16 //8 ,16 ,
            b'data',data_size 
            )
            wav_bytes =header +pcm 
            b64_audio =base64 .b64encode (wav_bytes ).decode ()
            duration =len (audio_np )/sr 
            await ws .send_json ({
            "type":"tts_audio","audio":b64_audio ,"format":"wav",
            "duration":round (duration ,2 ),"sentence_idx":0 ,"emotion":"neutral"
            })
            logger .debug (f"Speak TTS: sent {duration :.2f}s audio")
        else :
            logger .warning ("Speak TTS: empty audio")
    except asyncio .TimeoutError :
        logger .error ("Speak TTS: timed out")
    except Exception as e :
        logger .error (f"Speak TTS error: {e }")


def get_stream_idx ()->int :
    global _ws_stream_idx 
    return _ws_stream_idx 


def set_stream_idx (val :int ):
    global _ws_stream_idx 
    _ws_stream_idx =val 


def increment_stream_idx ()->int :
    global _ws_stream_idx 
    _ws_stream_idx +=1 
    return _ws_stream_idx 

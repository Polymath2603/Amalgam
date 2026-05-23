"""
Settings API routes — /api/settings
"""
import logging 

from fastapi import APIRouter 
from backend .api .deps import settings ,llm ,tts ,agent 
from backend .config .settings import BUILTIN_VOICES 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["settings"])


def _sync_emotion_tags ():
    """Sync TTS engine's supported emotions to the agent."""
    if agent ()and tts ():
        supported =tts ().get_supported_emotions ()
        agent ().update_emotion_tags (supported if supported else agent ()._emotion_tags )


@router .get ("/api/settings")
async def get_settings ():
    return settings ().get_all ()


@router .post ("/api/settings")
async def update_settings (body :dict ):
    settings ().update_all (body )
    llm ().reload_settings ()
    engine =settings ().get ("voice.engine","edge-tts")
    tts ().engine =engine 

    if engine =="elevenlabs":
        elevenlabs_key =settings ().get ("voice.elevenlabs.api_key","")
        if elevenlabs_key :
            elevenlabs_model =settings ().get ("voice.elevenlabs.model","eleven_multilingual_v2")
            tts ().configure_elevenlabs (elevenlabs_key ,elevenlabs_model )
    elif engine =="openai-tts":
        oa_key =settings ().get ("voice.openai_tts.api_key","")
        oa_model =settings ().get ("voice.openai_tts.model","tts-1")
        oa_url =settings ().get ("voice.openai_tts.base_url",None )
        if oa_key :
            tts ().configure_openai_tts (oa_key ,oa_model ,oa_url )
    elif engine =="alltalk":
        url =settings ().get ("voice.alltalk.url",None )
        lang =settings ().get ("voice.alltalk.language","en")
        ver =settings ().get ("voice.alltalk.version","v2")
        rv =settings ().get ("voice.alltalk.rvc_voice","")
        rp =settings ().get ("voice.alltalk.rvc_pitch","0")
        tts ().configure_alltalk (url ,lang ,ver ,rv ,rp )
    elif engine =="piper":
        url =settings ().get ("voice.piper.url",None )
        tts ().configure_piper (url )
    elif engine =="coqui-local":
        url =settings ().get ("voice.coqui_local.url",None )
        sid =settings ().get ("voice.coqui_local.speaker_id","")
        tts ().configure_coqui (url ,sid )
    elif engine =="kokoro":
        url =settings ().get ("voice.kokoro.url",None )
        tts ().configure_kokoro (url )
    _sync_emotion_tags ()
    agent ().update_settings (settings ())

    if "character"in body and "active"in body ["character"]:
        char_id =body ["character"]["active"]
        chars =settings ().get_characters ()
        if char_id in chars :
            logger .debug (f"Character switched to {chars [char_id ].get ('name',char_id )}")

    return {"status":"ok","voice":tts ().voice }


@router .post ("/api/settings/set")
async def set_setting (body :dict ):
    key =body .get ("key")
    value =body .get ("value")
    if key :
        settings ().set (key ,value )
        llm ().reload_settings ()
        _sync_emotion_tags ()
        agent ().update_settings (settings ())
    return {"status":"ok"}

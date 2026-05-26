"""
Settings API routes — /api/settings
"""
import logging 

from fastapi import APIRouter 
from backend .api .deps import settings ,llm ,tts ,agent 
from backend .core .config .settings import BUILTIN_VOICES 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["settings"])


def _sync_emotion_tags ():
    """No-op — avatar emotion is now controlled via MCP tools, not tags."""


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
    elif engine =="azure":
        api_key =settings ().get ("voice.azure.api_key","")
        region =settings ().get ("voice.azure.region","eastus")
        if api_key :
            tts ().configure_azure (api_key ,region )
    elif engine =="dashscope":
        api_key =settings ().get ("voice.dashscope.api_key","")
        model =settings ().get ("voice.dashscope.model","cosyvoice-v1")
        if api_key :
            tts ().configure_dashscope (api_key ,model )
    elif engine =="volcengine":
        app_id =settings ().get ("voice.volcengine.app_id","")
        access_token =settings ().get ("voice.volcengine.access_token","")
        cluster =settings ().get ("voice.volcengine.cluster","volcano_tts")
        if app_id and access_token :
            tts ().configure_volcengine (app_id ,access_token ,cluster )
    elif engine =="deepgram":
        api_key =settings ().get ("voice.deepgram.api_key","")
        model =settings ().get ("voice.deepgram.model","aura-2")
        if api_key :
            tts ().configure_deepgram (api_key ,model )
    elif engine =="mlx":
        pass 
    elif engine =="rvc":
        url =settings ().get ("voice.rvc.url",None )
        f0_up_key =settings ().get ("voice.rvc.f0_up_key",0 )
        f0_method =settings ().get ("voice.rvc.f0_method","rmvpe")
        tts ().engine =settings ().get ("voice.engine","edge-tts")
        tts ().configure_rvc (url ,f0_up_key ,f0_method )
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


@router .post ("/api/settings/batch")
async def batch_set_settings (body :dict ):
    """Set multiple settings at once via key-value pairs.
    Body: {"settings": {"voice.engine": "edge-tts", "provider.active": "ollama", ...}}
    """
    pairs =body .get ("settings",{})
    s =settings ()
    for key ,value in pairs .items ():
        s .set (key ,value )
    llm ().reload_settings ()
    _sync_emotion_tags ()
    agent ().update_settings (s )
    return {"status":"ok","count":len (pairs )}

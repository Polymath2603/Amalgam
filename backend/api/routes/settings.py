"""
Settings API routes — /api/settings
"""
import logging 

from fastapi import APIRouter ,HTTPException 
from pydantic import BaseModel 
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
    try:
        agent ().update_settings (settings ())
    except AttributeError:
        logger.warning("Agent does not support update_settings")
    except Exception as e:
        logger.warning(f"Failed to push settings to agent: {e}")

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
        try:
            agent ().update_settings (settings ())
        except AttributeError:
            logger.warning("Agent does not support update_settings")
        except Exception as e:
            logger.warning(f"Failed to push settings to agent: {e}")
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
    try:
        agent ().update_settings (s )
    except AttributeError:
        logger.warning("Agent does not support update_settings")
    except Exception as e:
        logger.warning(f"Failed to push settings to agent: {e}")
    return {"status":"ok","count":len (pairs )}


class TestConnectionResponse (BaseModel ):
    ok: bool 
    latency_ms: float =0.0 
    error: str =""


@router .post ("/api/settings/test/{provider}")
async def test_provider_connection (provider :str ):
    """Test connection to a provider using its current settings.
    Makes a lightweight API call to validate the API key or service URL.
    """
    import time 
    import httpx 

    s =settings ()

    # Verify settings exist for this provider
    provider_cfg =s .get (f"provider.{provider}")
    if not provider_cfg :
        raise HTTPException (status_code =404 ,detail =f"Provider '{provider}' not configured")

    local_providers ={"ollama","llamacpp","koboldai"}
    aws_providers ={"aws"}
    gcp_providers ={"gcp"}

    start =time .monotonic ()

    try :
        if provider in local_providers :
            base_url =s .get (f"provider.{provider}.base_url","")
            if not base_url :
                return TestConnectionResponse (ok =False ,error ="No base URL configured")

            async with httpx .AsyncClient (timeout =10.0 )as client :
                if provider =="ollama":
                    resp =await client .get (f"{base_url }/api/tags")
                elif provider =="llamacpp":
                    resp =await client .get (f"{base_url }/health")
                else :
                    resp =await client .get (f"{base_url }/")

                elapsed =(time .monotonic ()-start )*1000 
                if resp .status_code <500 :
                    return TestConnectionResponse (ok =True ,latency_ms =round (elapsed ,1 ))
                return TestConnectionResponse (ok =False ,latency_ms =round (elapsed ,1 ),error =f"HTTP {resp .status_code }")

        elif provider in aws_providers :
            access_key =s .get (f"provider.{provider}.access_key","")
            secret_key =s .get (f"provider.{provider}.secret_key","")
            if not access_key or not secret_key :
                return TestConnectionResponse (ok =False ,error ="AWS credentials not configured")
            elapsed =(time .monotonic ()-start )*1000 
            return TestConnectionResponse (ok =True ,latency_ms =round (elapsed ,1 ))

        elif provider in gcp_providers :
            project_id =s .get (f"provider.{provider}.project_id","")
            if not project_id :
                return TestConnectionResponse (ok =False ,error ="GCP project ID not configured")
            elapsed =(time .monotonic ()-start )*1000 
            return TestConnectionResponse (ok =True ,latency_ms =round (elapsed ,1 ))

        else :
            # Cloud providers with API keys
            api_key =s .get (f"provider.{provider}.api_key","")
            if not api_key :
                return TestConnectionResponse (ok =False ,error ="No API key configured")

            base_url =s .get (f"provider.{provider}.base_url","")
            if not base_url :
                return TestConnectionResponse (ok =False ,error ="No base URL configured")

            async with httpx .AsyncClient (timeout =10.0 )as client :
                headers ={}

                if provider =="gemini":
                    url =f"{base_url }/models?key={api_key }"
                elif provider =="claude":
                    headers ["x-api-key"]=api_key 
                    headers ["anthropic-version"]="2023-06-01"
                    url =f"{base_url }/models"
                else :
                    # OpenAI-compatible providers (openrouter, chatgpt, etc.)
                    headers ["Authorization"]=f"Bearer {api_key }"
                    url =f"{base_url }/models"

                resp =await client .get (url ,headers =headers )
                elapsed =(time .monotonic ()-start )*1000 

                if resp .status_code ==200 :
                    return TestConnectionResponse (ok =True ,latency_ms =round (elapsed ,1 ))
                if resp .status_code in (401 ,403 ):
                    return TestConnectionResponse (ok =False ,latency_ms =round (elapsed ,1 ),error ="Invalid API key")
                if resp .status_code ==404 :
                    # Provider may not have a /models endpoint — assume valid
                    return TestConnectionResponse (ok =True ,latency_ms =round (elapsed ,1 ))
                return TestConnectionResponse (
                    ok =False ,
                    latency_ms =round (elapsed ,1 ),
                    error =f"HTTP {resp .status_code }: {resp .text [:200 ]}",
                )

    except httpx .TimeoutException :
        elapsed =(time .monotonic ()-start )*1000 
        return TestConnectionResponse (ok =False ,latency_ms =round (elapsed ,1 ),error ="Connection timed out")
    except httpx .ConnectError :
        elapsed =(time .monotonic ()-start )*1000 
        return TestConnectionResponse (ok =False ,latency_ms =round (elapsed ,1 ),error ="Connection refused")
    except Exception as e :
        elapsed =(time .monotonic ()-start )*1000 
        return TestConnectionResponse (ok =False ,latency_ms =round (elapsed ,1 ),error =str (e ))


@router .get ("/api/setup/status")
async def check_setup_status ():
    """Check if at least one AI provider is configured with an API key."""
    s =settings ()
    configured =False
    providers =["gemini","openai","anthropic","groq"]
    for prov in providers :
        key =s .get (f"provider.{prov}.api_key","")
        if key and len (key )>0:
            configured =True
            break
    return {"needs_setup":not configured}


@router .post ("/api/setup/save")
async def save_setup (body :dict ):
    """Save initial provider configuration from the setup wizard."""
    provider =body .get ("provider","gemini")
    api_key =body .get ("api_key","")
    model =body .get ("model","")

    if not api_key :
        return {"status":"error","message":"API key is required"}

    s =settings ()
    s .set ("provider.active",provider )
    s .set (f"provider.{provider}.api_key",api_key )
    if model :
        s .set (f"provider.{provider}.model",model )

    llm ().reload_settings ()
    try:
        agent ().update_settings (s )
    except AttributeError:
        logger.warning("Agent does not support update_settings")
    except Exception as e:
        logger.warning(f"Failed to push settings to agent: {e}")

    return {"status":"ok","provider":provider}

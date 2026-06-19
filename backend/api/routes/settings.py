"""
Settings API routes — /api/settings
"""
import logging 

from typing import Any
from fastapi import APIRouter ,HTTPException 
from pydantic import BaseModel 
from backend .api .deps import settings ,llm ,tts ,agent 
from backend .core .config .settings import BUILTIN_VOICES 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["settings"])

# Map display provider IDs to internal settings keys
PROVIDER_KEY_MAP = {
    "openai": "chatgpt",
    "anthropic": "claude",
}

# Known provider keys for validation
VALID_PROVIDERS = {"gemini", "ollama", "openrouter", "zai", "siliconflow", "groq",
                   "chatgpt", "claude", "llamacpp", "koboldai",
                   "deepseek", "mistral", "together", "azure-openai",
                   "alibaba", "huggingface", "aws", "gcp"}

VALID_TTS_ENGINES = {"edge-tts", "openvoice", "elevenlabs", "openai-tts", "speecht5",
                     "alltalk", "piper", "coqui-local", "kokoro", "azure",
                     "dashscope", "volcengine", "deepgram", "mlx", "rvc"}

VALID_STT_ENGINES = {"browser", "faster-whisper", "openai-whisper", "groq-whisper", "whispercpp"}

VALID_PROFILES = {"default", "token-friendly", "quality", "custom"}

def _validate_settings_update(body: dict) -> list[str]:
    """Validate settings update body. Returns list of error messages (empty = valid)."""
    errors = []
    
    for key, value in body.items():
        # Validate provider.active
        if key == "provider.active" and value not in VALID_PROVIDERS:
            errors.append(f"Unknown provider: {value}")
        
        # Validate voice.engine
        if key == "voice.engine" and value not in VALID_TTS_ENGINES:
            errors.append(f"Unknown TTS engine: {value}")
        
        # Validate voice.stt_engine
        if key == "voice.stt_engine" and value not in VALID_STT_ENGINES:
            errors.append(f"Unknown STT engine: {value}")
        
        # Validate profile
        if key == "profile" and value not in VALID_PROFILES:
            errors.append(f"Unknown profile: {value}. Valid: {', '.join(sorted(VALID_PROFILES))}")
        
        # Validate API key format (basic sanity)
        if key.endswith("api_key") and value:
            if not isinstance(value, str):
                errors.append(f"API key must be a string")
            elif len(value) < 8:
                errors.append(f"API key looks too short ({len(value)} chars)")
        
        # Validate numeric fields
        if key in ("llm.temperature",) and value is not None:
            try:
                v = float(value)
                if v < 0 or v > 2:
                    errors.append(f"{key} must be between 0 and 2")
            except (ValueError, TypeError):
                errors.append(f"{key} must be a number")
        
        if key in ("ui.font_size",) and value is not None:
            try:
                v = int(value)
                if v < 8 or v > 48:
                    errors.append(f"{key} must be between 8 and 48")
            except (ValueError, TypeError):
                errors.append(f"{key} must be a number")
    
    return errors

def _settings_key(provider_id: str) -> str:
    """Map a provider ID to the internal settings key."""
    return PROVIDER_KEY_MAP.get(provider_id, provider_id)


# ── Pydantic request models ───────────────────────────────────────

class SetSettingRequest(BaseModel):
    """Validated request body for POST /api/settings/set."""
    key: str
    value: Any = None


class BatchSettingsRequest(BaseModel):
    """Validated request body for POST /api/settings/batch."""
    settings: dict[str, Any]


def _sync_emotion_tags ():
    """No-op — avatar emotion is now controlled via MCP tools, not tags."""


@router .get ("/api/settings")
async def get_settings ():
    return settings ().get_all ()


@router .post ("/api/settings")
async def update_settings (body :dict ):
    # Validate input
    errors = _validate_settings_update(body)
    if errors:
        return {"status":"error","errors":errors,"voice":tts ().voice }
    
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
async def set_setting (body :SetSettingRequest ):
    key =body .key
    value =body .value
    if key :
        # Validate single setting
        errors = _validate_settings_update({key: value})
        if errors:
            return {"status":"error","errors":errors}
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
async def batch_set_settings (body :BatchSettingsRequest ):
    """Set multiple settings at once via key-value pairs.
    Body: {"settings": {"voice.engine": "edge-tts", "provider.active": "ollama", ...}}
    """
    pairs =body .settings
    # Validate all pairs
    errors = _validate_settings_update(pairs)
    if errors:
        return {"status":"error","errors":errors,"count":0 }
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


@router .get ("/api/settings/get/{key:path}")
async def get_setting (key: str ):
    """Get a single setting value by dot-notation key."""
    s =settings ()
    value =s .get (key )
    return {"key":key ,"value":value }


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
    provider_key =_settings_key (provider )

    # Verify settings exist for this provider
    provider_cfg =s .get (f"provider.{provider_key}")
    if not provider_cfg :
        raise HTTPException (status_code =404 ,detail =f"Provider '{provider}' not configured")

    local_providers ={"ollama","llamacpp","koboldai"}
    aws_providers ={"aws"}
    gcp_providers ={"gcp"}

    start =time .monotonic ()

    try :
        if provider_key in local_providers :
            base_url =s .get (f"provider.{provider_key}.base_url","")
            if not base_url :
                return TestConnectionResponse (ok =False ,error ="No base URL configured")

            async with httpx .AsyncClient (timeout =10.0 )as client :
                if provider_key =="ollama":
                    resp =await client .get (f"{base_url }/api/tags")
                elif provider_key =="llamacpp":
                    resp =await client .get (f"{base_url }/health")
                else :
                    resp =await client .get (f"{base_url }/")

                elapsed =(time .monotonic ()-start )*1000 
                if resp .status_code <500 :
                    return TestConnectionResponse (ok =True ,latency_ms =round (elapsed ,1 ))
                return TestConnectionResponse (ok =False ,latency_ms =round (elapsed ,1 ),error =f"HTTP {resp .status_code }")

        elif provider_key in aws_providers :
            access_key =s .get (f"provider.{provider_key}.access_key","")
            secret_key =s .get (f"provider.{provider_key}.secret_key","")
            if not access_key or not secret_key :
                return TestConnectionResponse (ok =False ,error ="AWS credentials not configured")
            elapsed =(time .monotonic ()-start )*1000 
            return TestConnectionResponse (ok =True ,latency_ms =round (elapsed ,1 ))

        elif provider_key in gcp_providers :
            project_id =s .get (f"provider.{provider_key}.project_id","")
            if not project_id :
                return TestConnectionResponse (ok =False ,error ="GCP project ID not configured")
            elapsed =(time .monotonic ()-start )*1000 
            return TestConnectionResponse (ok =True ,latency_ms =round (elapsed ,1 ))

        else :
            # Cloud providers with API keys
            api_key =s .get (f"provider.{provider_key}.api_key","")
            if not api_key :
                return TestConnectionResponse (ok =False ,error ="No API key configured")

            base_url =s .get (f"provider.{provider_key}.base_url","")
            if not base_url :
                return TestConnectionResponse (ok =False ,error ="No base URL configured")

            async with httpx .AsyncClient (timeout =10.0 )as client :
                headers ={}

                if provider_key =="gemini":
                    url =f"{base_url }/models?key={api_key }"
                elif provider_key =="claude":
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

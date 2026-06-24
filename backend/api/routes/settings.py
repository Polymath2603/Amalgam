"""
Settings API routes — /api/settings
"""
import asyncio
import logging 

from typing import Any
from fastapi import APIRouter ,HTTPException 
from pydantic import BaseModel 
from backend .api .deps import settings ,llm ,tts ,agent ,companion
from backend.core.deprecated import deprecated 

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
                   "alibaba", "huggingface", "aws", "gcp", "opencode", "opendev"}

VALID_TTS_ENGINES = {"edge-tts", "openvoice", "elevenlabs", "openai-tts", "speecht5",
                     "alltalk", "piper", "coqui-local", "kokoro", "azure",
                     "dashscope", "volcengine", "deepgram", "mlx", "rvc"}

VALID_STT_ENGINES = {"browser", "faster-whisper", "openai-whisper", "groq-whisper", "whispercpp"}

VALID_PROFILES = {"default", "token-friendly", "quality", "custom"}

def _validate_settings_update(body: dict) -> list[str]:
    """Validate settings update body. Returns list of error messages (empty = valid)."""
    errors = []
    
    # Flatten nested dicts to dot-notation for validation
    flat = {}
    for key, value in body.items():
        if isinstance(value, dict):
            for nested_key, nested_val in value.items():
                flat[f"{key}.{nested_key}"] = nested_val
        else:
            flat[key] = value
    
    for key, value in flat.items():
        if value is None or value == "":
            continue
        
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
        
        # Validate UI theme
        if key == "ui.theme" and value not in {"dark", "midnight", "light", "nord"}:
            errors.append(f"Unknown theme: {value}. Valid: dark, midnight, light, nord")
        
        # Validate agent type
        if key == "agent.type" and value not in {"basic", "reflective", "planning", "reflective_planning"}:
            errors.append(f"Unknown agent type: {value}. Valid: basic, reflective, planning, reflective_planning")
        
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
        
        # Validate wake word engine
        if key == "wake_word.engine" and value not in {"openwakeword", "snowboy", "none"}:
            errors.append(f"Unknown wake word engine: {value}. Valid: openwakeword, snowboy, none")
    
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
        try:
            elevenlabs_key =settings ().get ("voice.elevenlabs.api_key","")
            if elevenlabs_key :
                elevenlabs_model =settings ().get ("voice.elevenlabs.model","eleven_multilingual_v2")
                tts ().configure_elevenlabs (elevenlabs_key ,elevenlabs_model )
        except Exception as e:
            logger.error("Failed to configure elevenlabs: %s", e)
    elif engine =="openai-tts":
        try:
            oa_key =settings ().get ("voice.openai_tts.api_key","")
            oa_model =settings ().get ("voice.openai_tts.model","tts-1")
            oa_url =settings ().get ("voice.openai_tts.base_url",None )
            if oa_key :
                tts ().configure_openai_tts (oa_key ,oa_model ,oa_url )
        except Exception as e:
            logger.error("Failed to configure openai-tts: %s", e)
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
    # Propagate settings to TTS subsystem
    tts_obj = tts()
    if hasattr(tts_obj, 'reload_settings'):
        tts_obj.reload_settings(s)
    # Propagate to voice pipeline if voice/stt/wake_word settings changed
    voice_keys = [k for k in pairs if k.startswith('voice.') or k.startswith('stt.') or k.startswith('wake_word.')]
    if voice_keys:
        try:
            from backend.core.deps import get_voice_pipeline
            pipeline = get_voice_pipeline()
            if pipeline is not None and hasattr(pipeline, 'reconfigure'):
                pipeline.reconfigure(s)
                logger.debug(f"Voice pipeline reconfigured for keys: {voice_keys}")
        except Exception as e:
            logger.warning(f"Failed to propagate voice settings: {e}")
    # Propagate to companion
    companion_keys = [k for k in pairs if k.startswith('companion.')]
    if companion_keys:
        try:
            c = companion()
            if c and hasattr(c, 'reload_settings'):
                c.reload_settings(s)
        except Exception as e:
            logger.warning(f"Failed to propagate companion settings: {e}")
    return {"status":"ok","count":len (pairs )}


@router .get ("/api/settings/get/{key:path}")
async def get_setting (key: str ):
    """Get a single setting value by dot-notation key. Masks API keys."""
    s =settings ()
    value =s .get (key )
    # Mask API keys
    if key.endswith("api_key") or key.endswith("_key"):
        if value and isinstance(value, str):
            if len(value) < 12:
                value = "****"
            else:
                value = f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"
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
                    resp =await asyncio.wait_for(client .get (f"{base_url }/api/tags"), timeout=15.0)
                elif provider_key =="llamacpp":
                    resp =await asyncio.wait_for(client .get (f"{base_url }/health"), timeout=15.0)
                else :
                    resp =await asyncio.wait_for(client .get (f"{base_url }/"), timeout=15.0)

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

                resp =await asyncio.wait_for(client .get (url ,headers =headers ), timeout=15.0)
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

    except asyncio.TimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        return TestConnectionResponse(ok=False, latency_ms=round(elapsed, 1), error="Connection timed out")
    except httpx .TimeoutException :
        elapsed =(time .monotonic ()-start )*1000 
        return TestConnectionResponse (ok =False ,latency_ms =round (elapsed ,1 ),error ="Connection timed out")
    except httpx .ConnectError :
        elapsed =(time .monotonic ()-start )*1000 
        return TestConnectionResponse (ok =False ,latency_ms =round (elapsed ,1 ),error ="Connection refused")
    except Exception as e :
        elapsed =(time .monotonic ()-start )*1000 
        return TestConnectionResponse (ok =False ,latency_ms =round (elapsed ,1 ),error =str (e ))


@router .get ("/api/settings/safe")
@deprecated()
async def get_settings_safe ():
    """Return settings with API keys masked (first 4 + last 4 chars).

    Used by the frontend to display settings without leaking secrets.
    """
    def _mask(val: str) -> str:
        if not val or not isinstance(val, str) or len(val) < 8:
            return "****"
        return f"{val[:4]}{'*' * (len(val) - 8)}{val[-4:]}"

    raw = settings ().get_all ()
    safe = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            safe[k] = {}
            for nk, nv in v.items():
                if isinstance(nv, dict):
                    safe[k][nk] = {}
                    for ik, iv in nv.items():
                        if ik == "api_key" or (ik.endswith("_key") and isinstance(iv, str) and len(iv) >= 8):
                            safe[k][nk][ik] = _mask(str(iv))
                        else:
                            safe[k][nk][ik] = iv
                elif nk == "api_key" or (nk.endswith("_key") and isinstance(nv, str) and len(nv) >= 8):
                    safe[k][nk] = _mask(str(nv))
                else:
                    safe[k][nk] = nv
        elif k == "api_key" or (k.endswith("_key") and isinstance(v, str) and len(v) >= 8):
            safe[k] = _mask(str(v))
        else:
            safe[k] = v
    return safe


@router .post ("/api/settings/reset")
@deprecated()
async def reset_settings (target :str ="voice"):
    """Reset a settings section to defaults.

    target:
      "voice"   — reset voice engine settings
      "agent"   — reset agent type and related settings
      "ui"      — reset theme, font size, language
      "all"     — reset everything (dangerous, preserves provider keys)
    """
    from backend .core .config .settings import Settings as SettingsClass
    s = settings ()
    defaults = SettingsClass .DEFAULTS if hasattr(SettingsClass, 'DEFAULTS') else {}
    if not defaults:
        return {"status": "error", "message": "No defaults available"}

    if target == "voice":
        voice_keys = [k for k in defaults if k.startswith("voice.")]
        for k in voice_keys:
            s.set(k, defaults[k])
    elif target == "agent":
        agent_keys = [k for k in defaults if k.startswith("agent.")]
        for k in agent_keys:
            s.set(k, defaults[k])
    elif target == "ui":
        ui_keys = [k for k in defaults if k.startswith("ui.")]
        for k in ui_keys:
            s.set(k, defaults[k])
    elif target == "all":
        # Preserve all provider keys (API keys, access keys, secrets are sensitive)
        preserved = {}
        for k, v in s.get_all().items():
            if k.startswith("provider."):
                preserved[k] = v
        for k, v in defaults.items():
            s.set(k, v)
        # Restore provider keys
        for k, v in preserved.items():
            s.set(k, v)
    else:
        return {"status": "error", "message": f"Unknown target: {target}. Use voice, agent, ui, or all"}

    llm().reload_settings()
    # Propagate to TTS subsystem
    try:
        tts_obj = tts()
        if hasattr(tts_obj, 'reload_settings'):
            tts_obj.reload_settings(settings())
    except Exception as e:
        logger.warning("Failed to propagate settings to TTS: %s", e)
    return {"status": "ok", "reset": target}

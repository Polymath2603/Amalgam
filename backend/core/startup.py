"""
Shared application initialization for all frontends (webui, CLI, gRPC).
Extracted from backend/app.py startup event so CLI and other modes
get the same initialization path.
"""
import os 
import asyncio 
import logging 

from backend .core .deps import get_shared 
from backend .core .paths import VAULT_DIR 
from backend .core .config .settings import load_characters_from_yaml 

logger =logging .getLogger (__name__ )


async def init_application ():
    """Initialize all shared components. Safe to call multiple times (idempotent for singletons).

    Initializes:
      - All shared singletons (settings, llm, memory, mcp, tts, agent, etc.)
      - Vault directory and default rules.md
      - Conversation session
      - TTS engine (OpenVoice only, others are lazy)
      - MCP server connections
    """
    shared =get_shared ()
    settings =shared ["settings"]

    log_level =settings .get ("log.level","WARNING")
    log_format =settings .get ("log.format","console")
    from backend .core .log_config import configure_logging 
    configure_logging (level =log_level ,log_format =log_format )
    memory =shared ["memory"]
    mcp_client =shared ["mcp"]
    tts_engine =shared ["tts"]

    vault_path =settings .get ("vault.path",str (VAULT_DIR ))
    os .makedirs (vault_path ,exist_ok =True )
    rules_path =os .path .join (vault_path ,"rules.md")
    if not os .path .exists (rules_path ):
        with open (rules_path ,"w")as f :
            f .write ("# Rules\n\nAdd your custom rules here. These will be injected into every conversation.\n")

    memory .start_session ()

    engine =settings .get ("voice.engine","edge-tts")
    if engine =="openvoice":
        logger .debug ("Preloading OpenVoice TTS engine...")
        try :
            loop =asyncio .get_event_loop ()
            await loop .run_in_executor (None ,tts_engine .get_openvoice_loaded )
            logger .debug ("OpenVoice TTS engine ready")
        except Exception as e :
            logger .warning (f"OpenVoice preload failed: {e }")

    mcp_servers =settings .get_mcp_servers ()
    if mcp_servers :
        for s in mcp_servers :
            if s .get ("name")=="shell":
                shell_mode =settings .get ("shell.mode","safe")
                shell_prefixes =settings .get ("shell.allowed_prefixes",[])
                s .setdefault ("env",{})
                s ["env"]["AMALGAM_SHELL_MODE"]=shell_mode 
                s ["env"]["AMALGAM_SHELL_ALLOWED_COMMANDS"]=",".join (shell_prefixes )
        asyncio .create_task (mcp_client .connect_from_settings (mcp_servers ))

    settings .start_watcher ()
    settings .on_change (make_settings_reloader (mcp_client ,asyncio .get_event_loop ())) 


def make_settings_reloader (mcp_client ,loop ):
    """Return a callback that hot-reloads components when settings change."""
    from backend .core .deps import get_shared 

    def _reload (settings ):
        """Reload MCP servers and refresh character data on settings change."""
        shared =get_shared ()
        try :
            if loop and loop .is_running ():
                mcp_servers =settings .get_mcp_servers ()
                if mcp_servers :
                    for s in mcp_servers :
                        if s .get ("name")=="shell":
                            shell_mode =settings .get ("shell.mode","safe")
                            shell_prefixes =settings .get ("shell.allowed_prefixes",[])
                            s .setdefault ("env",{})
                            s ["env"]["AMALGAM_SHELL_MODE"]=shell_mode 
                            s ["env"]["AMALGAM_SHELL_ALLOWED_COMMANDS"]=",".join (shell_prefixes )
                    asyncio .run_coroutine_threadsafe (
                        mcp_client .connect_from_settings (mcp_servers ),loop 
                    )

                settings ._characters =load_characters_from_yaml ()
        except Exception as e :
            logger .warning (f"Settings hot-reload failed: {e }")

    return _reload 


async def shutdown_application ():
    """Clean up shared resources. Call on application shutdown."""
    try :
        from backend .core .deps import mcp ,memory 
        await mcp ().close ()
        await memory ().shutdown ()
    except Exception as e :
        logger .warning (f"Shutdown error: {e }")

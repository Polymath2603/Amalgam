"""
FastAPI application factory.
Creates and configures the main app instance with all routes, middleware, static mounts,
and startup lifecycle.
"""
import os 
import asyncio 
import logging 

from fastapi import FastAPI ,WebSocket 
from fastapi .staticfiles import StaticFiles 
from fastapi .middleware .cors import CORSMiddleware 

from backend .api .ws .handler import handle_chat 
from backend .api .routes import (
settings as settings_route ,
characters ,
mcp as mcp_route ,
memory as memory_route ,
vault ,
relationship ,
tts as tts_route ,
root ,
)
from backend .api .deps import settings ,memory ,tts ,mcp 
from backend .paths import FRONTEND_DIR ,DATA_DIR ,CHARACTERS_DIR ,VAULT_DIR 
from backend .utils .icon_generator import generate_missing_icons 

logger =logging .getLogger (__name__ )


def create_app ():
    """Create and return the configured FastAPI application."""
    app =FastAPI (title ="Amalgam")
    app .add_middleware (CORSMiddleware ,allow_origins =["*"],allow_methods =["*"],allow_headers =["*"])


    app .include_router (settings_route .router )
    app .include_router (characters .router )
    app .include_router (mcp_route .router )
    app .include_router (memory_route .router )
    app .include_router (vault .router )
    app .include_router (relationship .router )
    app .include_router (tts_route .router )
    app .include_router (root .router )


    CHAR_DEFAULT_ANIM =str (CHARACTERS_DIR /"default"/"anim")
    if os .path .exists (CHAR_DEFAULT_ANIM ):
        app .mount ("/static/animations",StaticFiles (directory =CHAR_DEFAULT_ANIM ),name ="default_animations")


    if os .path .exists (str (FRONTEND_DIR )):
        app .mount ("/static",StaticFiles (directory =str (FRONTEND_DIR )),name ="static")


    if os .path .exists (str (DATA_DIR )):
        app .mount ("/user_data",StaticFiles (directory =str (DATA_DIR )),name ="user_data")


    if os .path .exists (str (CHARACTERS_DIR )):
        app .mount ("/characters",StaticFiles (directory =str (CHARACTERS_DIR )),name ="characters")


    @app .websocket ("/ws/chat")
    async def ws_chat (websocket :WebSocket ):
        await handle_chat (websocket )


    @app .on_event ("startup")
    async def startup ():
        logger .warning ("Starting Amalgam backend...")
        asyncio .create_task (_delayed_startup_tasks ())


        memory ().start_session ()


        engine =settings ().get ("voice.engine","edge-tts")
        if engine =="openvoice":
            logger .debug ("Preloading OpenVoice TTS engine...")
            try :
                loop =asyncio .get_event_loop ()
                await loop .run_in_executor (None ,tts ().get_openvoice_loaded )
                logger .debug ("OpenVoice TTS engine ready")
            except Exception as e :
                logger .warning (f"OpenVoice preload failed: {e }")


        vault_path =settings ().get ("vault.path",str (VAULT_DIR ))
        os .makedirs (vault_path ,exist_ok =True )
        rules_path =os .path .join (vault_path ,"rules.md")
        if not os .path .exists (rules_path ):
            with open (rules_path ,"w")as f :
                f .write ("# Rules\n\nAdd your custom rules here. These will be injected into every conversation.\n")


        mcp_servers =settings ().get_mcp_servers ()
        if mcp_servers :
            try :
                await mcp ().connect_from_settings (mcp_servers )
            except Exception as e :
                logger .warning (f"MCP servers from settings failed: {e }")

    return app 


async def _delayed_startup_tasks ():
    """Run icon generation 2 seconds after startup so the server is responsive first."""
    try :
        await asyncio .sleep (2.0 )
        await generate_missing_icons ()
    except Exception as e :
        logger .error (f"Error in delayed startup tasks: {e }")



app =create_app ()

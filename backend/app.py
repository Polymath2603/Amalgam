"""
FastAPI application factory.
Creates and configures the main app instance with all routes, middleware, static mounts,
and startup lifecycle.
"""
import os 
import asyncio 
import logging 
from pathlib import Path 

from fastapi import FastAPI ,WebSocket 
from fastapi .responses import FileResponse ,Response 
from fastapi .staticfiles import StaticFiles 
from fastapi .middleware .cors import CORSMiddleware 
import mimetypes

mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")

from backend .api .ws .handler import handle_chat 
from backend .api .routes import (
settings as settings_route ,
characters ,
commands as commands_route ,
mcp as mcp_route ,
memory as memory_route ,
push as push_route ,
vault ,
relationship ,
tts as tts_route ,
)
from backend .core .paths import DATA_DIR ,CHARACTERS_DIR ,PROJECT_ROOT 
from backend .core .startup import init_application 
from backend .core .utils .icon_generator import generate_missing_icons 
from pathlib import Path 

_origins_env = os.environ.get("AMALGAM_CORS_ORIGINS", "")
if _origins_env:
    CORS_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]
else:
    CORS_ORIGINS = [
        "http://localhost:8000",
        "http://localhost:5173",
        "http://localhost:3000",
        "tauri://localhost",
    ]

WEBUI_DIR =PROJECT_ROOT /"webui"

logger =logging .getLogger (__name__ )


def create_app ():
    """Create and return the configured FastAPI application."""
    app =FastAPI (title ="Amalgam")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        allow_credentials=True,
        max_age=600,
    )

    app .include_router (settings_route .router )
    app .include_router (characters .router )
    app .include_router (commands_route .router )
    app .include_router (mcp_route .router )
    app .include_router (memory_route .router )
    app .include_router (push_route .router )
    app .include_router (vault .router )
    app .include_router (relationship .router )
    app .include_router (tts_route .router )

    DATA_DIR .mkdir (parents =True ,exist_ok =True )
    app .mount ("/data",StaticFiles (directory =str (DATA_DIR )),name ="data")

    REPO_CHARS =str (CHARACTERS_DIR )
    @app .get ("/characters/{file_path:path}")
    async def serve_character_asset (file_path :str ):
        full_path =CHARACTERS_DIR /file_path 
        if full_path .exists ()and full_path .is_file ():
            return FileResponse (str (full_path ))
        return Response (status_code =404 )

    @app .websocket ("/ws/chat")
    async def ws_chat (websocket :WebSocket ):
        await handle_chat (websocket )

    @app .on_event ("startup")
    async def startup ():
        logger .warning ("Starting Amalgam backend...")
        await init_application ()
        port =os .environ .get ("AMALGAM_PORT","8000")
        host =os .environ .get ("AMALGAM_HOST","0.0.0.0")
        logger .warning (f"\n  Server ready on http://localhost:{port }\n")
        asyncio .create_task (_delayed_startup_tasks ())

    @app .on_event ("shutdown")
    async def shutdown ():
        logger .warning ("Shutting down Amalgam backend...")
        from backend .core .startup import shutdown_application 
        await shutdown_application ()

    index_path =WEBUI_DIR /"index.html"
    if index_path .exists ():
        @app .get ("/{path:path}")
        async def serve_webui (path :str ):
            file_path =WEBUI_DIR /path 
            if file_path .exists ()and file_path .is_file ():
                return FileResponse (str (file_path ))
            return FileResponse (str (index_path ))
    return app 


async def _delayed_startup_tasks ():
    """Run icon generation 2 seconds after startup so the server is responsive first."""
    try :
        await asyncio .sleep (2.0 )
        await generate_missing_icons ()
    except Exception as e :
        logger .error (f"Error in delayed startup tasks: {e }")

app =create_app ()

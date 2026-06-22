"""
FastAPI application factory.
Creates and configures the main app instance with all routes, middleware, static mounts,
and startup lifecycle.
"""
import os
import asyncio
import logging
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import FastAPI ,WebSocket ,Request
from fastapi .responses import FileResponse ,Response ,JSONResponse
from fastapi .staticfiles import StaticFiles
from fastapi .middleware .cors import CORSMiddleware
from fastapi .exceptions import RequestValidationError
from starlette .middleware .base import BaseHTTPMiddleware
from starlette .exceptions import HTTPException as StarletteHTTPException
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
setup as setup_route ,
companion as companion_route ,
)
from backend .core .paths import DATA_DIR ,CHARACTERS_DIR ,PROJECT_ROOT
from backend .core .startup import init_application
from backend .core .utils .icon_generator import generate_missing_icons

_origins_env = os.environ.get("AMALGAM_CORS_ORIGINS", "")
if _origins_env:
    CORS_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]
else:
    CORS_ORIGINS = [
        os.environ.get("AMALGAM_BACKEND_URL", "http://localhost:8000"),
        "http://localhost:5173",
        "http://localhost:3000",
        "tauri://localhost",
    ]

WEBUI_DIR =PROJECT_ROOT /"webui"

logger =logging .getLogger (__name__ )

_in_flight_requests: dict[str, list[float]] = {}


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple per-IP sliding-window rate limiter."""
    def __init__(self, app, max_requests: int = 120, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/api/health", "/ready"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = _in_flight_requests.setdefault(client_ip, [])
        # Prune stale entries
        while window and window[0] < now - self.window_seconds:
            window.pop(0)
        if len(window) >= self.max_requests:
            return JSONResponse(
                {"error": "Rate limit exceeded — try again later"},
                status_code=429,
            )
        window.append(now)
        return await call_next(request)


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
    app.add_middleware(_RateLimitMiddleware, max_requests=120, window_seconds=60)

    # ── Global exception handlers ──────────────────────────────────
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = []
        for err in exc.errors():
            field = " → ".join(str(loc) for loc in err.get("loc", []))
            msg = err.get("msg", "Invalid value")
            errors.append({"field": field, "message": msg})
        return JSONResponse(
            status_code=422,
            content={"error": "Validation failed", "details": errors},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception")
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"},
        )

    # Health check endpoint
    _start_time = time.time()

    @app.get("/api/health")
    async def health():
        """Service health status endpoint. Returns cached states (instant)."""
        from backend.core.health import get_registry

        states = get_registry().get_all()
        overall = "ok"
        for s in states.values():
            if s["status"] == "down":
                overall = "degraded"
                break
            if s["status"] == "unknown":
                overall = "unknown"

        return {
            "status": overall,
            "service": "amalgam",
            "version": "0.1.0",
            "uptime": time.time() - _start_time,
            "services": states,
        }

    @app.get("/ready")
    async def ready():
        db_ok = False
        try:
            from backend.core.memory.fts import FTSSearch
            from backend.core.paths import CONVERSATIONS_DIR
            fts = FTSSearch(CONVERSATIONS_DIR)
            fts.search("probe")  # synchronous — no await
            db_ok = True
        except Exception as e:
            logger.debug("Ready check — FTS probe failed: %s", e)
        status = 200 if db_ok else 503
        return JSONResponse(
            {"status": "ok" if db_ok else "degraded", "database": db_ok},
            status_code=status,
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
    app .include_router (setup_route .router )
    app .include_router (setup_route .providers_router )
    app .include_router (companion_route .router )

    DATA_DIR .mkdir (parents =True ,exist_ok =True )
    app .mount ("/data",StaticFiles (directory =str (DATA_DIR )),name ="data")

    REPO_CHARS =str (CHARACTERS_DIR )
    @app .get ("/characters/{file_path:path}")
    async def serve_character_asset (file_path :str ):
        # Prevent path traversal: resolve and verify the path stays inside CHARACTERS_DIR
        full_path =(CHARACTERS_DIR /file_path ).resolve ()
        if not full_path .is_relative_to (CHARACTERS_DIR .resolve ()):
            return Response (status_code =403 )
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
        # Start companion scheduler
        try :
            from backend .core .deps import companion as companion_fn
            sched = companion_fn ()
            if sched :
                import asyncio
                asyncio .create_task (sched .start ())
        except Exception as e :
            logger .warning (f"Companion scheduler start failed: {e}")

        # Start Telegram bot (if configured)
        try :
            from backend .api .telegram import run_telegram
            asyncio .create_task (run_telegram ())
        except Exception as e :
            logger .debug (f"Telegram bot not available: {e}")

        # Start gRPC server (if grpc package available)
        try :
            from backend .grpc .server import serve_grpc
            asyncio .create_task (serve_grpc ())
        except ImportError :
            pass  # grpc package not installed
        except Exception as e :
            logger .debug (f"gRPC server start failed: {e}")

        port =os .environ .get ("AMALGAM_PORT","8000")
        host =os .environ .get ("AMALGAM_HOST","0.0.0.0")
        logger .warning (f"\n  Server ready on http://localhost:{port }\n")
        # Auto-open browser if not disabled
        if not os.environ.get("NO_BROWSER"):
            threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
        asyncio .create_task (_delayed_startup_tasks ())

    @app .on_event ("shutdown")
    async def shutdown ():
        logger .warning ("Shutting down Amalgam backend...")
        # Stop companion scheduler
        try :
            from backend .core .deps import companion as companion_fn
            sched = companion_fn ()
            if sched :
                await sched .stop ()
        except Exception as e:
            logger.debug("Failed to stop companion scheduler on shutdown: %s", e)
        from backend .core .startup import shutdown_application 
        await shutdown_application ()

    index_path =WEBUI_DIR /"index.html"
    if index_path .exists ():
        @app .get ("/{path:path}")
        async def serve_webui (path :str ):
            # Prevent path traversal: resolve and verify the path stays inside WEBUI_DIR
            file_path =(WEBUI_DIR /path ).resolve ()
            if not file_path .is_relative_to (WEBUI_DIR .resolve ()):
                return Response (status_code =403 )
            if file_path .exists ()and file_path .is_file ():
                return FileResponse (str (file_path ))
            return FileResponse (str (index_path ))
    return app 


async def _delayed_startup_tasks ():
    """Run icon generation and hot-reloader 2 seconds after startup so the server is responsive first."""
    try :
        await asyncio .sleep (2.0 )
        await generate_missing_icons ()
        # Start hot-reload watcher (plan spec)
        from backend .core .hot_reload import setup_hot_reload, _reloader
        from backend .skills .md_loader import get_loader as _get_skill_loader
        from backend .core import constitution
        reloader = setup_hot_reload(_get_skill_loader(), constitution)
        asyncio .create_task (reloader .start())
    except Exception as e :
        logger .error (f"Error in delayed startup tasks: {e }")

app =create_app ()

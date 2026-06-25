"""
FastAPI application factory.
Creates and configures the main app instance with all routes, middleware, static mounts,
and startup lifecycle.
"""
import asyncio
import json
import logging
import mimetypes
import os
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.ws.handler import handle_chat
from backend.api.routes import (
    settings as settings_route,
    characters as characters_route,
    commands as commands_route,
    mcp as mcp_route,
    memory as memory_route,
    metrics as metrics_route,
    push as push_route,
    vault as vault_route,
    relationship as relationship_route,
    tts as tts_route,
    setup as setup_route,
    companion as companion_route,
)
from backend.core.paths import DATA_DIR, CHARACTERS_DIR, PROJECT_ROOT
from backend.core.startup import init_application
from backend.core.utils.icon_generator import generate_missing_icons

_origins_env = os.environ.get("AMALGAM_CORS_ORIGINS", "")
if _origins_env:
    CORS_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]
else:
    CORS_ORIGINS = [
        os.environ.get("AMALGAM_BACKEND_URL", "http://localhost:8000"),
        "http://localhost:5173",
        "http://localhost:3000",
        "tauri://localhost",
        "*",
    ]

WEBUI_DIR = PROJECT_ROOT / "webui"

logger = logging.getLogger(__name__)

# Per-IP sliding window: {client_ip: deque[timestamps]}
_in_flight_requests: dict[str, deque[float]] = {}

# Background task tracking for clean shutdown (fix H7)
_background_tasks: set[asyncio.Task] = set()
_cache_fts = None  # cached FTS instance for /ready (fix M10)
_cache_fts_lock = threading.Lock()  # fix N7


def _track_task(task: asyncio.Task) -> None:
    """Register a background task for lifecycle tracking."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


class _RateLimitMiddleware:
    """Simple per-IP sliding-window rate limiter as pure ASGI middleware (fix H8)."""
    def __init__(self, app, max_requests: int = 120, window_seconds: int = 60):
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in ("/api/health", "/ready"):
            await self.app(scope, receive, send)
            return

        # M2: better client IP detection — try X-Forwarded-For first
        client_ip = "unknown"
        headers = dict(scope.get("headers", []))
        xff = headers.get(b"x-forwarded-for")
        if xff:
            client_ip = xff.decode().split(",")[0].strip()
        else:
            client_info = scope.get("client")
            if client_info:
                client_ip = client_info[0]

        now = time.monotonic()
        window = _in_flight_requests.setdefault(client_ip, deque())

        # M1: O(1) popleft via deque
        while window and window[0] < now - self.window_seconds:
            window.popleft()

        # L4: check limit BEFORE appending current timestamp
        if len(window) >= self.max_requests:
            body = json.dumps({"error": "Rate limit exceeded — try again later"}).encode()
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ]
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": headers,
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
            return

        window.append(now)
        await self.app(scope, receive, send)


def create_app():
    """Create and return the configured FastAPI application."""
    # L7: move mimetypes registration inside create_app
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("image/svg+xml", ".svg")

    app = FastAPI(title="Amalgam")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        allow_credentials=False,
        max_age=600,
    )
    # H8: pure ASGI middleware (not BaseHTTPMiddleware)
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

    # M10: cached FTS instance, re-created lazily on error
    @app.get("/ready")
    async def ready():
        global _cache_fts
        db_ok = False
        try:
            from backend.core.memory.fts import FTSSearch
            from backend.core.paths import CONVERSATIONS_DIR

            with _cache_fts_lock:  # fix N7
                if _cache_fts is None:
                    _cache_fts = FTSSearch(CONVERSATIONS_DIR)
                fts = _cache_fts
            # H9: wrap synchronous I/O in thread executor
            await asyncio.to_thread(fts.search, "probe")
            db_ok = True
        except Exception as e:
            logger.debug("Ready check — FTS probe failed: %s", e)
            with _cache_fts_lock:  # fix N7
                _cache_fts = None  # force re-creation next time
        status = 200 if db_ok else 503
        return JSONResponse(
            {"status": "ok" if db_ok else "degraded", "database": db_ok},
            status_code=status,
        )

    # M7: consistent _route suffix for all routers
    app.include_router(settings_route.router)
    app.include_router(characters_route.router)
    app.include_router(commands_route.router)
    app.include_router(mcp_route.router)
    app.include_router(memory_route.router)
    app.include_router(metrics_route.router)
    app.include_router(push_route.router)
    app.include_router(vault_route.router)
    app.include_router(relationship_route.router)
    app.include_router(tts_route.router)
    app.include_router(setup_route.router)
    app.include_router(setup_route.providers_router)
    app.include_router(companion_route.router)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

    @app.get("/characters/{file_path:path}")
    async def serve_character_asset(file_path: str):
        # Prevent path traversal: resolve and verify the path stays inside CHARACTERS_DIR
        full_path = (CHARACTERS_DIR / file_path).resolve()
        if not full_path.is_relative_to(CHARACTERS_DIR.resolve()):
            return Response(status_code=403)
        if full_path.exists() and full_path.is_file():
            return FileResponse(str(full_path))
        return Response(status_code=404)

    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket):
        await handle_chat(websocket)

    @app.on_event("startup")
    async def startup():
        logger.info("Starting Amalgam backend...")                     # M3
        await init_application()
        # Start companion scheduler
        try:
            from backend.core.deps import companion as companion_fn
            sched = companion_fn()
            if sched:
                # M6: remove redundant import asyncio
                _track_task(asyncio.create_task(sched.start()))
        except Exception as e:
            logger.warning(f"Companion scheduler start failed: {e}")   # M3

        # Start Telegram bot (if configured)
        try:
            from backend.api.telegram import run_telegram
            _track_task(asyncio.create_task(run_telegram()))
        except Exception as e:
            logger.debug(f"Telegram bot not available: {e}")

        # Start gRPC server (if grpc package available)
        try:
            from backend.grpc.server import serve_grpc
            _track_task(asyncio.create_task(serve_grpc()))
        except ImportError:
            pass  # grpc package not installed
        except Exception as e:
            logger.debug(f"gRPC server start failed: {e}")

        port = os.environ.get("AMALGAM_PORT", "8000")
        host = os.environ.get("AMALGAM_HOST", "0.0.0.0")
        logger.info(f"\n  Server ready on http://localhost:{port}\n")  # M3
        # L8: use asyncio instead of threading.Timer for browser open
        if not os.environ.get("NO_BROWSER"):
            _track_task(asyncio.create_task(_open_browser(port)))
        _track_task(asyncio.create_task(_delayed_startup_tasks()))

    @app.on_event("shutdown")
    async def shutdown():
        logger.info("Shutting down Amalgam backend...")                # M3
        # M4: use warning level for shutdown errors
        # Stop companion scheduler
        try:
            from backend.core.deps import companion as companion_fn
            sched = companion_fn()
            if sched:
                await sched.stop()
        except Exception as e:
            logger.warning("Failed to stop companion scheduler on shutdown: %s", e)  # M4

        # Cancel tracked background tasks (fix N10)
        while _background_tasks:
            tasks = list(_background_tasks)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        from backend.core.startup import shutdown_application
        await shutdown_application()

    # M8: register webui route unconditionally; handler checks file existence
    @app.get("/{path:path}")
    async def serve_webui(path: str):
        # Prevent path traversal: resolve and verify the path stays inside WEBUI_DIR
        file_path = (WEBUI_DIR / path).resolve()
        if not file_path.is_relative_to(WEBUI_DIR.resolve()):
            return Response(status_code=403)
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        index_path = WEBUI_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return Response(status_code=404)

    return app


async def _open_browser(port: str):
    """Open the browser after a short delay (fix L8)."""
    import webbrowser
    await asyncio.sleep(1.5)
    webbrowser.open(f"http://localhost:{port}")


async def _delayed_startup_tasks():
    """Run icon generation and hot-reloader 2 seconds after startup so the server is responsive first."""
    try:
        await asyncio.sleep(2.0)
        await generate_missing_icons()
        # Start hot-reload watcher (plan spec)
        # M9: don't import private _reloader; use public API return value
        from backend.core.hot_reload import setup_hot_reload
        from backend.skills.md_loader import get_loader as _get_skill_loader
        from backend.core import constitution
        reloader = setup_hot_reload(_get_skill_loader(), constitution)
        _track_task(asyncio.create_task(reloader.start()))
    except Exception as e:
        logger.error(f"Error in delayed startup tasks: {e}")


app = create_app()

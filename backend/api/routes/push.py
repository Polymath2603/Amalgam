"""Push notification token registration endpoint for Capacitor native shell.

6B.3 — Receives push tokens from the Capacitor app and stores them
for server-initiated notifications.
"""
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["push"])

# In-memory token store (replace with DB in production)
_push_tokens: dict[str, dict] = {}  # token -> {"platform": str, "device_id": str}


@router.post("/api/push/register")
async def register_token(data: dict = None):
    data = data or {}
    token = (data.get("token") or "").strip()
    platform = data.get("platform", "unknown")
    device_id = data.get("device_id", "")

    if not token:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Missing push token"}, status_code=400)

    _push_tokens[token] = {"platform": platform, "device_id": device_id}
    logger.info("Push token registered: %s (%s)", token[:16] + "...", platform)
    return {"status": "ok"}


@router.post("/api/push/unregister")
async def unregister_token(data: dict = None):
    data = data or {}
    token = (data.get("token") or "").strip()
    _push_tokens.pop(token, None)
    return {"status": "ok"}


@router.get("/api/push/tokens")
async def list_tokens():
    """Admin endpoint — list registered tokens (not exposed in production)."""
    return {"tokens": list(_push_tokens.keys())}

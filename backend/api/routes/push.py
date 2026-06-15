"""Push notification token registration endpoint for Capacitor native shell.

6B.3 — Receives push tokens from the Capacitor app and persists them
for server-initiated notifications.
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["push"])

PUSH_TOKENS_PATH = Path("data/push_tokens.json")


def _load_tokens() -> dict[str, dict]:
    if PUSH_TOKENS_PATH.exists():
        try:
            return json.loads(PUSH_TOKENS_PATH.read_text())
        except Exception as e:
            logger.warning("Failed to load push tokens: %s", e)
    return {}


def _save_tokens(tokens: dict[str, dict]):
    PUSH_TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUSH_TOKENS_PATH.write_text(json.dumps(tokens, indent=2))


@router.post("/api/push/register")
async def register_token(data: dict = None):
    data = data or {}
    token = (data.get("token") or "").strip()
    platform = data.get("platform", "unknown")
    device_id = data.get("device_id", "")

    if not token:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Missing push token"}, status_code=400)

    tokens = _load_tokens()
    tokens[token] = {"platform": platform, "device_id": device_id}
    _save_tokens(tokens)
    logger.info("Push token registered: %s (%s)", token[:16] + "...", platform)
    return {"status": "ok"}


@router.post("/api/push/unregister")
async def unregister_token(data: dict = None):
    data = data or {}
    token = (data.get("token") or "").strip()
    tokens = _load_tokens()
    tokens.pop(token, None)
    _save_tokens(tokens)
    return {"status": "ok"}


@router.get("/api/push/tokens")
async def list_tokens():
    """Admin endpoint — list registered tokens (not exposed in production)."""
    tokens = _load_tokens()
    return {"tokens": list(tokens.keys())}

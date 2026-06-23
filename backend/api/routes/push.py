"""Push notification token registration endpoint for Capacitor native shell.

6B.3 — Receives push tokens from the Capacitor app and persists them
for server-initiated notifications.
"""
import json
import logging
import fcntl
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from backend.core.deprecated import deprecated

logger = logging.getLogger(__name__)

router = APIRouter(tags=["push"])

PUSH_TOKENS_PATH = Path("data/push_tokens.json")


class PushRegisterRequest(BaseModel):
    token: str
    platform: str = "unknown"
    device_id: str = ""


class PushUnregisterRequest(BaseModel):
    token: str = ""


def _load_tokens() -> dict[str, dict]:
    if PUSH_TOKENS_PATH.exists():
        try:
            with open(PUSH_TOKENS_PATH, "r") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                data = json.load(f)
            return data
        except Exception as e:
            logger.warning("Failed to load push tokens: %s", e)
    return {}


def _save_tokens(tokens: dict[str, dict]):
    PUSH_TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PUSH_TOKENS_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(tokens, f, indent=2)
    tmp.replace(PUSH_TOKENS_PATH)


@router.post("/api/push/register")
@deprecated()
async def register_token(body: PushRegisterRequest):
    token = body.token  # Don't strip — preserve original for matching
    platform = body.platform
    device_id = body.device_id

    if not token:
        return JSONResponse({"error": "Missing push token"}, status_code=400)

    tokens = _load_tokens()
    tokens[token] = {"platform": platform, "device_id": device_id}
    _save_tokens(tokens)
    logger.info("Push token registered: %s (%s)", token[:16] + "...", platform)
    return {"status": "ok"}


@router.post("/api/push/unregister")
@deprecated()
async def unregister_token(body: PushUnregisterRequest):
    token = body.token  # Don't strip — match original registration
    tokens = _load_tokens()
    if token not in tokens:
        return JSONResponse({"status": "error", "errors": ["Push token not found"]}, status_code=404)
    tokens.pop(token, None)
    _save_tokens(tokens)
    return {"status": "ok"}


@router.get("/api/push/tokens")
@deprecated()
async def list_tokens():
    """Admin endpoint — list registered tokens (not exposed in production)."""
    # TODO: Add authentication before exposing this endpoint
    tokens = _load_tokens()
    return {"tokens": list(tokens.keys())}

"""
Companion API routes — /api/companion
Settings and manual trigger for companion mode.
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel
from backend.api.deps import settings
from backend.core.deprecated import deprecated

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/companion", tags=["companion"])


class CompanionSettingsUpdate(BaseModel):
    enabled: bool | None = None
    idle_check_delay: float | None = None
    proactive_interval: float | None = None
    time_awareness: bool | None = None
    personality_notes: str | None = None


@router.get("/settings")
async def get_companion_settings():
    """Return current companion settings."""
    s = settings()
    return {
        "enabled": s.get("companion.enabled", False),
        "idle_check_delay": s.get("companion.idle_check_delay", 10),
        "proactive_interval": s.get("companion.proactive_interval", 60),
        "time_awareness": s.get("companion.time_awareness", True),
        "personality_notes": s.get("companion.personality_notes", ""),
    }


@router.post("/settings")
async def update_companion_settings(body: CompanionSettingsUpdate):
    """Update companion settings."""
    s = settings()
    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        s.set(f"companion.{key}", value)
    return {"ok": True, "settings": await get_companion_settings()}


@router.post("/trigger")
async def trigger_companion_message():
    """Manually trigger a companion message via LLM."""
    sched = companion()
    if sched is None:
        return {"ok": False, "error": "Companion scheduler not initialized"}
    text = await sched.trigger_now()
    if text:
        return {"ok": True, "content": text}
    return {"ok": False, "error": "Failed to generate companion message"}

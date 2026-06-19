"""
Typed event bus for cross-component communication.
Usage:
    from backend.core.events import event_bus, ServiceEvent

    # Subscribe
    event_bus.on("llm.call.complete", my_handler)

    # Publish (fire-and-forget)
    event_bus.emit("llm.call.complete", model="gemini", tokens=150)

    # Publish and await all handlers
    await event_bus.emit_async("service.status.change", ...)
"""

from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# ── Event name constants ──────────────────────────────────────────────

class Events:
    """Central registry of all event names. Single source of truth."""

    # LLM lifecycle
    LLM_CALL_START = "llm.call.start"
    LLM_CALL_COMPLETE = "llm.call.complete"
    LLM_CALL_FAILED = "llm.call.failed"
    LLM_ROUTER_DECISION = "llm.router.decision"

    # TTS lifecycle
    TTS_SYNTHESIS_START = "tts.synthesis.start"
    TTS_SYNTHESIS_COMPLETE = "tts.synthesis.complete"
    TTS_SYNTHESIS_FAILED = "tts.synthesis.failed"
    TTS_ENGINE_FAILED = "tts.engine.failed"

    # STT lifecycle
    STT_INPUT_DETECTED = "stt.input.detected"
    STT_TRANSCRIPTION_COMPLETE = "stt.transcription.complete"
    STT_TRANSCRIPTION_FAILED = "stt.transcription.failed"

    # Voice pipeline
    VOICE_STATE_CHANGE = "voice.state.change"
    VOICE_INTERRUPT = "voice.interrupt"

    # Service health
    SERVICE_STATUS_CHANGE = "service.status.change"
    SERVICE_REGISTERED = "service.registered"

    # Memory
    MEMORY_RETRIEVAL = "memory.retrieval"
    MEMORY_SUMMARY = "memory.summary"

    # Skills
    SKILL_USED = "skill.used"
    SKILL_CREATED = "skill.created"
    SKILL_CURATOR_RUN = "skill.curator.run"

    # User profile
    USER_PROFILE_UPDATED = "user.profile.updated"

    # Agent
    AGENT_TURN_START = "agent.turn.start"
    AGENT_TURN_COMPLETE = "agent.turn.complete"
    AGENT_ERROR = "agent.error"
    AGENT_TOOL_CALL = "agent.tool.call"

    # MCP
    MCP_SERVER_CONNECTED = "mcp.server.connected"
    MCP_SERVER_DISCONNECTED = "mcp.server.disconnected"
    MCP_SERVER_ERROR = "mcp.server.error"


@dataclass
class Event:
    """Base event payload."""
    type: str
    timestamp: float = field(default_factory=lambda: __import__('time').time())
    source: str = ""
    data: dict = field(default_factory=dict)


class EventBus:
    """
    Lightweight in-process event bus.

    - sync handlers run in the publisher's thread/task
    - async handlers are scheduled via create_task
    - exceptions in handlers never propagate (logged instead)

    Thread-safe for subscribe/unsubscribe. emit is not thread-safe
    (should only be called from async context).
    """

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}
        self._async_handlers: dict[str, list[Callable[..., Coroutine]]] = {}

    def on(self, event: str, handler: Callable):
        """Register a sync handler."""
        self._handlers.setdefault(event, []).append(handler)

    def on_async(self, event: str, handler: Callable[..., Coroutine]):
        """Register an async handler (scheduled via create_task)."""
        self._async_handlers.setdefault(event, []).append(handler)

    def off(self, event: str, handler: Callable):
        """Unregister a handler."""
        try:
            self._handlers.get(event, []).remove(handler)
        except ValueError:
            pass
        try:
            self._async_handlers.get(event, []).remove(handler)
        except ValueError:
            pass

    def emit(self, event: str, **data):
        """Fire event synchronously. Async handlers are scheduled as tasks."""
        ev = Event(type=event, data=data)

        # Sync handlers
        for handler in self._handlers.get(event, []):
            try:
                handler(ev)
            except Exception as e:
                logger.warning(f"Event handler {handler.__name__} failed for {event}: {e}")

        # Async handlers
        for handler in self._async_handlers.get(event, []):
            try:
                asyncio.create_task(self._safe_async_handler(handler, ev))
            except Exception as e:
                logger.warning(f"Failed to schedule async handler for {event}: {e}")

    async def emit_async(self, event: str, **data):
        """Fire event and await all handlers. Mix of sync and async."""
        ev = Event(type=event, data=data)

        # Sync handlers (same as emit)
        for handler in self._handlers.get(event, []):
            try:
                handler(ev)
            except Exception as e:
                logger.warning(f"Event handler {handler.__name__} failed for {event}: {e}")

        # Async handlers (awaited)
        for handler in self._async_handlers.get(event, []):
            try:
                await handler(ev)
            except Exception as e:
                logger.warning(f"Async event handler {handler.__name__} failed for {event}: {e}")

    async def _safe_async_handler(self, handler, event):
        try:
            await handler(event)
        except Exception as e:
            logger.warning(f"Async event handler {handler.__name__} failed for {event.type}: {e}")

    def clear(self):
        """Remove all handlers (useful in tests)."""
        self._handlers.clear()
        self._async_handlers.clear()


# Module-level singleton
_event_bus = EventBus()

def get_bus() -> EventBus:
    return _event_bus

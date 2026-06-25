"""
CompanionEngine — unified orchestrator for companion mode.

This is the central "brain" that:
  • Maintains companion state (on/off, idle, connection)
  • Coordinates with CompanionScheduler for proactive triggers
  • Pushes companion messages to all connected surfaces
  • Manages avatar expressions and animations
  • Tracks companion context (session, conversation state)

Usage:
    engine = CompanionEngine(settings, llm, memory)
    engine.start()
    engine.push_event(CompanionEvent(CompanionEventType.IDLE_ENTER))
    engine.send_companion_message("Hello!", context="greeting")
    engine.stop()
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Optional

from .events import CompanionEvent, CompanionEventType
from .scheduler import CompanionScheduler

logger = logging.getLogger(__name__)


class CompanionState(str, Enum):
    """Unified companion state machine."""
    DISABLED = "disabled"           # Companion mode turned off
    IDLE = "idle"                   # User is idle (no activity detected)
    ACTIVE = "active"               # User is actively interacting
    SLEEPING = "sleeping"           # Extended idle — avatar sleeping
    AWAY = "away"                   # Mid-level idle — not sleeping but not active


class CompanionEngine:
    """
    Unified companion engine that replaces scattered companion implementations.

    Wires together:
    - CompanionScheduler (proactive message generation)
    - WebSocket session management
    - Avatar state coordination
    - Idle detection from all surfaces
    """

    def __init__(
        self,
        settings_provider: Callable,
        llm_provider: Callable,
        memory_provider: Optional[Callable] = None,
    ) -> None:
        self._settings = settings_provider
        self._llm = llm_provider
        self._memory = memory_provider

        # State
        self._state = CompanionState.DISABLED
        self._running = False
        self._engine_task: Optional[asyncio.Task] = None

        # Per-connection sessions: session_id -> send_fn
        self._sessions: dict[str, Callable] = {}

        # Sub-components
        self._scheduler = CompanionScheduler(
            settings_provider=settings_provider,
            llm_provider=llm_provider,
            memory_provider=memory_provider,
        )

        # Callbacks for surfaces that want real-time updates
        self._on_state_change: Optional[Callable[[CompanionState], None]] = None
        self._on_companion_message: Optional[Callable[[dict], None]] = None
        self._on_expression: Optional[Callable[[str, float], None]] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the companion engine."""
        if self._running:
            return
        self._running = True
        self._sync_state_from_settings()
        logger.info("Companion engine started (state=%s)", self._state.value)

    def stop(self) -> None:
        """Stop the companion engine gracefully."""
        self._running = False
        self._state = CompanionState.DISABLED
        # Fire scheduler stop asynchronously
        asyncio.create_task(self._scheduler.stop())
        logger.info("Companion engine stopped")

    async def stop_async(self) -> None:
        """Async stop — await pending tasks."""
        self.stop()
        if self._engine_task and not self._engine_task.done():
            self._engine_task.cancel()
            try:
                await self._engine_task
            except asyncio.CancelledError:
                pass
            self._engine_task = None

    # ── Settings ───────────────────────────────────────────────────────────

    def _sync_state_from_settings(self) -> None:
        """Read companion.enabled from settings and sync state."""
        enabled = bool(self._settings().get("companion.enabled", False))
        if enabled and self._state == CompanionState.DISABLED:
            self._state = CompanionState.ACTIVE
            asyncio.create_task(self._scheduler.start())
        elif not enabled and self._state != CompanionState.DISABLED:
            self._state = CompanionState.DISABLED
            asyncio.create_task(self._scheduler.stop())
        self._notify_state_change()

    def enable(self) -> None:
        """Enable companion mode: update settings, activate state, start scheduler."""
        self._settings().set("companion.enabled", True)
        if self._state == CompanionState.DISABLED:
            self._state = CompanionState.ACTIVE
            asyncio.create_task(self._scheduler.start())
            self._notify_state_change()

    def disable(self) -> None:
        """Disable companion mode: update settings, deactivate state, stop scheduler."""
        self._settings().set("companion.enabled", False)
        if self._state != CompanionState.DISABLED:
            self._state = CompanionState.DISABLED
            asyncio.create_task(self._scheduler.stop())
            self._notify_state_change()

    def is_enabled(self) -> bool:
        """Check if companion mode is currently enabled."""
        return self._state != CompanionState.DISABLED

    def get_state(self) -> CompanionState:
        return self._state

    # ── Session Management ────────────────────────────────────────────────

    def register_session(self, session_id: str, send_fn: Callable) -> None:
        """Register a WebSocket session for push messages."""
        self._sessions[session_id] = send_fn
        self._scheduler.register_session(session_id, send_fn)
        if self.is_enabled():
            self.push_event(
                CompanionEvent(CompanionEventType.USER_JOINED, data={"session_id": session_id})
            )
        logger.debug("Companion: session registered: %s", session_id)

    def unregister_session(self, session_id: str) -> None:
        """Remove a WebSocket session."""
        self._sessions.pop(session_id, None)
        self._scheduler.unregister_session(session_id)
        logger.debug("Companion: session unregistered: %s", session_id)

    # ── Event Handling ────────────────────────────────────────────────────

    def push_event(self, event: CompanionEvent) -> None:
        """Push an event into the companion system (fire-and-forget)."""
        if not self.is_enabled():
            return
        # Fire scheduler event asynchronously — don't await here
        asyncio.create_task(self._scheduler.on_event(event))

        # Handle events that affect engine state
        if event.event_type == CompanionEventType.IDLE_ENTER:
            self._state = CompanionState.IDLE
            self._notify_state_change()
        elif event.event_type == CompanionEventType.IDLE_EXIT:
            self._state = CompanionState.ACTIVE
            self._notify_state_change()
        elif event.event_type == CompanionEventType.IDLE_TIMEOUT:
            self._state = CompanionState.SLEEPING
            self._notify_state_change()

    # ── Message Sending ───────────────────────────────────────────────────

    async def send_companion_message(
        self,
        text: str,
        context: str = "proactive",
        session_id: Optional[str] = None,
        expression: Optional[str] = None,
    ) -> None:
        """Send a companion message to all (or a specific) session."""
        if not self.is_enabled():
            return

        payload = {
            "type": "companion",
            "content": text,
            "context": context,
            "timestamp": time.time(),
        }
        if expression:
            payload["expression"] = expression

        if session_id:
            send_fn = self._sessions.get(session_id)
            if send_fn:
                try:
                    await send_fn(payload)
                except Exception as e:
                    logger.warning("Companion: send to %s failed: %s", session_id, e)
        else:
            for sid, send_fn in list(self._sessions.items()):
                try:
                    await send_fn(payload)
                except Exception as e:
                    logger.warning("Companion: broadcast to %s failed: %s", sid, e)

        if self._on_companion_message:
            try:
                self._on_companion_message(payload)
            except Exception as e:
                logger.warning("Companion: on_companion_message callback failed: %s", e)

    # ── Avatar Control ────────────────────────────────────────────────────

    async def set_expression(self, expression: str, intensity: float = 1.0) -> None:
        """Push an expression change to all surfaces."""
        if not self.is_enabled():
            return
        payload = {"type": "emotion", "emotion": expression, "intensity": intensity}
        for sid, send_fn in list(self._sessions.items()):
            try:
                await send_fn(payload)
            except Exception as e:
                logger.warning("Companion: expression send failed: %s", e)
        if self._on_expression:
            try:
                self._on_expression(expression, intensity)
            except Exception as e:
                logger.warning("Companion: on_expression callback failed: %s", e)

    async def set_mouth_movement(self, level: float) -> None:
        """Push mouth/viseme state for lip-sync."""
        if not self.is_enabled():
            return
        payload = {"type": "voice_level", "level": min(1.0, max(0.0, level))}
        for sid, send_fn in list(self._sessions.items()):
            try:
                await send_fn(payload)
            except Exception:
                pass

    # ── Callback Registration ─────────────────────────────────────────────

    def set_on_state_change(self, cb: Optional[Callable[[CompanionState], None]]) -> None:
        self._on_state_change = cb

    def set_on_companion_message(self, cb: Optional[Callable[[dict], None]]) -> None:
        self._on_companion_message = cb

    def set_on_expression(self, cb: Optional[Callable[[str, float], None]]) -> None:
        self._on_expression = cb

    # ── Internals ──────────────────────────────────────────────────────────

    def _notify_state_change(self) -> None:
        if self._on_state_change:
            try:
                self._on_state_change(self._state)
            except Exception as e:
                logger.warning("Companion: state change callback failed: %s", e)





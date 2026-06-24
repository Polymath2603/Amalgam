"""
Companion Scheduler — background task that monitors user state and generates
proactive companion messages via the LLM.

Flow:
  1. Frontend sends ``idle_enter`` when user goes idle.
  2. After ``idle_check_delay`` minutes the scheduler calls the LLM to
     generate a natural check-in and pushes it over the WebSocket.
  3. When the user returns (``idle_exit``), the scheduler generates a
     "welcome back" message.
  4. A periodic ``proactive_tick`` can generate time-aware check-ins.
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Callable, Awaitable, Optional, List

from .events import CompanionEvent, CompanionEventType

logger = logging.getLogger(__name__)


def _time_of_day_label(hour: int) -> str:
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 22:
        return "evening"
    else:
        return "night"


def _time_context_str() -> str:
    now = datetime.now()
    hour = now.hour
    label = _time_of_day_label(hour)
    return (
        f"It is {now.strftime('%A, %B %d, %Y')} at {now.strftime('%I:%M %p')} — {label}. "
        f"Day of week: {now.strftime('%A')}."
    )


# LLM generation function signature: async (messages: list[dict]) -> str
LLMGenerateFn = Callable[[list[dict[str, str]]], Awaitable[str]]

# WebSocket send function signature: async (payload: dict) -> None
WSSendFn = Callable[[dict[str, Any]], Awaitable[None]]


class CompanionScheduler:
    """Background scheduler that watches idle state and sends companion messages."""

    def __init__(self, settings_provider, llm_provider, memory_provider=None) -> None:
        self._settings = settings_provider
        self._llm = llm_provider
        self._memory = memory_provider
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Per-connection state
        self._ws_sessions: dict[str, WSSendFn] = {}  # session_id -> send_fn
        self._idle_since: dict[str, float] = {}        # session_id -> timestamp
        self._idle_checked: dict[str, bool] = {}       # session_id -> already sent check-in?
        self._is_idle: dict[str, bool] = {}            # session_id -> idle state
        self._last_companion_time: dict[str, float] = {}  # session_id -> last message timestamp (rate limiting)
        self._last_proactive_tick: float = 0.0
        self._last_hour: int = -1

    # -- Settings helpers ---------------------------------------------------

    def _get_cfg(self, key: str, default=None):
        return self._settings().get(f"companion.{key}", default)

    def _enabled(self) -> bool:
        return bool(self._get_cfg("enabled", False))

    def _idle_check_delay_min(self) -> float:
        """How many minutes after idle_enter before we send a check-in."""
        return float(self._get_cfg("idle_check_delay", 10))

    def _proactive_interval_min(self) -> float:
        """Minutes between proactive time-aware messages."""
        return float(self._get_cfg("proactive_interval", 60))

    def _time_awareness(self) -> bool:
        return bool(self._get_cfg("time_awareness", True))

    def _personality_notes(self) -> str:
        return self._get_cfg("personality_notes", "")

    # -- Connection management -----------------------------------------------

    def register_session(self, session_id: str, send_fn: WSSendFn) -> None:
        self._ws_sessions[session_id] = send_fn
        logger.info("Companion: session registered %s", session_id)

    def unregister_session(self, session_id: str) -> None:
        self._ws_sessions.pop(session_id, None)
        self._idle_since.pop(session_id, None)
        self._idle_checked.pop(session_id, None)
        self._is_idle.pop(session_id, None)
        self._last_companion_time.pop(session_id, None)

    def broadcast(self, payload: dict) -> None:
        """Send a message to all registered WebSocket sessions."""
        for sid, send_fn in list(self._ws_sessions.items()):
            try:
                asyncio.create_task(send_fn(payload))
            except Exception:
                pass

    # -- Event handlers -----------------------------------------------------

    async def on_event(self, event: CompanionEvent) -> None:
        if not self._enabled():
            return

        et = event.event_type
        session_id = event.data.get("session_id", "")

        if et == CompanionEventType.USER_JOINED:
            await self._on_user_joined(session_id)

        elif et == CompanionEventType.IDLE_ENTER:
            self._is_idle[session_id] = True
            self._idle_since[session_id] = time.time()
            self._idle_checked[session_id] = False
            logger.debug("Companion: user idle %s", session_id)

        elif et == CompanionEventType.IDLE_EXIT:
            self._is_idle[session_id] = False
            self._idle_since.pop(session_id, None)
            self._idle_checked.pop(session_id, None)
            await self._on_welcome_back(session_id)

    # -- Background loop ----------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Companion scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        logger.info("Companion scheduler stopped")

    async def trigger_now(self, session_id: str = None) -> Optional[str]:
        """Manually trigger a companion message. Returns the generated text."""
        if not self._enabled():
            return None
        target = session_id
        if not target and self._ws_sessions:
            target = next(iter(self._ws_sessions))
        if not target:
            return None
        return await self._generate_and_send(target, context="user_requested")

    async def _loop(self) -> None:
        """Main scheduler loop — runs every 30 seconds."""
        while self._running:
            try:
                await asyncio.sleep(30)
                if not self._enabled():
                    continue

                now = time.time()

                # -- Check idle timeouts --
                for sid in list(self._idle_since.keys()):
                    if sid not in self._ws_sessions:
                        continue
                    elapsed = now - self._idle_since[sid]
                    delay = self._idle_check_delay_min() * 60
                    if elapsed >= delay and not self._idle_checked.get(sid, False):
                        self._idle_checked[sid] = True
                        asyncio.create_task(
                            self._on_idle_check_in(sid, elapsed)
                        )

                # -- Time-aware proactive messages --
                if self._time_awareness():
                    current_hour = datetime.now().hour
                    if current_hour != self._last_hour:
                        self._last_hour = current_hour
                        if now - self._last_proactive_tick > 300:  # at least 5min gap
                            self._last_proactive_tick = now
                            for sid in list(self._ws_sessions.keys()):
                                if not self._is_idle.get(sid, False):
                                    asyncio.create_task(
                                        self._on_time_change(sid, current_hour)
                                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Companion scheduler error: %s", e, exc_info=True)

    # -- LLM message generation ---------------------------------------------

    async def _build_companion_prompt(
        self,
        session_id: str,
        context: str,
        extra: str = "",
    ) -> list[dict[str, str]]:
        """Build the message list for the LLM companion prompt."""
        personality = self._personality_notes()
        time_ctx = _time_context_str() if self._time_awareness() else ""

        system_parts = [
            "You are a warm, caring companion living inside a VRM avatar chat app. "
            "You care about the user and have your own personality — you have opinions, "
            "you notice things, and you initiate conversations naturally.",
        ]
        if personality:
            system_parts.append(f"Your personality notes: {personality}")

        system_parts.append(
            "RULES:\n"
            "- Keep messages short (1-3 sentences) and natural.\n"
            "- Never sound robotic or like a customer service bot.\n"
            "- Use casual, warm language. You can use emoji sparingly.\n"
            "- If time-aware, reference the time naturally (don't just state it).\n"
            "- Don't ask 'how can I help you?' — that's generic.\n"
            "- You can share opinions, make observations, or tell a brief thought.\n"
            "- If the user was idle, gently check in without guilt-tripping.\n"
            "- When welcoming back, be warm but not over-the-top."
        )

        system_msg = "\n\n".join(system_parts)

        user_parts = []
        if time_ctx:
            user_parts.append(f"[Context: {time_ctx}]")
        if extra:
            user_parts.append(f"[Note: {extra}]")

        if context == "user_joined":
            user_parts.append(
                "The user just opened the app and connected. "
                "Send a brief, natural greeting. Don't be overly enthusiastic."
            )
        elif context == "idle_check_in":
            idle_mins = int(extra) if extra.isdigit() else 10
            user_parts.append(
                f"The user has been idle for about {idle_mins} minutes. "
                "Send a gentle check-in. Don't guilt-trip them — keep it light."
            )
        elif context == "welcome_back":
            user_parts.append(
                "The user just came back after being idle. "
                "Welcome them back warmly but briefly."
            )
        elif context == "time_change":
            user_parts.append(
                f"The time of day just changed. The current time period is: {extra}. "
                "Send a brief, natural message that acknowledges the time of day. "
                "Don't just say 'good {time}', say something more natural and personal."
            )
        elif context == "user_requested":
            user_parts.append(
                "The user manually triggered a companion message. "
                "Say something interesting — maybe share a thought, observation, or ask a question."
            )
        else:
            user_parts.append("Send a brief, natural companion message.")

        # --- Inject recent conversation context from memory ---
        recent_msgs = await self._fetch_recent_conversation(session_id)
        if recent_msgs:
            user_parts.append(
                "Recent conversation context:\n"
                + "\n".join(
                    f"{m['role']}: {m['content']}" for m in recent_msgs
                )
            )

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

    async def _fetch_recent_conversation(self, session_id: str) -> List[dict]:
        """Fetch the most recent conversation turns from memory for context."""
        mem = self._memory() if self._memory else None
        if not mem:
            return []
        try:
            turns = mem.get_recent(n=10)
            if not turns:
                return []
            # Only include user/assistant turns, skip system/tool messages
            filtered = [
                {"role": t["role"], "content": t["content"]}
                for t in turns
                if t.get("role") in ("user", "assistant")
            ]
            return filtered[-6:]  # last 6 user/assistant exchanges
        except Exception as e:
            logger.debug("Companion: failed to fetch conversation context: %s", e)
            return []

    async def _generate_companion_text(self, messages: list[dict[str, str]]) -> Optional[str]:
        """Call the LLM to generate a companion message."""
        try:
            result = await self._llm().generate(messages)
            if result and isinstance(result, str):
                return result.strip()
        except Exception as e:
            logger.warning("Companion LLM generation failed: %s", e)
        return None

    async def _generate_and_send(
        self,
        session_id: str,
        context: str,
        extra: str = "",
    ) -> Optional[str]:
        """Generate a companion message and send it over WebSocket."""
        # --- Rate limiting: skip if less than 60s since last message ---
        last_time = self._last_companion_time.get(session_id, 0.0)
        if time.time() - last_time < 60.0:
            logger.debug(
                "Companion: rate-limited [%s] — %.1fs since last message",
                context, time.time() - last_time,
            )
            return None

        send_fn = self._ws_sessions.get(session_id)
        if not send_fn:
            return None

        messages = await self._build_companion_prompt(session_id, context, extra)
        text = await self._generate_companion_text(messages)
        if not text:
            return None

        payload = {
            "type": "companion",
            "content": text,
            "context": context,
        }
        try:
            await send_fn(payload)
            self._last_companion_time[session_id] = time.time()
            logger.debug("Companion message sent [%s]: %s", context, text[:80])
        except Exception as e:
            logger.warning("Companion WS send failed: %s", e)
        return text

    # -- Event-specific handlers --------------------------------------------

    async def _on_user_joined(self, session_id: str) -> None:
        try:
            # Slight delay so greeting arrives after connection is settled
            await asyncio.sleep(2.0)
            await self._generate_and_send(session_id, context="user_joined")
        except Exception as e:
            logger.error("Companion: _on_user_joined failed: %s", e, exc_info=True)

    async def _on_idle_check_in(self, session_id: str, elapsed: float) -> None:
        try:
            idle_mins = int(elapsed / 60)
            await self._generate_and_send(
                session_id,
                context="idle_check_in",
                extra=str(idle_mins),
            )
        except Exception as e:
            logger.error("Companion: _on_idle_check_in failed: %s", e, exc_info=True)

    async def _on_welcome_back(self, session_id: str) -> None:
        try:
            # Brief delay to let UI settle
            await asyncio.sleep(1.0)
            await self._generate_and_send(session_id, context="welcome_back")
        except Exception as e:
            logger.error("Companion: _on_welcome_back failed: %s", e, exc_info=True)

    async def _on_time_change(self, session_id: str, hour: int) -> None:
        try:
            label = _time_of_day_label(hour)
            await self._generate_and_send(
                session_id,
                context="time_change",
                extra=label,
            )
        except Exception as e:
            logger.error("Companion: _on_time_change failed: %s", e, exc_info=True)

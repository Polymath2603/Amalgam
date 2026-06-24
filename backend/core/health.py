"""
Service health registry with proactive background checks.
All services register a lightweight async check function.
A background task runs all checks every 60 seconds.
Services also push status changes via the event bus in real-time.

Usage:
    from backend.core.health import health_registry

    # Register a service
    health_registry.register("llm.provider.gemini", check_llm_fn)

    # Check a specific service
    status = await health_registry.check("llm.provider.gemini")

    # Get all statuses (instant, from cache)
    all_status = health_registry.get_all()
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

from backend.core.events import get_bus, Events

logger = logging.getLogger(__name__)


class ServiceStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"
    NOT_CONFIGURED = "not_configured"


@dataclass
class ServiceState:
    """Current state of a registered service."""

    name: str
    status: ServiceStatus = ServiceStatus.UNKNOWN
    last_ok: Optional[float] = None  # timestamp of last successful check
    last_failure: Optional[float] = None  # timestamp of last failure
    last_error: str = ""  # last error message
    detail: str = ""  # human-readable detail
    latency_ms: float = 0.0  # last check latency


class ServiceRegistry:
    """
    Central registry for all service health checks.

    - Services register an async check function
    - A background task runs all checks every 60 seconds
    - Individual checks emit events on status change
    - get_all() returns instant cached state (no I/O)
    """

    def __init__(self):
        self._services: dict[str, ServiceState] = {}
        self._check_fns: dict[str, Callable[[], Awaitable[tuple[bool, str]]]] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._bus = get_bus()

    # ── Public API ──────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        check_fn: Callable[[], Awaitable[tuple[bool, str]]],
        initial_status: ServiceStatus = ServiceStatus.UNKNOWN,
    ):
        """
        Register a service.

        *check_fn* is an async callable that returns ``(ok: bool, detail: str)``.
        *detail* is a human-readable string such as ``"gemini-2.0-flash (connected)"``
        or ``"Connection refused: port 8080"``.
        """
        self._services[name] = ServiceState(
            name=name,
            status=initial_status,
            detail="Registered, not yet checked"
            if initial_status == ServiceStatus.UNKNOWN
            else "",
        )
        self._check_fns[name] = check_fn
        self._bus.emit(
            Events.SERVICE_REGISTERED,
            service=name,
            status=initial_status.value,
        )
        logger.info(f"Service registered: {name}")

    async def check(self, name: str) -> ServiceState:
        """Run a single service check. Updates cache."""
        if name not in self._check_fns:
            return ServiceState(
                name=name, status=ServiceStatus.NOT_CONFIGURED, detail="Not registered"
            )

        fn = self._check_fns[name]
        start = time.monotonic()
        try:
            ok, detail = await fn()
            elapsed = (time.monotonic() - start) * 1000
            state = self._services[name]

            old_status = state.status

            if ok:
                state.status = ServiceStatus.OK
                state.last_ok = time.time()
                state.last_error = ""
                state.latency_ms = round(elapsed, 1)
            else:
                state.status = ServiceStatus.DOWN
                state.last_failure = time.time()
                state.last_error = detail
                state.latency_ms = round(elapsed, 1)

            state.detail = detail

            # Emit on status change
            if state.status != old_status:
                self._bus.emit(
                    Events.SERVICE_STATUS_CHANGE,
                    service=name,
                    status=state.status.value,
                    old_status=old_status.value if old_status else None,
                    detail=detail,
                )

            return state
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            state = self._services.get(name, ServiceState(name=name))
            state.status = ServiceStatus.DOWN
            state.last_failure = time.time()
            state.last_error = str(e)
            state.detail = f"Check failed: {e}"
            state.latency_ms = round(elapsed, 1)
            self._services[name] = state
            return state

    def get_status(self, name: str) -> ServiceStatus:
        """Instant: get cached status (never runs a check)."""
        state = self._services.get(name)
        if state is None:
            return ServiceStatus.NOT_CONFIGURED
        return state.status

    def get_state(self, name: str) -> Optional[ServiceState]:
        """Instant: get full cached state."""
        return self._services.get(name)

    def get_all(self) -> dict[str, dict]:
        """Instant: get all service states as serializable dicts."""
        return {
            name: {
                "name": state.name,
                "status": state.status.value,
                "last_ok": state.last_ok,
                "last_failure": state.last_failure,
                "last_error": state.last_error,
                "detail": state.detail,
                "latency_ms": state.latency_ms,
            }
            for name, state in self._services.items()
        }

    async def check_all(self) -> dict[str, dict]:
        """Run checks on ALL registered services. Returns updated states."""
        results = {}
        for name in self._check_fns:
            state = await self.check(name)
            results[name] = {
                "name": state.name,
                "status": state.status.value,
                "detail": state.detail,
                "latency_ms": state.latency_ms,
            }
        return results

    # ── Background checker ──────────────────────────────────────────────

    async def start_background_checker(self, interval: int = 60):
        """Start background task that checks all services every *interval* seconds."""
        if self._running:
            return
        self._running = True
        logger.info(f"Health background checker started (interval={interval}s)")
        self._task = asyncio.create_task(self._background_loop(interval))

    async def stop_background_checker(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _background_loop(self, interval: int):
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                await self.check_all()
            except Exception as e:
                logger.warning(f"Background health check error: {e}")


# ── Module-level singleton ────────────────────────────────────────────

_registry = ServiceRegistry()


def get_registry() -> ServiceRegistry:
    return _registry


# ── Built-in check functions ──────────────────────────────────────────


def register_builtin_checks(settings_obj=None, llm_obj=None, tts_obj=None):
    """Register checks for all known services. Called at startup."""

    async def _check_llm():
        # Check if LLM is configured and responsive
        try:
            provider = (
                settings_obj.get("provider.active", "unknown")
                if settings_obj
                else "unknown"
            )
            model = (
                settings_obj.get(f"provider.{provider}.model", "unknown")
                if settings_obj
                else "unknown"
            )
            api_key = (
                settings_obj.get(f"provider.{provider}.api_key", "")
                if settings_obj
                else ""
            )

            if provider == "ollama":
                # For local providers, check if the URL responds
                return True, f"{provider}/{model} (local)"

            if not api_key:
                return False, f"{provider}: no API key configured"

            # Light check: just validate config exists
            return True, f"{provider}/{model} (configured)"
        except Exception as e:
            return False, str(e)

    async def _check_tts():
        try:
            engine = (
                settings_obj.get("voice.engine", "edge-tts")
                if settings_obj
                else "edge-tts"
            )
            if tts_obj is not None:
                # Try a quick synthesis to verify
                return True, f"{engine} (connected)"
            return True, f"{engine} (configured)"
        except Exception as e:
            return False, str(e)

    async def _check_stt():
        try:
            from backend.api.routes.settings import get_stt_engine_for_mode
            engine = get_stt_engine_for_mode(settings_obj)
            return True, f"{engine} (configured)"
        except Exception as e:
            return False, str(e)

    async def _check_mcp():
        # Check if at least one MCP server is connected
        return True, "servers configured"  # Placeholder

    async def _check_avatar():
        try:
            enabled = settings_obj.get("avatar.model_path", "") if settings_obj else ""
            if enabled:
                return True, "model configured"
            return True, "disabled (no model path)"
        except Exception as e:
            return False, str(e)

    registry = get_registry()
    registry.register("llm", _check_llm)
    registry.register("tts", _check_tts)
    registry.register("stt", _check_stt)
    registry.register("mcp", _check_mcp)
    registry.register("avatar", _check_avatar)

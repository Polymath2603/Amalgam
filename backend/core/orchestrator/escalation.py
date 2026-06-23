"""
Chain-of-command escalation — sub-agent → parent → orchestrator → user.
Agents can request help from their parent, or escalate blocked decisions up the chain.
"""
import asyncio
import logging
import uuid
from typing import Any, Callable, Coroutine, Literal

logger = logging.getLogger(__name__)

Severity = Literal["info", "warning", "blocked", "critical"]


class EscalationRequest:
    """A request for human or parent intervention."""
    def __init__(self, agent_id: str, reason: str, context: str,
                 severity: Severity = "info"):
        self.id: str = uuid.uuid4().hex
        self.agent_id = agent_id
        self.reason = reason
        self.context = context
        self.severity: Severity = severity
        self.resolved = False
        self.resolution = ""
        # Future that resolves when the user/parent responds
        self._response_future: asyncio.Future[str] | None = None

    def set_response_future(self, fut: asyncio.Future[str]):
        """Attach a Future that will be resolved with the user's response."""
        self._response_future = fut


class ChainOfCommand:
    """Manages escalation ladder: sub-agent → parent → orchestrator → user."""

    def __init__(self, max_auto_escalations: int = 3):
        self._pending: list[EscalationRequest] = []
        self._max_auto_escalations = max_auto_escalations
        # Registry: agent_id → parent_agent_id for chain-of-command resolution
        self._agent_hierarchy: dict[str, str] = {}

    def register_agent(self, agent_id: str, parent_id: str | None = None):
        """Register an agent in the hierarchy (None parent = direct child of orchestrator)."""
        if parent_id:
            self._agent_hierarchy[agent_id] = parent_id

    def _get_parent(self, agent_id: str) -> str | None:
        """Return the parent agent of *agent_id*, or None if at the orchestrator level."""
        return self._agent_hierarchy.get(agent_id)

    def escalate(self, agent_id: str, reason: str, context: str,
                 severity: Severity = "info") -> EscalationRequest:
        """Create and register an escalation request."""
        req = EscalationRequest(agent_id, reason, context, severity)
        self._pending.append(req)
        logger.warning("Escalation from %s: %s (%s)", agent_id, reason, severity)
        return req

    def resolve(self, req: EscalationRequest, resolution: str):
        """Mark an escalation as resolved."""
        req.resolved = True
        req.resolution = resolution
        # Resolve the pending future if any
        if req._response_future is not None and not req._response_future.done():
            req._response_future.set_result(resolution)

    def get_pending(self, severity: Severity | None = None, max_results: int = 50) -> list[EscalationRequest]:
        if severity:
            results = [r for r in self._pending if not r.resolved and r.severity == severity]
        else:
            results = [r for r in self._pending if not r.resolved]
        return results[:max_results]

    def can_auto_escalate(self) -> bool:
        """Check if we can auto-escalate to user without flooding."""
        recent = [r for r in self._pending if not r.resolved
                  and r.severity in ("blocked", "critical")]
        return len(recent) < self._max_auto_escalations

    async def notify_user(
        self,
        req: EscalationRequest,
        ws_send_fn: Callable[[dict], Coroutine[Any, Any, None]] | None = None,
        timeout: float = 120.0,
    ) -> str | None:
        """Send escalation to user via WebSocket and *wait* for a response.

        Returns the user's response string on success, or ``None`` if
        *ws_send_fn* was not provided or the request timed out.
        """
        if not ws_send_fn:
            return None

        # Create a Future that the resolve() or external handler will set
        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[str] = loop.create_future()
        req.set_response_future(response_future)

        await ws_send_fn({
            "type": "escalation",
            "agent_id": req.agent_id,
            "reason": req.reason,
            "context": req.context,
            "severity": req.severity,
            "request_id": req.id,
        })

        try:
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.warning("Escalation %s timed out after %.0f s", req.id, timeout)
            # Cancel the future to prevent InvalidStateError if response arrives later
            if not response_future.done():
                response_future.cancel()
            req.resolved = True
            req.resolution = "timeout"
            return None

    def receive_response(self, request_id: str, resolution: str) -> bool:
        """Handle an incoming user/parent response for a pending escalation.

        This is typically called from the WebSocket handler when a user
        replies to an escalation prompt.

        Returns ``True`` if the request was found and resolved.
        """
        for req in self._pending:
            if req.id == request_id and not req.resolved:
                self.resolve(req, resolution)
                return True
        logger.warning("No pending escalation found with id %s", request_id)
        return False

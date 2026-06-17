"""
Chain-of-command escalation — sub-agent → parent → orchestrator → user.
Agents can request help from their parent, or escalate blocked decisions up the chain.
"""
import logging

logger = logging.getLogger(__name__)


class EscalationRequest:
    """A request for human or parent intervention."""
    def __init__(self, agent_id: str, reason: str, context: str,
                 severity: str = "info"):
        self.agent_id = agent_id
        self.reason = reason
        self.context = context
        self.severity = severity  # info | warning | blocked | critical
        self.resolved = False
        self.resolution = ""


class ChainOfCommand:
    """Manages escalation ladder: sub-agent → parent → orchestrator → user."""

    def __init__(self):
        self._pending: list[EscalationRequest] = []
        self._max_auto_escalations = 3

    def escalate(self, agent_id: str, reason: str, context: str,
                 severity: str = "info") -> EscalationRequest:
        """Create and register an escalation request."""
        req = EscalationRequest(agent_id, reason, context, severity)
        self._pending.append(req)
        logger.warning(f"Escalation from {agent_id}: {reason} ({severity})")
        return req

    def resolve(self, req: EscalationRequest, resolution: str):
        """Mark an escalation as resolved."""
        req.resolved = True
        req.resolution = resolution

    def get_pending(self, severity: str | None = None) -> list[EscalationRequest]:
        if severity:
            return [r for r in self._pending if not r.resolved and r.severity == severity]
        return [r for r in self._pending if not r.resolved]

    def can_auto_escalate(self) -> bool:
        """Check if we can auto-escalate to user without flooding."""
        recent = [r for r in self._pending if not r.resolved
                  and r.severity in ("blocked", "critical")]
        return len(recent) < self._max_auto_escalations

    async def notify_user(self, req: EscalationRequest,
                          ws_send_fn) -> str | None:
        """Send escalation to user via WebSocket and wait for response."""
        if not ws_send_fn:
            return None
        await ws_send_fn({
            "type": "escalation",
            "agent_id": req.agent_id,
            "reason": req.reason,
            "context": req.context,
            "severity": req.severity,
            "request_id": id(req),
        })
        return id(req)

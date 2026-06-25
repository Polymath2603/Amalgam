"""
Companion package — unified companion mode for Amalgam.

The companion engine manages a persistent ambient AI presence that:
- Detects user idle/active state and sends proactive check-ins
- Generates time-aware greetings and welcome-backs
- Pushes companion messages to all connected surfaces (WebUI, overlay, CLI)
- Coordinates with the VRM avatar overlay for expressions and animations
"""
from .events import CompanionEvent, CompanionEventType
from .scheduler import CompanionScheduler
from .engine import CompanionEngine, CompanionState

__all__ = [
    "CompanionEvent",
    "CompanionEventType",
    "CompanionScheduler",
    "CompanionEngine",
    "CompanionState",
]


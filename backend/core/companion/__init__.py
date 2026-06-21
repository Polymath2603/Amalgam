"""
Companion package — proactive companion mode for Amalgam.
"""
from .events import CompanionEvent, CompanionEventType
from .scheduler import CompanionScheduler

__all__ = [
    "CompanionEvent",
    "CompanionEventType",
    "CompanionScheduler",
]

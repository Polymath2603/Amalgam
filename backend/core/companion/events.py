"""
Companion events — types the companion scheduler can react to.
"""
import time
from enum import Enum
from dataclasses import dataclass, field


class CompanionEventType(str, Enum):
    USER_JOINED = "user_joined"
    IDLE_ENTER = "idle_enter"
    IDLE_TIMEOUT = "idle_timeout"
    IDLE_EXIT = "idle_exit"
    TIME_CHANGE = "time_change"       # crossed hour boundary
    TASK_COMPLETE = "task_complete"     # background task finished
    PROACTIVE_TICK = "proactive_tick"   # periodic check-in timer


@dataclass
class CompanionEvent:
    event_type: CompanionEventType
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)

    def age_seconds(self) -> float:
        return time.time() - self.timestamp

"""
Agent DM system via shared blackboard — agents post messages, share context,
and coordinate through a structured message bus.
"""
import time
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BlackboardEntry:
    """A single message on the blackboard."""
    key: str
    value: Any
    author: str
    timestamp: float = 0.0
    ttl: float = 0.0  # 0 = permanent


class Blackboard:
    """Shared communication channel for multi-agent coordination.

    Agents post structured messages under namespaced keys.
    Other agents subscribe or poll for relevant entries.
    """

    def __init__(self):
        self._entries: dict[str, BlackboardEntry] = {}
        self._locks: dict[str, str] = {}  # key → agent_id lock holder

    def post(self, key: str, value: Any, author: str, ttl: float = 0.0):
        """Post a value to the blackboard under a namespaced key."""
        self._entries[key] = BlackboardEntry(
            key=key, value=value, author=author,
            timestamp=time.time(), ttl=ttl,
        )
        logger.debug(f"Blackboard: {author} posted {key}")

    def get(self, key: str, default: Any = None) -> Any:
        """Read a value from the blackboard."""
        entry = self._entries.get(key)
        if entry is None:
            return default
        if entry.ttl > 0 and time.time() - entry.timestamp > entry.ttl:
            del self._entries[key]
            return default
        return entry.value

    def delete(self, key: str):
        self._entries.pop(key, None)

    def search(self, prefix: str) -> list[BlackboardEntry]:
        """Return all entries whose key starts with prefix."""
        return [e for k, e in self._entries.items() if k.startswith(prefix)]

    def acquire_lock(self, key: str, agent_id: str, timeout: float = 5.0) -> bool:
        """Try to lock a resource for exclusive access by one agent."""
        now = time.time()
        if key in self._locks:
            holder = self._locks[key]
            if holder != agent_id:
                return False
        self._locks[key] = agent_id
        return True

    def release_lock(self, key: str, agent_id: str):
        """Release a held lock."""
        if self._locks.get(key) == agent_id:
            del self._locks[key]

    def clear(self):
        self._entries.clear()
        self._locks.clear()

"""
Agent DM system via shared blackboard — agents post messages, share context,
and coordinate through a structured message bus with pub/sub support.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class BlackboardEntry:
    """A single message on the blackboard."""
    key: str
    value: Any
    author: str
    timestamp: float = 0.0
    ttl: float = 0.0  # 0 = permanent


_SubscriptionCallback = Callable[[str, Any, str], None]


class Blackboard:
    """Shared communication channel for multi-agent coordination.

    Agents post structured messages under namespaced keys.
    Other agents subscribe or poll for relevant entries.

    All public methods are safe to call from concurrent coroutines.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._entries: dict[str, BlackboardEntry] = {}
        self._locks: dict[str, str] = {}  # key -> agent_id lock holder
        # Pub/sub: key prefix -> list of callbacks
        self._subscriptions: dict[str, list[_SubscriptionCallback]] = {}
        # Prefix index for fast search
        self._prefix_index: dict[str, set[str]] = {}
        # Stale-lock TTL (seconds); locks older than this are eligible for
        # re-acquisition.  0 = never expire (default behaviour).
        self._lock_ttl: float = 30.0

    # -- Pub/Sub -----------------------------------------------------------

    def subscribe(self, key_prefix: str, callback: _SubscriptionCallback):
        """Register a callback for entries whose key starts with *key_prefix*.

        The callback is invoked as ``fn(key, value, author)`` every time a
        matching entry is posted.
        """
        self._subscriptions.setdefault(key_prefix, []).append(callback)

    def unsubscribe(self, key_prefix: str, callback: _SubscriptionCallback):
        """Remove a previously registered subscription."""
        subs = self._subscriptions.get(key_prefix)
        if subs:
            try:
                subs.remove(callback)
            except ValueError:
                pass

    # -- CRUD --------------------------------------------------------------

    async def post(self, key: str, value: Any, author: str, ttl: float = 0.0):
        """Post a value to the blackboard under a namespaced key."""
        async with self._lock:
            self._entries[key] = BlackboardEntry(
                key=key, value=value, author=author,
                timestamp=time.time(), ttl=ttl,
            )
            # Update prefix index
            self._add_to_prefix_index(key)
            logger.debug("Blackboard: %s posted %s", author, key)

        # Fire subscriptions outside the lock to avoid deadlocks
        self._notify_subscribers(key, value, author)

    async def get(self, key: str, default: Any = None) -> Any:
        """Read a value from the blackboard (safe concurrent read)."""
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return default
            # TTL check -- copy the value before releasing the lock so the
            # caller gets a consistent snapshot even if the entry is deleted.
            if entry.ttl > 0 and time.time() - entry.timestamp > entry.ttl:
                del self._entries[key]
                self._remove_from_prefix_index(key)
                return default
            return entry.value

    async def delete(self, key: str):
        """Remove an entry from the blackboard."""
        async with self._lock:
            existed = key in self._entries
            self._entries.pop(key, None)
            self._remove_from_prefix_index(key)
        if existed:
            logger.debug("Blackboard: deleted %s", key)

    async def clear(self):
        """Remove all entries, locks, and subscriptions."""
        async with self._lock:
            self._entries.clear()
            self._locks.clear()
            self._prefix_index.clear()
        self._subscriptions.clear()
        logger.debug("Blackboard: cleared")

    async def search(self, prefix: str) -> list[BlackboardEntry]:
        """Return all entries whose key starts with *prefix*.

        Uses a prefix index for O(log n) lookups in most cases.
        """
        async with self._lock:
            matched_keys = self._prefix_index.get(prefix, set())
            if matched_keys:
                # Fast path via prefix index
                result: list[BlackboardEntry] = []
                for k in matched_keys:
                    entry = self._entries.get(k)
                    if entry is not None:
                        if entry.ttl > 0 and time.time() - entry.timestamp > entry.ttl:
                            del self._entries[k]
                            self._remove_from_prefix_index(k)
                            continue
                        result.append(entry)
                return result
            # Fallback: full scan (first time with this prefix, or after index rebuild)
            return [
                e for k, e in self._entries.items()
                if k.startswith(prefix)
                and not (e.ttl > 0 and time.time() - e.timestamp > e.ttl)
            ]

    # -- Distributed Locking -----------------------------------------------

    async def acquire_lock(self, key: str, agent_id: str,
                           timeout: float = 5.0) -> bool:
        """Try to lock a resource for exclusive access by one agent.

        If the lock is held by another agent, this method will block up to
        *timeout* seconds, retrying every 0.1 s.  If *timeout* <= 0 the
        method returns immediately (non-blocking).
        """
        deadline = time.time() + timeout if timeout > 0 else time.time()
        while True:
            async with self._lock:
                holder = self._locks.get(key)
                if holder is None:
                    # Lock is free
                    self._locks[key] = agent_id
                    return True
                if holder == agent_id:
                    # Already held by this agent (reentrant)
                    return True
                if self._lock_ttl > 0:
                    # Stale-lock check: if the holder hasn't been seen
                    # recently enough, let the new agent take over.
                    lock_key = key
                    lock_owner = holder
                    # Check all entries for this lock's author timestamp.
                    # If the lock holder hasn't posted to the blackboard
                    # within the TTL window, force-release the stale lock.
                    stale = True
                    for entry in self._entries.values():
                        if entry.author == lock_owner and (time.time() - entry.timestamp) < self._lock_ttl:
                            stale = False
                            break
                    if stale:
                        logger.warning(
                            "Blackboard: forcing stale lock '%s' (holder %s, ttl %.1fs)",
                            key, lock_owner, self._lock_ttl,
                        )
                        self._locks[key] = agent_id
                        return True

            if time.time() >= deadline:
                return False
            await asyncio.sleep(0.1)

    async def release_lock(self, key: str, agent_id: str):
        """Release a held lock."""
        async with self._lock:
            if self._locks.get(key) == agent_id:
                del self._locks[key]

    async def release_all_locks(self, agent_id: str):
        """Release all locks held by *agent_id* (crash-cleanup helper)."""
        async with self._lock:
            keys = [k for k, v in self._locks.items() if v == agent_id]
            for k in keys:
                del self._locks[k]

    # -- Internals ---------------------------------------------------------

    def _add_to_prefix_index(self, key: str):
        """Index *key* under every prefix up to the first ``.`` separator."""
        # Index the full key and the namespace prefix
        parts = key.split(".", 1)
        prefixes = {key}
        if len(parts) > 1:
            prefixes.add(parts[0])
        for p in prefixes:
            self._prefix_index.setdefault(p, set()).add(key)

    def _remove_from_prefix_index(self, key: str):
        for idx_set in self._prefix_index.values():
            idx_set.discard(key)

    def _notify_subscribers(self, key: str, value: Any, author: str):
        for prefix, callbacks in self._subscriptions.items():
            if key.startswith(prefix):
                for cb in callbacks:
                    try:
                        cb(key, value, author)
                    except Exception:
                        logger.exception(
                            "Subscriber callback failed for prefix %r", prefix,
                        )

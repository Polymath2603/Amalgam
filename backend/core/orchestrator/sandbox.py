"""
Topic-based sandbox conflict detection — prevents two sub-agents from
simultaneously modifying overlapping resources or topics.
"""
import logging
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TopicLock:
    topic: str
    agent_id: str
    resource_path: str = ""
    acquired_at: float = 0.0


class SandboxDetector:
    """Detects and prevents topic/resource conflicts between sub-agents.

    Each agent declares which topics/resources it's working on.
    If two agents touch overlapping topics, the second is warned or blocked.

    The topic hierarchy is validated to be acyclic on registration.
    ``_is_related`` uses a reverse-parent index for O(d) ancestor retrieval
    with a visited set and depth limit to avoid infinite loops on malformed
    trees.
    """

    def __init__(self, lock_ttl: float = 300.0):
        self._locks: dict[str, TopicLock] = {}
        # topic_tree: parent -> set[children]
        self._topic_tree: dict[str, set[str]] = {}
        # parent_of: child -> parent  (reverse index for O(1) ancestor lookups)
        self._parent_of: dict[str, str] = {}
        # Locks older than *lock_ttl* seconds can be stolen.
        self._lock_ttl = lock_ttl

    # -- Topic Tree Management ---------------------------------------------

    def register_topic(self, topic: str, parent: str | None = None):
        """Register a topic and its parent for hierarchy checks.

        Raises ``ValueError`` if adding the parent would create a cycle.
        """
        if topic not in self._topic_tree:
            self._topic_tree[topic] = set()
        if parent:
            if parent not in self._topic_tree:
                self._topic_tree[parent] = set()
            # Cycle detection: ensure parent is not already a descendant of topic
            descendants = self._descendants(topic)
            if parent in descendants:
                raise ValueError(
                    f"Cannot register topic {topic!r} with parent {parent!r}: "
                    f"would create a cycle ({parent} is already a descendant of {topic})"
                )
            self._topic_tree[parent].add(topic)
            # Update reverse index
            self._parent_of[topic] = parent

    def _descendants(self, topic: str) -> set[str]:
        """Return all descendants of *topic* (including *topic* itself)."""
        visited: set[str] = set()
        queue: deque[str] = deque([topic])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            for child in self._topic_tree.get(node, set()):
                if child not in visited:
                    queue.append(child)
        return visited

    # -- Lock Management ---------------------------------------------------

    def acquire(self, topic: str, agent_id: str,
                resource_path: str = "") -> tuple[bool, str]:
        """Try to claim a topic. Returns (success, conflict_info)."""
        now = time.time()

        existing = self._locks.get(topic)
        if existing:
            # Stale-lock reclamation
            if existing.agent_id != agent_id:
                if self._lock_ttl > 0 and now - existing.acquired_at > self._lock_ttl:
                    logger.warning(
                        "Reclaiming stale lock on topic %r from %s",
                        topic, existing.agent_id,
                    )
                    del self._locks[topic]
                else:
                    return (False, f"Topic '{topic}' already held by {existing.agent_id}")
            else:
                # Already held by this agent -- refresh timestamp
                existing.acquired_at = now
                return (True, "")

        # Check hierarchy -- if parent or child is locked by another agent
        conflict_agents = set()
        for locked_topic, lock in list(self._locks.items()):
            if lock.agent_id == agent_id:
                continue
            # Skip stale locks
            if self._lock_ttl > 0 and now - lock.acquired_at > self._lock_ttl:
                logger.warning("Cleaning stale lock on topic %r", locked_topic)
                del self._locks[locked_topic]
                continue
            if self._is_related(topic, locked_topic):
                conflict_agents.add(lock.agent_id)

        if conflict_agents:
            return (False, f"Topic '{topic}' overlaps with agents: {conflict_agents}")

        self._locks[topic] = TopicLock(
            topic=topic,
            agent_id=agent_id,
            resource_path=resource_path,
            acquired_at=now,
        )
        logger.debug("Sandbox: %s acquired topic '%s'", agent_id, topic)
        return (True, "")

    def release(self, topic: str, agent_id: str):
        """Release a topic lock."""
        lock = self._locks.get(topic)
        if lock and lock.agent_id == agent_id:
            del self._locks[topic]

    def release_all(self, agent_id: str):
        """Release all locks held by an agent."""
        to_release = [t for t, l in self._locks.items() if l.agent_id == agent_id]
        for t in to_release:
            del self._locks[t]

    # -- Hierarchy Relationship Check -------------------------------------

    def _is_related(self, topic_a: str, topic_b: str) -> bool:
        """Check if two topics are hierarchically related.

        Uses the reverse parent index for O(d) ancestor retrieval (no
        full-table scan), with a visited set and depth limit (100) to
        prevent infinite loops when the topic tree contains cycles.
        """
        if topic_a == topic_b:
            return True

        MAX_DEPTH = 100

        def ancestors(node: str) -> set[str]:
            """Return all ancestors of *node* (including *node* itself)."""
            result: set[str] = set()
            current = node
            depth = 0
            while current is not None and depth <= MAX_DEPTH:
                if current in result:
                    break  # cycle guard
                result.add(current)
                current = self._parent_of.get(current)
                depth += 1
            if depth > MAX_DEPTH:
                logger.warning("Sandbox: MAX_DEPTH (%d) reached traversing ancestors from '%s' — possible cycle", MAX_DEPTH, node)
            return result

        ancestors_a = ancestors(topic_a)
        ancestors_b = ancestors(topic_b)

        return bool(ancestors_a & ancestors_b)

    # -- Utility -----------------------------------------------------------

    def cleanup_stale_locks(self):
        """Remove all locks that have exceeded the TTL."""
        now = time.time()
        stale = [
            t for t, l in self._locks.items()
            if self._lock_ttl > 0 and now - l.acquired_at > self._lock_ttl
        ]
        for t in stale:
            logger.info("Cleaning stale lock on topic %r", t)
            del self._locks[t]
        return len(stale)

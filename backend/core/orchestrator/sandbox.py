"""
Topic-based sandbox conflict detection — prevents two sub-agents from
simultaneously modifying overlapping resources or topics.
"""
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TopicLock:
    topic: str
    agent_id: str
    resource_path: str = ""


class SandboxDetector:
    """Detects and prevents topic/resource conflicts between sub-agents.

    Each agent declares which topics/resources it's working on.
    If two agents touch overlapping topics, the second is warned or blocked.
    """

    def __init__(self):
        self._locks: dict[str, TopicLock] = {}
        self._topic_tree: dict[str, set[str]] = {}

    def register_topic(self, topic: str, parent: str | None = None):
        """Register a topic and its parent for hierarchy checks."""
        if topic not in self._topic_tree:
            self._topic_tree[topic] = set()
        if parent:
            if parent not in self._topic_tree:
                self._topic_tree[parent] = set()
            self._topic_tree[parent].add(topic)

    def acquire(self, topic: str, agent_id: str,
                resource_path: str = "") -> tuple[bool, str]:
        """Try to claim a topic. Returns (success, conflict_info)."""
        existing = self._locks.get(topic)
        if existing and existing.agent_id != agent_id:
            return (False, f"Topic '{topic}' already held by {existing.agent_id}")

        # Check hierarchy — if parent or child is locked by another agent
        conflict_agents = set()
        for locked_topic, lock in self._locks.items():
            if lock.agent_id == agent_id:
                continue
            if self._is_related(topic, locked_topic):
                conflict_agents.add(lock.agent_id)

        if conflict_agents:
            return (False, f"Topic '{topic}' overlaps with agents: {conflict_agents}")

        self._locks[topic] = TopicLock(topic=topic, agent_id=agent_id,
                                        resource_path=resource_path)
        logger.debug(f"Sandbox: {agent_id} acquired topic '{topic}'")
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

    def _is_related(self, topic_a: str, topic_b: str) -> bool:
        """Check if two topics are hierarchically related."""
        if topic_a == topic_b:
            return True
        # Check if a is ancestor of b, or b is ancestor of a
        ancestors_a = {topic_a}
        ancestors_b = {topic_b}
        changed = True
        while changed:
            changed = False
            for parent, children in self._topic_tree.items():
                if parent in ancestors_a:
                    for c in children:
                        if c not in ancestors_a:
                            ancestors_a.add(c)
                            changed = True
                if parent in ancestors_b:
                    for c in children:
                        if c not in ancestors_b:
                            ancestors_b.add(c)
                            changed = True
                for c in children:
                    if c in ancestors_a and parent not in ancestors_a:
                        ancestors_a.add(parent)
                        changed = True
                    if c in ancestors_b and parent not in ancestors_b:
                        ancestors_b.add(parent)
                        changed = True
        return bool(ancestors_a & ancestors_b)

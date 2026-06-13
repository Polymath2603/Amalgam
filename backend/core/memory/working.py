"""Working memory — last N turns with LRU eviction."""

from collections import OrderedDict
from typing import Any, Dict, List, Optional


class WorkingMemory:
    """Stores recent conversational turns in FIFO order with a capacity cap."""

    def __init__(self, capacity: int = 20):
        self._capacity = capacity
        self._turns: OrderedDict[str, Dict] = OrderedDict()

    def add(self, role: str, content: str, metadata: Optional[Dict] = None) -> Dict:
        """Record a turn and evict oldest if over capacity."""
        turn = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
        }
        key = f"{len(self._turns)}"
        self._turns[key] = turn
        if len(self._turns) > self._capacity:
            self._turns.popitem(last=False)
        return turn

    def recent(self, n: int = 5) -> List[Dict]:
        """Return the last *n* turns as a list."""
        return list(self._turns.values())[-n:]

    def all(self) -> List[Dict]:
        return list(self._turns.values())

    def clear(self):
        self._turns.clear()

    def __len__(self) -> int:
        return len(self._turns)

    @property
    def capacity(self) -> int:
        return self._capacity

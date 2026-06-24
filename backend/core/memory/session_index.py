import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


class SessionIndex:
    """Persistent session index backed by a JSON file.

    Uses atomic writes (write to .tmp, then os.replace) to prevent
    corruption on crash.
    """

    INDEX_FILE = "sessions_index.json"

    def __init__(self, conv_dir: Path) -> None:
        self._path = conv_dir / self.INDEX_FILE
        self._lock = threading.Lock()
        self._index: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._index = json.loads(self._path.read_text())
            except Exception:
                self._index = {}

    def _save(self) -> None:
        """Atomic write to prevent corruption on crash."""
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._index, indent=2, default=str))
        # Atomic rename on POSIX; os.replace works cross-platform
        os.replace(str(tmp), str(self._path))

    def upsert(self, session_id: str, meta: dict) -> None:
        with self._lock:
            self._index[session_id] = meta
            self._save()

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._index.pop(session_id, None)
            self._save()

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(
                self._index.values(),
                key=lambda x: x.get("updated", ""),
                reverse=True,
            )

    def clear(self) -> None:
        """Remove all entries from the index."""
        with self._lock:
            self._index.clear()
            self._save()

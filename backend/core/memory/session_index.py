import json
import threading
from pathlib import Path
from typing import List, Dict


class SessionIndex:
    INDEX_FILE = "sessions_index.json"

    def __init__(self, conv_dir: Path):
        self._path = conv_dir / self.INDEX_FILE
        self._lock = threading.Lock()
        self._index: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._index = json.loads(self._path.read_text())
            except Exception:
                self._index = {}

    def _save(self):
        self._path.write_text(json.dumps(self._index, indent=2, default=str))

    def upsert(self, session_id: str, meta: dict):
        with self._lock:
            self._index[session_id] = meta
            self._save()

    def remove(self, session_id: str):
        with self._lock:
            self._index.pop(session_id, None)
            self._save()

    def list_all(self) -> List[Dict]:
        with self._lock:
            return sorted(
                self._index.values(),
                key=lambda x: x.get("updated", ""),
                reverse=True,
            )

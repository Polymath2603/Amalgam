"""
FTS5 full-text search across all conversation sessions.

Uses SQLite's built-in FTS5 extension for fast keyword search over
session messages. Runs alongside ChromaDB (semantic) search.
"""
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class FTSSearch:
    """Keyword-based full-text search across all session messages via FTS5."""

    DB_FILENAME = "fts_index.db"

    def __init__(self, conv_dir: Path):
        self._conv_dir = conv_dir
        conv_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = conv_dir / self.DB_FILENAME
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local connection (FTS5 is thread-safe with separate conns)."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path), timeout=10)
            self._local.conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn.execute("PRAGMA synchronous=OFF;")
        return self._local.conn

    def _init_db(self):
        """Create the FTS5 virtual table if it does not exist."""
        conn = self._get_conn()
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5("
            "  session_id UNINDEXED,"
            "  role UNINDEXED,"
            "  content,"
            "  timestamp UNINDEXED,"
            "  msg_id UNINDEXED,"
            "  tokenize='porter unicode61'"
            ");"
        )
        conn.commit()

    def index_message(self, session_id: str, msg_id: str, role: str,
                      content: str, timestamp: str):
        """Add or update a single message in the FTS index."""
        if not content or not content.strip():
            return
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO message_fts (rowid, session_id, role, content, timestamp, msg_id) "
            "VALUES ("
            "  COALESCE((SELECT rowid FROM message_fts WHERE msg_id = ?), NULL),"
            "  ?, ?, ?, ?, ?"
            ");",
            (msg_id, session_id, role, content, timestamp, msg_id),
        )
        conn.commit()

    def remove_message(self, msg_id: str):
        """Remove a message from the FTS index by its unique ID."""
        conn = self._get_conn()
        conn.execute("DELETE FROM message_fts WHERE msg_id = ?;", (msg_id,))
        conn.commit()

    def remove_session(self, session_id: str):
        """Remove all messages for a session."""
        conn = self._get_conn()
        conn.execute("DELETE FROM message_fts WHERE session_id = ?;", (session_id,))
        conn.commit()

    def rebuild_from_sessions(self, sessions_dir: Path):
        """Scan all JSON session files and index their messages.

        Idempotent — skips messages whose msg_id already exists.
        Use :meth:`clear` first to force a full rebuild.
        """
        conn = self._get_conn()
        indexed = 0
        skipped = 0

        # Determine which msg_ids already exist
        existing = set()
        try:
            rows = conn.execute("SELECT msg_id FROM message_fts WHERE msg_id != '';").fetchall()
            existing = {r[0] for r in rows}
        except Exception:
            pass

        for pattern in ("*/*/*/*.json", "*.json"):
            for path in sorted(sessions_dir.glob(pattern)):
                try:
                    data = json.loads(path.read_text())
                    sid = data.get("id", path.stem)
                    for i, msg in enumerate(data.get("messages", [])):
                        msg_id = f"{sid}_{i}"
                        if msg_id in existing:
                            skipped += 1
                            continue
                        content = msg.get("content", "")
                        if not content.strip():
                            continue
                        conn.execute(
                            "INSERT INTO message_fts (session_id, role, content, timestamp, msg_id) "
                            "VALUES (?, ?, ?, ?, ?);",
                            (sid, msg.get("role", ""), content,
                             msg.get("timestamp", ""), msg_id),
                        )
                        indexed += 1
                except Exception as e:
                    logger.debug(f"FTS rebuild skipped {path}: {e}")

        conn.commit()
        if indexed or skipped:
            logger.info(
                f"FTS index: {indexed} new messages indexed, "
                f"{skipped} already indexed"
            )

    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """Keyword search across all indexed session messages.

        Parameters
        ----------
        query : str
            Free-text query (FTS5 syntax supported, e.g. ``"exact phrase"``).
        top_k : int
            Maximum results to return.

        Returns
        -------
        list[dict]
            Each dict has keys: session_id, role, content, timestamp, rank.
        """
        if not query or not query.strip():
            return []

        conn = self._get_conn()
        try:
            # FTS5 requires the query to be quoted or valid syntax
            # bm25 scoring is built-in
            rows = conn.execute(
                "SELECT session_id, role, content, timestamp, rank "
                "FROM message_fts "
                "WHERE message_fts MATCH ? "
                "ORDER BY rank "
                "LIMIT ?;",
                (query, top_k),
            ).fetchall()
            return [
                {
                    "session_id": r[0],
                    "role": r[1],
                    "content": r[2],
                    "timestamp": r[3],
                    "rank": r[4],
                }
                for r in rows
            ]
        except sqlite3.OperationalError as e:
            logger.debug(f"FTS5 query failed ('{query}'): {e}")
            return []

    def search_session(self, session_id: str, query: str,
                       top_k: int = 10) -> List[Dict]:
        """Keyword search scoped to a single session."""
        if not query or not query.strip():
            return []
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT session_id, role, content, timestamp, rank "
                "FROM message_fts "
                "WHERE message_fts MATCH ? AND session_id = ? "
                "ORDER BY rank "
                "LIMIT ?;",
                (query, session_id, top_k),
            ).fetchall()
            return [
                {
                    "session_id": r[0],
                    "role": r[1],
                    "content": r[2],
                    "timestamp": r[3],
                    "rank": r[4],
                }
                for r in rows
            ]
        except sqlite3.OperationalError as e:
            logger.debug(f"FTS5 session query failed ('{query}'): {e}")
            return []

    def clear(self):
        """Remove all indexed messages (for full rebuild)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM message_fts;")
        conn.commit()

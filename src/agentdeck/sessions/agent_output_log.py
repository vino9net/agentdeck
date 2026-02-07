"""SQLite-backed output log with full-text search."""

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LogChunk:
    """A captured chunk of terminal output."""

    id: int
    session_id: str
    ts: float
    content: str


@dataclass
class SearchResult:
    """A search match with FTS5 snippet."""

    id: int
    session_id: str
    ts: float
    snippet: str


@dataclass
class HistoryPage:
    """Paginated history response."""

    chunks: list[LogChunk] = field(default_factory=list)
    earliest_ts: float | None = None


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    ts REAL NOT NULL,
    content TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chunks_session_ts
    ON chunks(session_id, ts);
"""

_FTS_SCHEMA = """\
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
    USING fts5(content, content=chunks, content_rowid=id);
"""

_FTS_TRIGGERS = """\
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks
BEGIN
    INSERT INTO chunks_fts(rowid, content)
    VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks
BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks
BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO chunks_fts(rowid, content)
    VALUES (new.id, new.content);
END;
"""


class AgentOutputLog:
    """Append-only output log stored in SQLite with FTS5.

    Thread-safe: each call opens its own connection or
    reuses a cached one. Use WAL mode for concurrent
    reads during writes.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        conn.executescript(_FTS_SCHEMA)
        conn.executescript(_FTS_TRIGGERS)
        self._conn = conn
        return conn

    def append(self, session_id: str, lines: list[str]) -> None:
        """Insert a chunk of new lines for a session."""
        if not lines:
            return
        conn = self._connect()
        content = "\n".join(lines)
        conn.execute(
            "INSERT INTO chunks (session_id, ts, content) VALUES (?, ?, ?)",
            (session_id, time.time(), content),
        )
        conn.commit()

    def read(
        self,
        session_id: str,
        before: float | None = None,
        limit: int = 50,
    ) -> HistoryPage:
        """Read non-archived chunks, newest first.

        Args:
            session_id: Session to read.
            before: Only return chunks with ts < before.
                Omit for latest chunks.
            limit: Max chunks to return.

        Returns:
            HistoryPage with chunks and earliest_ts.
        """
        conn = self._connect()
        if before is not None:
            rows = conn.execute(
                "SELECT id, session_id, ts, content"
                " FROM chunks"
                " WHERE session_id = ?"
                "   AND ts < ? AND archived = 0"
                " ORDER BY ts DESC LIMIT ?",
                (session_id, before, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, session_id, ts, content"
                " FROM chunks"
                " WHERE session_id = ?"
                "   AND archived = 0"
                " ORDER BY ts DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()

        chunks = [
            LogChunk(
                id=r[0],
                session_id=r[1],
                ts=r[2],
                content=r[3],
            )
            for r in rows
        ]
        chunks.reverse()

        earliest_ts = chunks[0].ts if chunks else None
        return HistoryPage(chunks=chunks, earliest_ts=earliest_ts)

    def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Full-text search via FTS5.

        Args:
            query: Search query (FTS5 syntax).
            session_id: Scope to a single session, or
                None for cross-session search.
            limit: Max results to return.

        Returns:
            List of SearchResult with snippets.
        """
        conn = self._connect()
        if session_id is not None:
            rows = conn.execute(
                "SELECT c.id, c.session_id, c.ts,"
                " snippet(chunks_fts, 0, '<b>', '</b>',"
                " '...', 40)"
                " FROM chunks_fts f"
                " JOIN chunks c ON c.id = f.rowid"
                " WHERE f.content MATCH ?"
                " AND c.session_id = ?"
                " AND c.archived = 0"
                " ORDER BY f.rank"
                " LIMIT ?",
                (query, session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT c.id, c.session_id, c.ts,"
                " snippet(chunks_fts, 0, '<b>', '</b>',"
                " '...', 40)"
                " FROM chunks_fts f"
                " JOIN chunks c ON c.id = f.rowid"
                " WHERE f.content MATCH ?"
                " AND c.archived = 0"
                " ORDER BY f.rank"
                " LIMIT ?",
                (query, limit),
            ).fetchall()

        return [
            SearchResult(
                id=r[0],
                session_id=r[1],
                ts=r[2],
                snippet=r[3],
            )
            for r in rows
        ]

    def latest_ts(self, session_id: str) -> float | None:
        """Timestamp of the most recent chunk."""
        conn = self._connect()
        row = conn.execute(
            "SELECT MAX(ts) FROM chunks WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row[0] if row else None

    def soft_delete(self, session_id: str) -> None:
        """Mark all chunks for a session as archived."""
        conn = self._connect()
        conn.execute(
            "UPDATE chunks SET archived = 1 WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()

    def session_ids(self) -> list[str]:
        """Non-archived session IDs that have log data."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT DISTINCT session_id FROM chunks WHERE archived = 0",
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

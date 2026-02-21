"""Database layer - SQLite with full error handling."""

import sqlite3
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from src.db.models import Session, SessionStatus, Snapshot, CapturedWindow, ChromeTab, AppType

logger = logging.getLogger("workspace.db")

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    desktop_id TEXT UNIQUE,
    status TEXT DEFAULT 'active',
    created_at TEXT,
    updated_at TEXT,
    last_snapshot TEXT,
    total_duration INTEGER DEFAULT 0,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    captured_at TEXT,
    window_count INTEGER DEFAULT 0,
    tab_count INTEGER DEFAULT 0,
    is_final INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS captured_windows (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE CASCADE,
    hwnd INTEGER,
    process_name TEXT,
    window_title TEXT,
    app_type TEXT DEFAULT 'generic',
    exe_path TEXT,
    working_dir TEXT,
    cmd_args TEXT DEFAULT '[]',
    restore_cmd TEXT
);

CREATE TABLE IF NOT EXISTS chrome_tabs (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE CASCADE,
    window_id INTEGER,
    tab_id TEXT,
    url TEXT,
    title TEXT,
    is_pinned INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 0
);
"""


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        try:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
            self._conn.commit()
            logger.info(f"Database connected: {self.db_path}")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    @contextmanager
    def transaction(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            logger.error(f"Transaction failed: {e}")
            raise

    def create_session(self, session: Session) -> Session:
        now = datetime.now().isoformat()
        try:
            with self.transaction() as conn:
                # Check if session already exists for this desktop
                existing = conn.execute(
                    "SELECT * FROM sessions WHERE desktop_id = ?", 
                    (session.desktop_id,)
                ).fetchone()
                
                if existing:
                    logger.warning(f"Session already exists for desktop {session.desktop_id[:8]}")
                    return self._row_to_session(existing)
                
                cur = conn.execute(
                    "INSERT INTO sessions (name, desktop_id, status, created_at, updated_at) VALUES (?,?,?,?,?)",
                    (session.name, session.desktop_id, session.status.value, now, now)
                )
                session.id = cur.lastrowid
                session.created_at = datetime.fromisoformat(now)
                session.updated_at = session.created_at
            return session
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            raise

    def get_all_sessions(self) -> list[Session]:
        try:
            rows = self._conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
            return [self._row_to_session(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to get sessions: {e}")
            return []

    def create_snapshot(self, session_id: int) -> int:
        try:
            with self.transaction() as conn:
                cur = conn.execute(
                    "INSERT INTO snapshots (session_id, captured_at) VALUES (?,?)",
                    (session_id, datetime.now().isoformat())
                )
                return cur.lastrowid
        except Exception as e:
            logger.error(f"Failed to create snapshot: {e}")
            raise

    def save_windows(self, windows: list[CapturedWindow]):
        import json
        try:
            with self.transaction() as conn:
                conn.executemany(
                    "INSERT INTO captured_windows (session_id, snapshot_id, hwnd, process_name, window_title, app_type, exe_path, working_dir, cmd_args) VALUES (?,?,?,?,?,?,?,?,?)",
                    [(w.session_id, w.snapshot_id, w.hwnd, w.process_name, w.window_title, w.app_type.value, w.exe_path, w.working_dir, json.dumps(w.cmd_args)) for w in windows]
                )
        except Exception as e:
            logger.error(f"Failed to save windows: {e}")

    def save_tabs(self, tabs: list[ChromeTab]):
        try:
            with self.transaction() as conn:
                conn.executemany(
                    "INSERT INTO chrome_tabs (session_id, snapshot_id, window_id, tab_id, url, title, is_pinned, is_active) VALUES (?,?,?,?,?,?,?,?)",
                    [(t.session_id, t.snapshot_id, t.window_id, t.tab_id, t.url, t.title, int(t.is_pinned), int(t.is_active)) for t in tabs]
                )
        except Exception as e:
            logger.error(f"Failed to save tabs: {e}")

    def get_latest_snapshot_id(self, session_id: int) -> Optional[int]:
        try:
            row = self._conn.execute(
                "SELECT id FROM snapshots WHERE session_id=? ORDER BY captured_at DESC LIMIT 1",
                (session_id,)
            ).fetchone()
            return row["id"] if row else None
        except Exception as e:
            logger.error(f"Failed to get latest snapshot: {e}")
            return None

    def get_windows_for_snapshot(self, snapshot_id: int) -> list[CapturedWindow]:
        import json
        try:
            rows = self._conn.execute(
                "SELECT * FROM captured_windows WHERE snapshot_id=?", 
                (snapshot_id,)
            ).fetchall()
            return [
                CapturedWindow(
                    id=r["id"],
                    session_id=r["session_id"],
                    snapshot_id=r["snapshot_id"],
                    hwnd=r["hwnd"],
                    process_name=r["process_name"],
                    window_title=r["window_title"],
                    app_type=AppType(r["app_type"]),
                    exe_path=r["exe_path"],
                    working_dir=r["working_dir"],
                    cmd_args=json.loads(r["cmd_args"] or "[]"),
                    restore_cmd=r.get("restore_cmd")
                ) for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get windows: {e}")
            return []

    def get_tabs_for_snapshot(self, snapshot_id: int) -> list[ChromeTab]:
        try:
            rows = self._conn.execute(
                "SELECT * FROM chrome_tabs WHERE snapshot_id=?",
                (snapshot_id,)
            ).fetchall()
            return [
                ChromeTab(
                    id=r["id"],
                    session_id=r["session_id"],
                    snapshot_id=r["snapshot_id"],
                    window_id=r["window_id"],
                    tab_id=r["tab_id"],
                    url=r["url"],
                    title=r["title"],
                    is_pinned=bool(r["is_pinned"]),
                    is_active=bool(r["is_active"])
                ) for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get tabs: {e}")
            return []

    def delete_session(self, session_id: int):
        try:
            with self.transaction() as conn:
                conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            logger.info(f"Deleted session {session_id}")
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")

    def _row_to_session(self, row) -> Session:
        return Session(
            id=row["id"],
            name=row["name"],
            desktop_id=row["desktop_id"],
            status=SessionStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_snapshot=datetime.fromisoformat(row["last_snapshot"]) if row["last_snapshot"] else None,
            total_duration=row["total_duration"],
            notes=row["notes"] or ""
        )

    def close(self):
        if self._conn:
            self._conn.close()
            logger.info("Database closed")
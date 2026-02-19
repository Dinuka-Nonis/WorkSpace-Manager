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
                    "INSERT INTO captured_windows (session_id, snapshot_id, hwnd, process_name, window_title, app_type, exe_path, cmd_args) VALUES (?,?,?,?,?,?,?,?)",
                    [(w.session_id, w.snapshot_id, w.hwnd, w.process_name, w.window_title, w.app_type.value, w.exe_path, json.dumps(w.cmd_args)) for w in windows]
                )
        except Exception as e:
            logger.error(f"Failed to save windows: {e}")

    def _row_to_session(self, row) -> Session:
        return Session(
            id=row["id"],
            name=row["name"],
            desktop_id=row["desktop_id"],
            status=SessionStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def close(self):
        if self._conn:
            self._conn.close()

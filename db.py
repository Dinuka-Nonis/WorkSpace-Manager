"""
db.py — SQLite persistence layer for WorkSpace Manager.

Tables:
  sessions      — named workspaces
  session_items — files, URLs, and apps belonging to a session
"""

import sqlite3
import os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.getenv("APPDATA", ".")) / "WorkSpaceManager" / "workspace.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL,
                icon         TEXT DEFAULT '🗂',
                description  TEXT DEFAULT '',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS session_items (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                type          TEXT NOT NULL CHECK(type IN ('file', 'url', 'app')),
                path_or_url   TEXT NOT NULL,
                label         TEXT NOT NULL,
                added_at      TEXT NOT NULL,
                last_opened_at TEXT
            );
        """)


# ─── SESSIONS ────────────────────────────────────────────────────────────────

def create_session(name: str, icon: str = "🗂", description: str = "") -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (name, icon, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, icon, description, now, now)
        )
        return cur.lastrowid


def get_all_sessions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_session(session_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def update_session(session_id: int, name: str = None, icon: str = None, description: str = None):
    session = get_session(session_id)
    if not session:
        return
    now = datetime.now().isoformat()
    new_name  = name        if name        is not None else session["name"]
    new_icon  = icon        if icon        is not None else session["icon"]
    new_desc  = description if description is not None else session["description"]
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET name=?, icon=?, description=?, updated_at=? WHERE id=?",
            (new_name, new_icon, new_desc, now, session_id)
        )


def delete_session(session_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))


def touch_session(session_id: int):
    """Update updated_at to now (call after any item change)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?",
            (datetime.now().isoformat(), session_id)
        )


# ─── SESSION ITEMS ────────────────────────────────────────────────────────────

def add_item(session_id: int, item_type: str, path_or_url: str, label: str) -> int:
    """
    Add a file, URL, or app to a session.
    item_type must be one of: 'file', 'url', 'app'
    """
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO session_items (session_id, type, path_or_url, label, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, item_type, path_or_url, label, now)
        )
        item_id = cur.lastrowid
        # Touch in same connection
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id)
        )
    return item_id


def get_items(session_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM session_items WHERE session_id=? ORDER BY added_at ASC",
            (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_item(item_id: int):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT session_id FROM session_items WHERE id=?", (item_id,)
        ).fetchone()
        conn.execute("DELETE FROM session_items WHERE id=?", (item_id,))
        if row:
            # Update in the same connection to avoid nested-transaction lock
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (now, row["session_id"])
            )


def mark_item_opened(item_id: int):
    """Record the last time this item was opened."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE session_items SET last_opened_at=? WHERE id=?",
            (datetime.now().isoformat(), item_id)
        )


def update_item_label(item_id: int, label: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT session_id FROM session_items WHERE id=?", (item_id,)
        ).fetchone()
        conn.execute(
            "UPDATE session_items SET label=? WHERE id=?",
            (label, item_id)
        )
        if row:
            touch_session(row["session_id"])


# ─── STATS ───────────────────────────────────────────────────────────────────

def get_session_stats(session_id: int) -> dict:
    items = get_items(session_id)
    counts = {"file": 0, "url": 0, "app": 0}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    return {
        "total":  len(items),
        "files":  counts["file"],
        "urls":   counts["url"],
        "apps":   counts["app"],
        "items":  items,
    }
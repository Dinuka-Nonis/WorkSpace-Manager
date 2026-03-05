"""
db.py — SQLite persistence layer for WorkSpace Manager.

Tables:
  sessions      — named workspaces (with status, desktop id, time tracking)
  session_items — files, URLs, and apps belonging to a session
  windows       — snapshot of open windows per session
  chrome_tabs   — snapshot of Chrome tabs per session
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
    """Create tables if they don't exist. Safe to call multiple times (idempotent)."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                name                TEXT NOT NULL,
                icon                TEXT DEFAULT '🗂',
                description         TEXT DEFAULT '',
                status              TEXT DEFAULT 'idle',
                virtual_desktop_id  TEXT DEFAULT NULL,
                time_spent          INTEGER DEFAULT 0,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS session_items (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id     INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                type           TEXT NOT NULL CHECK(type IN ('file', 'url', 'app')),
                path_or_url    TEXT NOT NULL,
                label          TEXT NOT NULL,
                added_at       TEXT NOT NULL,
                last_opened_at TEXT
            );

            CREATE TABLE IF NOT EXISTS windows (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                hwnd        INTEGER,
                title       TEXT,
                exe_name    TEXT,
                exe_path    TEXT,
                pid         INTEGER,
                saved_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chrome_tabs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                tab_id       INTEGER,
                title        TEXT,
                url          TEXT NOT NULL,
                fav_icon_url TEXT DEFAULT '',
                window_id    INTEGER,
                active       INTEGER DEFAULT 0,
                pinned       INTEGER DEFAULT 0,
                saved_at     TEXT NOT NULL
            );
        """)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection):
    """Add new columns to existing tables without losing data."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    migrations = {
        "status":             "ALTER TABLE sessions ADD COLUMN status TEXT DEFAULT 'idle'",
        "virtual_desktop_id": "ALTER TABLE sessions ADD COLUMN virtual_desktop_id TEXT DEFAULT NULL",
        "time_spent":         "ALTER TABLE sessions ADD COLUMN time_spent INTEGER DEFAULT 0",
    }
    for col, sql in migrations.items():
        if col not in existing:
            try:
                conn.execute(sql)
            except Exception:
                pass


# ─── SESSIONS ────────────────────────────────────────────────────────────────

def create_session(name: str, icon: str = "🗂", virtual_desktop_id: str = None, description: str = "") -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (name, icon, description, status, virtual_desktop_id, time_spent, created_at, updated_at) "
            "VALUES (?, ?, ?, 'idle', ?, 0, ?, ?)",
            (name, icon, description, virtual_desktop_id, now, now)
        )
        return cur.lastrowid


def get_all_sessions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_session(session_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None


def update_session(session_id: int, name: str = None, icon: str = None, description: str = None):
    session = get_session(session_id)
    if not session:
        return
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET name=?, icon=?, description=?, updated_at=? WHERE id=?",
            (
                name        if name        is not None else session["name"],
                icon        if icon        is not None else session["icon"],
                description if description is not None else session["description"],
                now, session_id,
            )
        )


def update_session_status(session_id: int, status: str):
    """Set session status: 'active' | 'paused' | 'idle'."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET status=?, updated_at=? WHERE id=?",
            (status, datetime.now().isoformat(), session_id)
        )


def delete_session(session_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))


def touch_session(session_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?",
            (datetime.now().isoformat(), session_id)
        )


def add_session_time(session_id: int, seconds: int):
    """Add seconds to a session's total time_spent counter."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET time_spent = time_spent + ? WHERE id=?",
            (seconds, session_id)
        )


# ─── SESSION ITEMS ────────────────────────────────────────────────────────────

def add_item(session_id: int, item_type: str, path_or_url: str, label: str) -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO session_items (session_id, type, path_or_url, label, added_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, item_type, path_or_url, label, now)
        )
        item_id = cur.lastrowid
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
    return item_id


def get_items(session_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM session_items WHERE session_id=? ORDER BY added_at ASC", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_item(item_id: int):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        row = conn.execute("SELECT session_id FROM session_items WHERE id=?", (item_id,)).fetchone()
        conn.execute("DELETE FROM session_items WHERE id=?", (item_id,))
        if row:
            conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, row["session_id"]))


def mark_item_opened(item_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE session_items SET last_opened_at=? WHERE id=?",
            (datetime.now().isoformat(), item_id)
        )


def update_item_label(item_id: int, label: str):
    with get_conn() as conn:
        row = conn.execute("SELECT session_id FROM session_items WHERE id=?", (item_id,)).fetchone()
        conn.execute("UPDATE session_items SET label=? WHERE id=?", (label, item_id))
        if row:
            touch_session(row["session_id"])


# ─── WINDOWS SNAPSHOT ─────────────────────────────────────────────────────────

def save_snapshot(session_id: int, windows: list[dict], tabs: list[dict]):
    """Replace the stored window + tab snapshot for a session."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM windows WHERE session_id=?", (session_id,))
        for w in windows:
            conn.execute(
                "INSERT INTO windows (session_id, hwnd, title, exe_name, exe_path, pid, saved_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, w.get("hwnd"), w.get("title", ""), w.get("exe_name", ""),
                 w.get("exe_path", ""), w.get("pid"), now)
            )

        conn.execute("DELETE FROM chrome_tabs WHERE session_id=?", (session_id,))
        for t in tabs:
            conn.execute(
                "INSERT INTO chrome_tabs (session_id, tab_id, title, url, fav_icon_url, window_id, active, pinned, saved_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, t.get("tab_id") or t.get("id"), t.get("title", ""), t.get("url", ""),
                 t.get("fav_icon_url", "") or t.get("favIconUrl", ""),
                 t.get("window_id") or t.get("windowId"),
                 int(bool(t.get("active", False))), int(bool(t.get("pinned", False))), now)
            )

        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))


def get_windows(session_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM windows WHERE session_id=? ORDER BY id ASC", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def save_chrome_tabs(session_id: int, tabs: list[dict]):
    """Save Chrome tabs from the native host (replaces existing)."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM chrome_tabs WHERE session_id=?", (session_id,))
        for t in tabs:
            conn.execute(
                "INSERT INTO chrome_tabs (session_id, tab_id, title, url, fav_icon_url, window_id, active, pinned, saved_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, t.get("tab_id") or t.get("id"), t.get("title", ""), t.get("url", ""),
                 t.get("fav_icon_url", "") or t.get("favIconUrl", ""),
                 t.get("window_id") or t.get("windowId"),
                 int(bool(t.get("active", False))), int(bool(t.get("pinned", False))), now)
            )


def get_chrome_tabs(session_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM chrome_tabs WHERE session_id=? ORDER BY id ASC", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ─── STATS ───────────────────────────────────────────────────────────────────

def get_session_stats(session_id: int) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM session_items WHERE session_id=? ORDER BY added_at ASC", (session_id,)
        ).fetchall()
        items = [dict(r) for r in rows]

    counts = {"file": 0, "url": 0, "app": 0}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1

    return {"total": len(items), "files": counts["file"], "urls": counts["url"],
            "apps": counts["app"], "items": items}


def get_all_session_stats() -> dict[int, dict]:
    """
    Return stats for ALL sessions in a single query — avoids N+1 on the grid.
    Returns {session_id: {total, files, urls, apps}}
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT session_id, type, COUNT(*) as cnt "
            "FROM session_items GROUP BY session_id, type"
        ).fetchall()

    result: dict[int, dict] = {}
    for row in rows:
        sid = row["session_id"]
        if sid not in result:
            result[sid] = {"total": 0, "files": 0, "urls": 0, "apps": 0}
        count = row["cnt"]
        result[sid]["total"] += count
        if row["type"] == "file":   result[sid]["files"] += count
        elif row["type"] == "url":  result[sid]["urls"]  += count
        elif row["type"] == "app":  result[sid]["apps"]  += count
    return result
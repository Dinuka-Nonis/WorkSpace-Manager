"""
db.py — SQLite persistence layer for WorkSpace Manager
Tables: sessions, windows, chrome_tabs, snapshots
"""

import sqlite3
import json
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
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                icon        TEXT DEFAULT '🗂',
                description TEXT DEFAULT '',
                status      TEXT DEFAULT 'active',   -- active | paused | idle
                virtual_desktop_id TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                total_seconds INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS windows (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                hwnd        INTEGER,
                title       TEXT,
                exe_path    TEXT,
                exe_name    TEXT,
                pid         INTEGER,
                snapshot_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chrome_tabs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                tab_id      INTEGER,
                title       TEXT,
                url         TEXT,
                favicon_url TEXT,
                captured_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                snapshot_at TEXT NOT NULL,
                window_count INTEGER DEFAULT 0,
                tab_count   INTEGER DEFAULT 0,
                raw_json    TEXT
            );
        """)


# ─── SESSIONS ────────────────────────────────────────────────────────────────

def create_session(name: str, icon: str = "🗂", virtual_desktop_id: str = None) -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (name, icon, status, virtual_desktop_id, created_at, updated_at) "
            "VALUES (?, ?, 'active', ?, ?, ?)",
            (name, icon, virtual_desktop_id, now, now)
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


def get_session_by_desktop(desktop_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE virtual_desktop_id=? ORDER BY created_at DESC LIMIT 1",
            (desktop_id,)
        ).fetchone()
        return dict(row) if row else None


def update_session_status(session_id: int, status: str):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET status=?, updated_at=? WHERE id=?",
            (status, now, session_id)
        )


def update_session_name(session_id: int, name: str):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET name=?, updated_at=? WHERE id=?",
            (name, now, session_id)
        )


def delete_session(session_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))


def add_session_time(session_id: int, seconds: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET total_seconds = total_seconds + ?, updated_at=? WHERE id=?",
            (seconds, datetime.now().isoformat(), session_id)
        )


# ─── WINDOWS ─────────────────────────────────────────────────────────────────

def save_windows(session_id: int, windows: list[dict]):
    """Replace all window records for this session with fresh snapshot."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM windows WHERE session_id=?", (session_id,))
        conn.executemany(
            "INSERT INTO windows (session_id, hwnd, title, exe_path, exe_name, pid, snapshot_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (session_id, w.get("hwnd"), w.get("title"), w.get("exe_path"),
                 w.get("exe_name"), w.get("pid"), now)
                for w in windows
            ]
        )


def get_windows(session_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM windows WHERE session_id=? ORDER BY id",
            (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ─── CHROME TABS ─────────────────────────────────────────────────────────────

def save_chrome_tabs(session_id: int, tabs: list[dict]):
    """Replace all chrome tab records for this session."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM chrome_tabs WHERE session_id=?", (session_id,))
        conn.executemany(
            "INSERT INTO chrome_tabs (session_id, tab_id, title, url, favicon_url, captured_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (session_id, t.get("id"), t.get("title"), t.get("url"),
                 t.get("favIconUrl", ""), now)
                for t in tabs
            ]
        )


def get_chrome_tabs(session_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM chrome_tabs WHERE session_id=? ORDER BY id",
            (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ─── SNAPSHOTS ───────────────────────────────────────────────────────────────

def save_snapshot(session_id: int, windows: list[dict], tabs: list[dict]):
    now = datetime.now().isoformat()
    raw = json.dumps({"windows": windows, "tabs": tabs})
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO snapshots (session_id, snapshot_at, window_count, tab_count, raw_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, now, len(windows), len(tabs), raw)
        )
    save_windows(session_id, windows)
    save_chrome_tabs(session_id, tabs)


def get_session_stats(session_id: int) -> dict:
    windows = get_windows(session_id)
    tabs = get_chrome_tabs(session_id)
    session = get_session(session_id)

    # Unique apps (by exe_name, excluding system processes)
    apps = list({w["exe_name"] for w in windows if w["exe_name"] and
                 w["exe_name"].lower() not in ("explorer.exe", "dwm.exe", "winlogon.exe")})

    total_secs = session.get("total_seconds", 0) if session else 0
    hours, rem = divmod(total_secs, 3600)
    mins = rem // 60
    if hours > 0:
        duration = f"{hours}h {mins}m"
    elif mins > 0:
        duration = f"{mins}m"
    else:
        duration = "< 1m"

    return {
        "app_count": len(apps),
        "apps": apps[:6],  # top 6
        "tab_count": len(tabs),
        "window_count": len(windows),
        "duration": duration,
    }

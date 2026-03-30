"""
db.py — SQLite persistence layer for WorkSpace Manager.

save_chrome_tabs fix:
  • Tab with confirmed profile_dir  → chrome-profile:<dir>|<url>   (green badge)
  • Tab with profile_email but no dir → chrome-profile-email:<email>|<url>  (amber ⚠)
  • Tab with neither                → SKIPPED (no wrong-profile saves)
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
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT NOT NULL,
                icon             TEXT DEFAULT '🗂',
                description      TEXT DEFAULT '',
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                type            TEXT NOT NULL CHECK(type IN ('file', 'url', 'app')),
                path_or_url     TEXT NOT NULL,
                label           TEXT NOT NULL,
                added_at        TEXT NOT NULL,
                last_opened_at  TEXT
            );
        """)
        _add_column_if_missing(conn, "sessions", "last_restored_at", "TEXT")
        _add_column_if_missing(conn, "sessions", "status",           "TEXT DEFAULT ''")


def _add_column_if_missing(conn, table, column, col_def):
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    except sqlite3.OperationalError:
        pass


# ─── SESSIONS ────────────────────────────────────────────────────────────────

def create_session(name, icon="🗂", description="") -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (name,icon,description,created_at,updated_at) VALUES (?,?,?,?,?)",
            (name, icon, description, now, now))
        return cur.lastrowid


def get_all_sessions() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()]


def get_session(session_id) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None


def update_session(session_id, name=None, icon=None, description=None):
    s = get_session(session_id)
    if not s: return
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET name=?,icon=?,description=?,updated_at=? WHERE id=?",
            (name or s["name"], icon or s["icon"], description if description is not None else s["description"], now, session_id))


def update_session_status(session_id, status):
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET status=? WHERE id=?", (status, session_id))


def delete_session(session_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))


def touch_session(session_id):
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?",
                     (datetime.now().isoformat(), session_id))


def touch_session_restored(session_id):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET last_restored_at=?,updated_at=? WHERE id=?",
                     (now, now, session_id))


# ─── SESSION ITEMS ────────────────────────────────────────────────────────────

def add_item(session_id, item_type, path_or_url, label) -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO session_items (session_id,type,path_or_url,label,added_at) VALUES (?,?,?,?,?)",
            (session_id, item_type, path_or_url, label, now))
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        return cur.lastrowid


def add_items_bulk(session_id, items: list[dict]) -> list[int]:
    if not items: return []
    now = datetime.now().isoformat()
    ids = []
    with get_conn() as conn:
        existing = set(
            (r["type"], r["path_or_url"]) for r in conn.execute(
                "SELECT type,path_or_url FROM session_items WHERE session_id=?",
                (session_id,)).fetchall())
        for item in items:
            key = (item["type"], item["path_or_url"])
            if key in existing: continue
            existing.add(key)
            cur = conn.execute(
                "INSERT INTO session_items (session_id,type,path_or_url,label,added_at) VALUES (?,?,?,?,?)",
                (session_id, item["type"], item["path_or_url"], item["label"], now))
            ids.append(cur.lastrowid)
        if ids:
            conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
    return ids


def get_items(session_id) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM session_items WHERE session_id=? ORDER BY added_at ASC",
            (session_id,)).fetchall()]


def delete_item(item_id):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        row = conn.execute("SELECT session_id FROM session_items WHERE id=?", (item_id,)).fetchone()
        conn.execute("DELETE FROM session_items WHERE id=?", (item_id,))
        if row:
            conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, row["session_id"]))


def mark_item_opened(item_id):
    with get_conn() as conn:
        conn.execute("UPDATE session_items SET last_opened_at=? WHERE id=?",
                     (datetime.now().isoformat(), item_id))


def update_item_label(item_id, label):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        row = conn.execute("SELECT session_id FROM session_items WHERE id=?", (item_id,)).fetchone()
        conn.execute("UPDATE session_items SET label=? WHERE id=?", (label, item_id))
        if row:
            conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, row["session_id"]))


# ─── CHROME TABS (native host) ────────────────────────────────────────────────

def save_chrome_tabs(session_id: int, tabs: list[dict]):
    """
    Called by the native host when Chrome sends a tabs_snapshot.

    Profile attribution rules:
      profile_dir confirmed  → chrome-profile:<dir>|<url>          green badge
      profile_email only     → chrome-profile-email:<email>|<url>  amber ⚠ badge
      neither                → SKIPPED — no wrong-profile guessing
    """
    items   = []
    skipped = 0

    for t in tabs:
        url = (t.get("url") or "").strip()
        if not url:
            continue

        title         = (t.get("title") or url).strip()
        profile_dir   = (t.get("profile_dir")   or "").strip()
        profile_name  = (t.get("profile_name")  or "").strip()
        profile_email = (t.get("profile_email") or "").strip()

        if profile_dir:
            path_or_url  = f"chrome-profile:{profile_dir}|{url}"
            display_name = profile_name or profile_dir
            label        = f"[{display_name}] {title}"

        elif profile_email:
            # Host couldn't confirm dir; store with email so restore can retry.
            path_or_url = f"chrome-profile-email:{profile_email}|{url}"
            label       = f"[⚠ {profile_email}] {title}"
            print(f"[DB] save_chrome_tabs: no profile_dir for {url!r}, storing email hint")

        else:
            # No profile info at all — skip rather than guess "Default".
            skipped += 1
            continue

        items.append({"type": "url", "path_or_url": path_or_url, "label": label})

    if skipped:
        print(f"[DB] save_chrome_tabs: skipped {skipped} tab(s) with no profile info")

    add_items_bulk(session_id, items)


# ─── STATS ───────────────────────────────────────────────────────────────────

def get_session_stats(session_id) -> dict:
    items  = get_items(session_id)
    counts = {"file": 0, "url": 0, "app": 0}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    return {"total": len(items), "files": counts["file"],
            "urls": counts["url"], "apps": counts["app"], "items": items}

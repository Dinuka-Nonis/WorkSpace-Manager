"""
db.py — SQLite persistence layer for WorkSpace Manager.

Tables:
  sessions      — named workspaces
  session_items — files, URLs, and apps belonging to a session

save_chrome_tabs fix:
  Previously accepted tabs with empty profile_dir and used the bare URL,
  which meant tabs from ANY Chrome profile (including background ones) would
  get saved without attribution. Now:
    • Tabs with a confirmed profile_dir  → stored as chrome-profile:<dir>|<url>
    • Tabs with profile_email but no dir → stored with email hint so host can
      resolve later; label includes "?" profile marker so the user can see
      the profile wasn't fully confirmed.
    • Tabs with neither               → SKIPPED entirely. A tab with no
      profile info has no business being auto-added to a session.
  Plain (non-chrome-profile) URLs can still be added via the drop-zone
  drag path (which goes through drag_watcher, not this function).
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
    """Create tables and apply migrations."""
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


def _add_column_if_missing(conn, table: str, column: str, col_def: str):
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    except sqlite3.OperationalError:
        pass


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


def update_session(session_id: int, name: str = None, icon: str = None,
                   description: str = None):
    session = get_session(session_id)
    if not session:
        return
    now      = datetime.now().isoformat()
    new_name = name        if name        is not None else session["name"]
    new_icon = icon        if icon        is not None else session["icon"]
    new_desc = description if description is not None else session["description"]
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET name=?, icon=?, description=?, updated_at=? WHERE id=?",
            (new_name, new_icon, new_desc, now, session_id)
        )


def update_session_status(session_id: int, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET status=? WHERE id=?",
            (status, session_id)
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


def touch_session_restored(session_id: int):
    """Record the last time this session was restored."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET last_restored_at=?, updated_at=? WHERE id=?",
            (now, now, session_id)
        )


# ─── SESSION ITEMS ────────────────────────────────────────────────────────────

def add_item(session_id: int, item_type: str, path_or_url: str, label: str) -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO session_items (session_id, type, path_or_url, label, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, item_type, path_or_url, label, now)
        )
        item_id = cur.lastrowid
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id)
        )
    return item_id


def add_items_bulk(session_id: int, items: list[dict]) -> list[int]:
    """
    Insert multiple items in a single transaction.
    Each item: {type, path_or_url, label}
    Skips duplicates (same type + path_or_url already in session).
    Returns list of inserted IDs.
    """
    if not items:
        return []

    now = datetime.now().isoformat()
    ids: list[int] = []

    with get_conn() as conn:
        existing = set(
            (r["type"], r["path_or_url"])
            for r in conn.execute(
                "SELECT type, path_or_url FROM session_items WHERE session_id=?",
                (session_id,)
            ).fetchall()
        )

        for item in items:
            key = (item["type"], item["path_or_url"])
            if key in existing:
                continue
            existing.add(key)
            cur = conn.execute(
                "INSERT INTO session_items (session_id, type, path_or_url, label, added_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, item["type"], item["path_or_url"], item["label"], now)
            )
            ids.append(cur.lastrowid)

        if ids:
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id)
            )

    return ids


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
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (now, row["session_id"])
            )


def mark_item_opened(item_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE session_items SET last_opened_at=? WHERE id=?",
            (datetime.now().isoformat(), item_id)
        )


def update_item_label(item_id: int, label: str):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT session_id FROM session_items WHERE id=?", (item_id,)
        ).fetchone()
        conn.execute(
            "UPDATE session_items SET label=? WHERE id=?",
            (label, item_id)
        )
        if row:
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (now, row["session_id"])
            )


# ─── CHROME TABS (native host) ────────────────────────────────────────────────

def save_chrome_tabs(session_id: int, tabs: list[dict]):
    """
    Called by the native host when Chrome sends a tabs_snapshot.
    Upserts tabs as URL items — skips duplicates.

    Profile attribution rules (strict):
      1. tab has profile_dir  → store as chrome-profile:<dir>|<url>
                                label: [ProfileName] Title
      2. tab has profile_email but no profile_dir →
            host should have resolved the dir from Local State before calling
            this function. If it still can't, we store with email hint in the
            path so restore.py can at least try to match, and mark the label
            with "⚠" so the user sees it wasn't fully resolved.
      3. tab has neither profile_dir nor profile_email →
            SKIP — we have no idea which profile this came from.
            Saving a profileless URL causes the restore to open in whatever
            profile Chrome happens to have open, which is wrong.

    This function is NOT called for drag-drop adds — those go through
    drag_watcher._capture_window_info → drop_zone.on_dropped → db.add_item
    directly with the profile info already encoded in path_or_url.
    """
    items = []
    skipped = 0

    for t in tabs:
        url = t.get("url", "").strip()
        if not url:
            continue

        title        = t.get("title") or url
        profile_dir  = (t.get("profile_dir")  or "").strip()
        profile_name = (t.get("profile_name") or "").strip()
        profile_email = (t.get("profile_email") or "").strip()

        if profile_dir:
            # Best case: confirmed profile directory
            path_or_url = f"chrome-profile:{profile_dir}|{url}"
            display_name = profile_name or profile_dir
            label = f"[{display_name}] {title}"

        elif profile_email:
            # Partial info: we have an email but the host couldn't resolve the
            # directory (maybe Local State doesn't have this email mapped yet).
            # Store with email hint so restore can attempt a lookup.
            path_or_url = f"chrome-profile-email:{profile_email}|{url}"
            label = f"[⚠ {profile_email}] {title}"
            print(f"[DB] save_chrome_tabs: profile_dir missing for {url!r}, "
                  f"storing with email hint {profile_email!r}")

        else:
            # No profile info at all — skip to avoid wrong-profile restore.
            skipped += 1
            print(f"[DB] save_chrome_tabs: skipping {url!r} — no profile info")
            continue

        items.append({
            "type":        "url",
            "path_or_url": path_or_url,
            "label":       label,
        })

    if skipped:
        print(f"[DB] save_chrome_tabs: skipped {skipped} tab(s) with no profile info")

    add_items_bulk(session_id, items)


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

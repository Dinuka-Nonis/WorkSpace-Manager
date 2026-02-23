"""
daemon.py — WorkSpace daemon.

New architecture (v4):
  - On startup: scan ALL existing virtual desktops, create/update a session
    for each one that already has windows. No user prompt needed.
  - Every 8s: call snapshot_all_desktops() ONCE, distribute results to each
    session's DB record. No per-desktop API calls.
  - On desktop created: emit signal → show Spotlight for naming.
  - On desktop removed: save last known state, mark session idle.
  - On desktop switch: pause old session, resume new one.
"""

import sys
import time
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

import db
import snapshot as snap

DESKTOP_POLL_MS      = 500    # how often to check for desktop changes
SNAPSHOT_INTERVAL_MS = 8_000  # how often to snapshot all active desktops
TIME_TICK_MS         = 60_000 # how often to add time to active sessions


class WorkSpaceDaemon(QObject):
    new_desktop_detected  = pyqtSignal(str)  # desktop_id — show Spotlight
    snapshot_saved        = pyqtSignal(int)  # session_id
    chrome_tabs_received  = pyqtSignal(int, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prev_count: int = snap.get_desktop_count()
        self._prev_ids: set[str] = set(snap.get_all_desktop_ids())
        self._active_id: str | None = snap.get_current_desktop_id()

        # desktop_id → session_id  (in-memory map, rebuilt from DB on start)
        self._session_map: dict[str, int] = {}

        # int counter: suppress N upcoming new-desktop detections (used by restore)
        self._suppress_count: int = 0

        # Timestamp of last snapshot per session
        self._last_snap: dict[int, float] = {}

        # Restore existing desktop→session links from DB
        self._load_session_map()

    def _load_session_map(self):
        for s in db.get_all_sessions():
            did = s.get("virtual_desktop_id")
            if did and s["status"] in ("active", "paused"):
                self._session_map[did] = s["id"]

    # ── Startup ───────────────────────────────────────────────────────────────

    def start(self):
        """Call after QApplication exists. Scans all desktops then starts timers."""
        # Scan all existing desktops immediately
        self._scan_all_desktops_on_startup()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(DESKTOP_POLL_MS)

        self._snap_timer = QTimer(self)
        self._snap_timer.timeout.connect(self._snapshot_all)
        self._snap_timer.start(SNAPSHOT_INTERVAL_MS)

        self._time_timer = QTimer(self)
        self._time_timer.timeout.connect(self._tick_time)
        self._time_timer.start(TIME_TICK_MS)

    def stop(self):
        for t in (self._poll_timer, self._snap_timer, self._time_timer):
            t.stop()

    def _scan_all_desktops_on_startup(self):
        """
        On app launch: take one full snapshot across all desktops.
        For each desktop that has windows, ensure a session exists for it.
        For desktops in our session_map that no longer exist, mark idle.
        """
        print("[Daemon] Startup scan of all virtual desktops…")
        all_desktop_ids = snap.get_all_desktop_ids()
        current_id = snap.get_current_desktop_id()

        # Snapshot everything at once — this is O(1) call to pyvda
        all_windows = snap.snapshot_all_desktops()

        for desktop_id in all_desktop_ids:
            windows = all_windows.get(desktop_id, [])
            num = snap.get_desktop_number(desktop_id) or "?"
            print(f"[Daemon]   Desktop {num} ({desktop_id[:8]}…): {len(windows)} windows")

            if desktop_id in self._session_map:
                # Already have a session for this desktop — update its snapshot
                sid = self._session_map[desktop_id]
                status = "active" if desktop_id == current_id else "paused"
                db.update_session_status(sid, status)
                if windows:
                    tabs = db.get_chrome_tabs(sid)
                    db.save_snapshot(sid, windows, [dict(t) for t in tabs])
                    print(f"[Daemon]   Updated existing session {sid}")
            else:
                # New desktop we haven't seen before — if it has windows, auto-create
                # an unnamed session so data is captured immediately.
                # The user can name it later via the Spotlight prompt if they create
                # a NEW desktop; existing desktops get auto-named "Desktop N".
                if windows:
                    icon = "🖥"
                    name = f"Desktop {num}"
                    sid = db.create_session(name, icon, desktop_id)
                    self._session_map[desktop_id] = sid
                    status = "active" if desktop_id == current_id else "paused"
                    db.update_session_status(sid, status)
                    tabs = db.get_chrome_tabs(sid)
                    db.save_snapshot(sid, windows, [dict(t) for t in tabs])
                    print(f"[Daemon]   Auto-created session '{name}' (id={sid}) "
                          f"for existing desktop {desktop_id[:8]}…")

        # Mark sessions for desktops that no longer exist as idle
        existing = set(all_desktop_ids)
        for did, sid in list(self._session_map.items()):
            if did not in existing:
                db.update_session_status(sid, "idle")
                print(f"[Daemon]   Session {sid} orphaned (desktop gone) → idle")

        self._prev_ids = set(all_desktop_ids)
        self._prev_count = len(all_desktop_ids)
        self._active_id = current_id

    # ── Polling ───────────────────────────────────────────────────────────────

    def _poll(self):
        try:
            current_count  = snap.get_desktop_count()
            current_ids    = set(snap.get_all_desktop_ids())
            current_active = snap.get_current_desktop_id()

            if current_count > self._prev_count:
                # ── New desktop(s) ────────────────────────────────────────
                new_ids = current_ids - self._prev_ids
                self._active_id = current_active

                if self._suppress_count > 0:
                    self._suppress_count -= 1
                    print(f"[Daemon] Suppressed Spotlight for programmatic desktop(s): {new_ids}")
                else:
                    for did in new_ids:
                        self.new_desktop_detected.emit(did)

            elif current_count < self._prev_count:
                # ── Desktop(s) removed ────────────────────────────────────
                removed_ids = self._prev_ids - current_ids
                for did in removed_ids:
                    if did in self._session_map:
                        sid = self._session_map[did]
                        # Windows have already migrated to another desktop.
                        # Try to salvage them from current desktop by exe matching.
                        self._salvage_on_close(sid, current_active)
                        db.update_session_status(sid, "idle")
                        print(f"[Daemon] Desktop closed — session {sid} marked idle")
                        if self._active_id == did:
                            self._active_id = current_active

            else:
                # ── Desktop switch ────────────────────────────────────────
                if current_active and current_active != self._active_id:
                    old_id = self._active_id

                    # Snapshot old desktop NOW before leaving it
                    if old_id and old_id in self._session_map:
                        old_sid = self._session_map[old_id]
                        print(f"[Daemon] Leaving desktop — snapshotting session {old_sid}")
                        self._do_snapshot_for(old_sid, old_id)
                        db.update_session_status(old_sid, "paused")

                    if current_active in self._session_map:
                        db.update_session_status(
                            self._session_map[current_active], "active")

                    self._active_id = current_active

            self._prev_count = current_count
            self._prev_ids   = current_ids

        except Exception as e:
            print(f"[Daemon] _poll error (non-fatal): {e}")

    def _salvage_on_close(self, session_id: int, current_desktop_id: str):
        """
        When a desktop is closed, Windows moves its windows to another desktop.
        Try to find those windows on the current desktop by matching exe names.
        """
        prev_windows = db.get_windows(session_id)
        if not prev_windows:
            return

        known_exes = {w["exe_name"].lower() for w in prev_windows if w.get("exe_name")}
        if not known_exes:
            return

        all_windows = snap.snapshot_all_desktops()
        current_windows = all_windows.get(current_desktop_id, [])
        matched = [w for w in current_windows
                   if w.get("exe_name", "").lower() in known_exes]

        if matched:
            tabs = db.get_chrome_tabs(session_id)
            db.save_snapshot(session_id, matched, [dict(t) for t in tabs])
            print(f"[Daemon] Salvaged {len(matched)} windows for session {session_id} "
                  f"after desktop close")
        else:
            print(f"[Daemon] No matching windows found after desktop close — "
                  f"keeping {len(prev_windows)} previous windows for session {session_id}")

    # ── Snapshotting ──────────────────────────────────────────────────────────

    def _snapshot_all(self):
        """
        Called every 8s. Takes ONE snapshot across all desktops, then
        distributes each desktop's windows to its session in the DB.
        """
        try:
            all_windows = snap.snapshot_all_desktops()

            for desktop_id, session_id in list(self._session_map.items()):
                session = db.get_session(session_id)
                if not session or session["status"] not in ("active", "paused"):
                    continue

                windows = all_windows.get(desktop_id, [])
                self._save_snapshot_safe(session_id, windows)

        except Exception as e:
            print(f"[Daemon] _snapshot_all error (non-fatal): {e}")

    def _do_snapshot_for(self, session_id: int, desktop_id: str):
        """Snapshot a single session using already-available all_desktops data."""
        try:
            all_windows = snap.snapshot_all_desktops()
            windows = all_windows.get(desktop_id, [])
            self._save_snapshot_safe(session_id, windows)
        except Exception as e:
            print(f"[Daemon] _do_snapshot_for error: {e}")

    def _save_snapshot_safe(self, session_id: int, windows: list[dict]):
        """Save snapshot, but NEVER overwrite good data with an empty list."""
        tabs = db.get_chrome_tabs(session_id)

        if not windows:
            existing = db.get_windows(session_id)
            if existing:
                print(f"[Daemon] Snapshot empty for session {session_id} — "
                      f"keeping {len(existing)} previous windows")
                self._last_snap[session_id] = time.time()
                return
            # No previous data either — save the empty snapshot
        else:
            print(f"[Daemon] Saved {len(windows)} windows for session {session_id}")

        db.save_snapshot(session_id, windows, [dict(t) for t in tabs])
        self._last_snap[session_id] = time.time()
        self.snapshot_saved.emit(session_id)

    # ── Session management ────────────────────────────────────────────────────

    def suppress_next_new_desktop(self):
        """Call before programmatically creating a desktop (e.g. restore)."""
        self._suppress_count += 1

    def register_session(self, session_id: int, desktop_id: str):
        """Called after user names a session in Spotlight."""
        self._session_map[desktop_id] = session_id
        db.update_session_status(session_id, "active")
        # First snapshot after 2s — let user open their apps
        QTimer.singleShot(2_000, lambda: self._do_snapshot_for(session_id, desktop_id))

    def get_active_session_id(self) -> int | None:
        current = snap.get_current_desktop_id()
        return self._session_map.get(current) if current else None

    # ── Chrome tab handling ───────────────────────────────────────────────────

    def receive_chrome_tabs(self, session_id: int, tabs: list[dict]):
        db.save_chrome_tabs(session_id, tabs)
        self.chrome_tabs_received.emit(session_id, tabs)

    # ── Time tracking ─────────────────────────────────────────────────────────

    def _tick_time(self):
        try:
            for did, sid in list(self._session_map.items()):
                s = db.get_session(sid)
                if s and s["status"] == "active":
                    db.add_session_time(sid, 60)
        except Exception as e:
            print(f"[Daemon] _tick_time error (non-fatal): {e}")

    # ── Manual trigger ────────────────────────────────────────────────────────

    def force_snapshot(self):
        """Manually snapshot the active desktop (hotkey Win+Shift+S)."""
        current = snap.get_current_desktop_id()
        if current and current in self._session_map:
            self._do_snapshot_for(self._session_map[current], current)
            print(f"[Daemon] Force snapshot triggered for desktop {current[:8]}…")

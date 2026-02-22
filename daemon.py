"""
daemon.py — Core WorkSpace daemon.
Responsibilities:
  1. Poll virtual desktop count every 500ms — detect new desktops
  2. Snapshot windows on the current desktop every 30s
  3. Accumulate session time
  4. Accept chrome tab data from the native messaging host
  5. Signal the UI when events happen (uses Qt signals via QObject)
"""

import sys
import time
import threading
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

import db
import snapshot as snap

# How often to check for new virtual desktops (ms)
DESKTOP_POLL_MS = 500

# How often to snapshot windows (ms)
SNAPSHOT_INTERVAL_MS = 30_000

# How often to add time to active sessions (ms)
TIME_TICK_MS = 60_000


class WorkSpaceDaemon(QObject):
    """
    Qt-friendly daemon that runs polls via QTimer (no threads needed for UI signals).
    Emits signals that the main window / spotlight / HUD connect to.
    """

    # Emitted when a new virtual desktop is detected
    new_desktop_detected = pyqtSignal(str)   # desktop_id

    # Emitted after a snapshot has been saved (session_id)
    snapshot_saved = pyqtSignal(int)

    # Emitted when chrome tabs arrive from the native host
    chrome_tabs_received = pyqtSignal(int, list)  # session_id, tabs

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prev_desktop_count = snap.get_desktop_count()
        self._prev_desktop_ids: set[str] = set(snap.get_all_desktop_ids())
        self._active_desktop_id: str | None = snap.get_current_desktop_id()
        self._session_map: dict[str, int] = {}  # desktop_id -> session_id
        self._last_snapshot: dict[int, float] = {}  # session_id -> timestamp

        # Load existing desktop→session mappings from DB
        self._restore_desktop_map()

    def _restore_desktop_map(self):
        """Reload desktop-to-session map from saved sessions."""
        for session in db.get_all_sessions():
            if session.get("virtual_desktop_id") and session["status"] != "idle":
                self._session_map[session["virtual_desktop_id"]] = session["id"]

    # ── Timers ────────────────────────────────────────────────────────────────

    def start(self):
        """Start all polling timers. Call after QApplication is created."""
        self._desktop_timer = QTimer(self)
        self._desktop_timer.timeout.connect(self._poll_desktops)
        self._desktop_timer.start(DESKTOP_POLL_MS)

        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.timeout.connect(self._snapshot_all_active)
        self._snapshot_timer.start(SNAPSHOT_INTERVAL_MS)

        self._time_timer = QTimer(self)
        self._time_timer.timeout.connect(self._tick_time)
        self._time_timer.start(TIME_TICK_MS)

    def stop(self):
        for timer in (self._desktop_timer, self._snapshot_timer, self._time_timer):
            timer.stop()

    # ── Desktop polling ───────────────────────────────────────────────────────

    def _poll_desktops(self):
        current_count = snap.get_desktop_count()
        current_ids = set(snap.get_all_desktop_ids())

        if current_count > self._prev_desktop_count:
            # New desktop(s) created
            new_ids = current_ids - self._prev_desktop_ids
            for desktop_id in new_ids:
                self.new_desktop_detected.emit(desktop_id)

        # Detect desktop switches — pause old, mark new active
        current_active = snap.get_current_desktop_id()
        if current_active and current_active != self._active_desktop_id:
            # Pause old session
            if self._active_desktop_id and self._active_desktop_id in self._session_map:
                old_sid = self._session_map[self._active_desktop_id]
                db.update_session_status(old_sid, "paused")

            # Resume / mark new active session
            if current_active in self._session_map:
                new_sid = self._session_map[current_active]
                db.update_session_status(new_sid, "active")

            self._active_desktop_id = current_active

        self._prev_desktop_count = current_count
        self._prev_desktop_ids = current_ids

    # ── Session registration ──────────────────────────────────────────────────

    def register_session(self, session_id: int, desktop_id: str):
        """Called after user names a new session in the spotlight."""
        self._session_map[desktop_id] = session_id
        db.update_session_status(session_id, "active")
        # Immediately take first snapshot
        self._snapshot_session(session_id, desktop_id)

    def get_active_session_id(self) -> int | None:
        """Return the session_id for the current virtual desktop, if any."""
        current = snap.get_current_desktop_id()
        return self._session_map.get(current) if current else None

    # ── Snapshotting ──────────────────────────────────────────────────────────

    def _snapshot_all_active(self):
        for desktop_id, session_id in list(self._session_map.items()):
            session = db.get_session(session_id)
            if session and session["status"] == "active":
                self._snapshot_session(session_id, desktop_id)

    def _snapshot_session(self, session_id: int, desktop_id: str):
        windows = snap.snapshot_desktop(desktop_id)
        tabs = db.get_chrome_tabs(session_id)  # use last known tabs
        db.save_snapshot(session_id, windows, [dict(t) for t in tabs])
        self._last_snapshot[session_id] = time.time()
        self.snapshot_saved.emit(session_id)

    # ── Chrome tab handling ───────────────────────────────────────────────────

    def receive_chrome_tabs(self, session_id: int, tabs: list[dict]):
        """Called by the native messaging listener thread."""
        db.save_chrome_tabs(session_id, tabs)
        self.chrome_tabs_received.emit(session_id, tabs)

    # ── Time tracking ─────────────────────────────────────────────────────────

    def _tick_time(self):
        """Add 60s to all active sessions."""
        for desktop_id, session_id in list(self._session_map.items()):
            session = db.get_session(session_id)
            if session and session["status"] == "active":
                db.add_session_time(session_id, 60)

    # ── Manual snapshot trigger ───────────────────────────────────────────────

    def force_snapshot(self):
        """Manually trigger a snapshot of the active desktop."""
        current = snap.get_current_desktop_id()
        if current and current in self._session_map:
            self._snapshot_session(self._session_map[current], current)

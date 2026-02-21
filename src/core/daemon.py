"""Main daemon - orchestrates everything."""

import threading
import logging
import time
from datetime import datetime
from typing import Optional, Callable

from src.db.database import Database
from src.db.models import Session, SessionStatus
from src.core.desktop_watcher import DesktopWatcher
from src.core.window_capture import WindowCapture
from src.core.chrome_capture import ChromeCapture
from src.core.hotkeys import HotkeyManager

logger = logging.getLogger("workspace.daemon")


class WorkSpaceDaemon:
    def __init__(self, db: Database, config: dict):
        self.db = db
        self.config = config

        poll = config.get("capture", {}).get("poll_interval_sec", 5)
        self._poll_interval = poll
        self._active = {}  # desktop_id -> Session
        self._pending_prompts = set()  # Desktops that currently have a prompt open
        self._lock = threading.Lock()
        self._last_hotkey_time = 0  # Debounce hotkey
        
        self._watcher = DesktopWatcher(poll_interval=1.0)
        self._hotkeys = HotkeyManager(config)
        
        self._snapshot_thread = None
        self._running = False
        self._on_new_desktop_callbacks = []

    def start(self):
        logger.info("Daemon starting")
        self._running = True

        # Clean stale sessions and load active ones
        self._load_existing_sessions()

        # Wire desktop events
        self._watcher.on_new_desktop(self._handle_new_desktop)
        self._watcher.start()

        # Wire hotkeys
        self._hotkeys.on("new_session", self._handle_hotkey_new_session)
        self._hotkeys.start()

        # Start snapshot loop
        self._snapshot_thread = threading.Thread(target=self._snapshot_loop, daemon=True)
        self._snapshot_thread.start()

        logger.info("Daemon running")

    def stop(self):
        logger.info("Daemon stopping")
        self._running = False
        self._watcher.stop()
        self._hotkeys.stop()
        logger.info("Daemon stopped")

    def _load_existing_sessions(self):
        """Load sessions from DB and clean stale ones (desktop GUIDs change on reboot)."""
        sessions = self.db.get_all_sessions()
        
        # Get current valid desktop IDs
        current_desktop_ids = set(self._watcher.get_all_desktop_ids())
        current_desktop_ids.add(self._watcher.get_current_desktop_id())  # Include current
        
        active_count = 0
        stale_count = 0
        
        with self._lock:
            for s in sessions:
                # Check if this session's desktop still exists
                if s.desktop_id in current_desktop_ids:
                    # Desktop still exists - keep it active
                    self._active[s.desktop_id] = s
                    active_count += 1
                    logger.info(f"  ✓ Restored session: '{s.name}' on desktop {s.desktop_id[:8]}")
                else:
                    # Desktop no longer exists (reboot happened) - mark as stale
                    stale_count += 1
                    logger.debug(f"  ✗ Stale session: '{s.name}' (desktop {s.desktop_id[:8]} no longer exists)")
        
        logger.info(f"Loaded {active_count} active sessions, found {stale_count} stale sessions")
        
        if stale_count > 0:
            logger.info(f"Note: {stale_count} sessions are from previous Windows sessions (desktop IDs changed after reboot)")

    def create_session(self, name: str, desktop_id: str) -> Session:
        # Remove from pending prompts
        with self._lock:
            self._pending_prompts.discard(desktop_id)
            
            # Check if already exists
            if desktop_id in self._active:
                logger.warning(f"Session already exists for desktop {desktop_id[:8]}")
                return self._active[desktop_id]
        
        try:
            session = self.db.create_session(Session(
                id=None,
                name=name,
                desktop_id=desktop_id,
                status=SessionStatus.ACTIVE,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ))
            with self._lock:
                self._active[desktop_id] = session
            logger.info(f"✓ Session created: '{name}' on desktop {desktop_id[:8]}")
            return session
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            raise

    def cancel_session(self, desktop_id: str):
        """Called when user presses Esc - clear pending prompt."""
        with self._lock:
            self._pending_prompts.discard(desktop_id)
        logger.info(f"Session cancelled for desktop {desktop_id[:8]}")

    def get_all_sessions(self) -> list[Session]:
        return self.db.get_all_sessions()

    def on_new_desktop_detected(self, cb: Callable[[str], None]):
        self._on_new_desktop_callbacks.append(cb)

    def _handle_new_desktop(self, desktop_id: str):
        with self._lock:
            # Skip if already has a session
            if desktop_id in self._active:
                logger.debug(f"Desktop {desktop_id[:8]} already has a session, skipping")
                return
            
            # Skip if prompt already open for this desktop
            if desktop_id in self._pending_prompts:
                logger.debug(f"Prompt already open for desktop {desktop_id[:8]}, skipping")
                return
            
            # Mark as having a pending prompt
            self._pending_prompts.add(desktop_id)
        
        logger.info(f"→ Showing prompt for desktop: {desktop_id[:8]}")
        for cb in self._on_new_desktop_callbacks:
            cb(desktop_id)

    def _handle_hotkey_new_session(self):
        # Debounce - ignore if called within 500ms
        now = time.time()
        if now - self._last_hotkey_time < 0.5:
            logger.debug("Hotkey debounced (too fast)")
            return
        self._last_hotkey_time = now
        
        # Get current desktop
        desktop_id = self._watcher.get_current_desktop_id()
        if not desktop_id:
            logger.warning("Could not get current desktop ID")
            return
        
        logger.info(f"⌨ Hotkey triggered on desktop: {desktop_id[:8]}")
        self._handle_new_desktop(desktop_id)

    def _snapshot_loop(self):
        while self._running:
            time.sleep(self._poll_interval)
            try:
                self._take_all_snapshots()
            except Exception as e:
                logger.exception(f"Snapshot error: {e}")

    def _take_all_snapshots(self):
        with self._lock:
            active_sessions = dict(self._active)

        for desktop_id, session in active_sessions.items():
            if not session.id:
                continue
            try:
                snap_id = self.db.create_snapshot(session.id)

                wc = WindowCapture(session.id, desktop_id)
                windows = wc.capture(snap_id)
                if windows:
                    self.db.save_windows(windows)

                cc = ChromeCapture(session.id)
                tabs = cc.capture(snap_id)
                if tabs:
                    self.db.save_tabs(tabs)

                logger.debug(f"📸 Snapshot '{session.name}': {len(windows)} windows, {len(tabs)} tabs")
            except Exception as e:
                logger.error(f"Snapshot failed for '{session.name}': {e}")
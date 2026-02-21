"""Virtual desktop watcher - polls for changes."""

import threading
import logging
import time
from typing import Callable, Optional

try:
    import pyvda
    PYVDA_AVAILABLE = True
except ImportError:
    PYVDA_AVAILABLE = False

logger = logging.getLogger("workspace.desktop")


class DesktopWatcher:
    def __init__(self, poll_interval: float = 1.0):
        self.poll_interval = poll_interval
        self._running = False
        self._thread = None
        self._known_desktops = set()
        self._current_desktop = None
        self._on_new_desktop = []

    def on_new_desktop(self, cb: Callable[[str], None]):
        self._on_new_desktop.append(cb)

    def get_current_desktop_id(self) -> Optional[str]:
        if not PYVDA_AVAILABLE:
            return "mock-desktop-id"
        try:
            return str(pyvda.VirtualDesktop.current().id)
        except Exception as e:
            logger.error(f"Failed to get desktop: {e}")
            return None

    def get_all_desktop_ids(self) -> list[str]:
        if not PYVDA_AVAILABLE:
            return []
        try:
            return [str(d.id) for d in pyvda.VirtualDesktop.list()]
        except:
            return []

    def start(self):
        if self._running:
            return
        self._running = True
        self._known_desktops = set(self.get_all_desktop_ids())
        self._current_desktop = self.get_current_desktop_id()

        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("DesktopWatcher started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("DesktopWatcher stopped")

    def _poll_loop(self):
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.exception(f"Watcher error: {e}")
            time.sleep(self.poll_interval)

    def _tick(self):
        all_ids = set(self.get_all_desktop_ids())
        current_id = self.get_current_desktop_id()

        new_desktops = all_ids - self._known_desktops
        for desk_id in new_desktops:
            logger.info(f"New desktop: {desk_id[:8]}")
            for cb in self._on_new_desktop:
                cb(desk_id)

        self._known_desktops = all_ids
        self._current_desktop = current_id
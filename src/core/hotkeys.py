"""Global hotkey manager."""

import logging
import threading
from typing import Callable

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

logger = logging.getLogger("workspace.hotkeys")


class HotkeyManager:
    def __init__(self, config: dict):
        hk = config.get("hotkeys", {})
        self._hk_new_session = hk.get("new_session", "ctrl+win+d")
        self._hk_toggle_hud = hk.get("toggle_hud", "win+grave")
        
        self._handlers = {
            "new_session": [],
            "toggle_hud": [],
        }
        self._registered = False

    def on(self, event: str, handler: Callable):
        if event not in self._handlers:
            raise ValueError(f"Unknown event: {event}")
        self._handlers[event].append(handler)

    def start(self):
        if not KEYBOARD_AVAILABLE:
            logger.warning("keyboard library not available - hotkeys disabled")
            return
        if self._registered:
            return

        def _fire(event: str):
            def _inner():
                for h in self._handlers[event]:
                    threading.Thread(target=h, daemon=True).start()
            return _inner

        try:
            keyboard.add_hotkey(self._hk_new_session, _fire("new_session"), suppress=False)
            keyboard.add_hotkey(self._hk_toggle_hud, _fire("toggle_hud"), suppress=False)
            self._registered = True
            logger.info(f"Hotkeys registered: [{self._hk_new_session}] [{self._hk_toggle_hud}]")
        except Exception as e:
            logger.error(f"Failed to register hotkeys: {e}")

    def stop(self):
        if KEYBOARD_AVAILABLE and self._registered:
            keyboard.unhook_all_hotkeys()
            self._registered = False
            logger.info("Hotkeys unregistered")
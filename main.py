"""
main.py — WorkSpace Manager entry point.
Wires together: daemon, spotlight, HUD, main window, system tray.
Run with:  python main.py
"""

import sys
import os
import threading
from pathlib import Path

# ── Must be first ──────────────────────────────────────────────────────────
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QPixmap, QIcon, QLinearGradient, QFont
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject

import db
from daemon import WorkSpaceDaemon
from ui.spotlight import SpotlightWindow
from ui.hud import HUDWindow
from ui.main_window import MainWindow
from ui.styles import APP_STYLE, ACCENT, ACCENT2, BG, TEXT
from snapshot import get_current_desktop_id


# ── Hotkey setup ─────────────────────────────────────────────────────────────

class HotkeyBridge(QObject):
    """Runs the keyboard listener in a thread, emits Qt signals."""
    hud_toggle_requested = pyqtSignal()
    snapshot_requested = pyqtSignal()

    def start_listening(self):
        t = threading.Thread(target=self._listen, daemon=True)
        t.start()

    def _listen(self):
        try:
            import keyboard
            # Win+` to toggle HUD
            keyboard.add_hotkey("windows+`", self.hud_toggle_requested.emit)
            # Win+Shift+S to force snapshot
            keyboard.add_hotkey("windows+shift+s", self.snapshot_requested.emit)
            keyboard.wait()
        except Exception as e:
            print(f"[Hotkey] Warning: {e}")
            print("[Hotkey] Global hotkeys unavailable. Try running as administrator.")


# ── Tray icon ─────────────────────────────────────────────────────────────────

def make_tray_icon() -> QIcon:
    """Generate a simple gradient icon for the system tray."""
    px = QPixmap(64, 64)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    path = QPainterPath()
    path.addRoundedRect(4, 4, 56, 56, 14, 14)

    grad = QLinearGradient(0, 0, 64, 64)
    grad.setColorAt(0, QColor(ACCENT))
    grad.setColorAt(1, QColor(ACCENT2))
    p.fillPath(path, grad)

    p.setPen(QColor("white"))
    f = QFont("Segoe UI", 28)
    f.setBold(True)
    p.setFont(f)
    from PyQt6.QtCore import QRect
    p.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, "⊞")
    p.end()

    return QIcon(px)


# ── Main App Controller ───────────────────────────────────────────────────────

class WorkSpaceApp:
    """
    Central controller: wires daemon, UI windows, tray, and hotkeys.
    """

    def __init__(self, app: QApplication):
        self.app = app
        db.init_db()

        # Core components
        self.daemon = WorkSpaceDaemon()
        self.spotlight = SpotlightWindow()
        self.hud = HUDWindow()
        self.main_window = MainWindow()
        self.hotkeys = HotkeyBridge()

        # Tray
        self.tray = QSystemTrayIcon(make_tray_icon(), app)
        self._build_tray_menu()
        self.tray.show()

        # Connect signals
        self._wire()

        # Start daemon
        self.daemon.start()

        # Start hotkeys in background thread
        self.hotkeys.start_listening()

        # Show main window on first launch
        self.main_window.show()

        # Tray balloon
        self.tray.showMessage(
            "WorkSpace Manager",
            "Running in the background. Press Win+` for the HUD.",
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )

    def _build_tray_menu(self):
        menu = QMenu()
        menu.setStyleSheet(f"""
            QMenu {{
                background: #111118;
                border: 1px solid #2a2a3a;
                border-radius: 10px;
                padding: 6px;
                color: #e8e8f0;
                font-family: "Segoe UI Variable";
                font-size: 13px;
            }}
            QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
            QMenu::item:selected {{ background: rgba(124,106,247,0.15); color: #a78bfa; }}
            QMenu::separator {{ height: 1px; background: #2a2a3a; margin: 4px 8px; }}
        """)

        open_act = menu.addAction("⊞  Open Dashboard")
        open_act.triggered.connect(self._show_dashboard)

        hud_act = menu.addAction("  Toggle HUD  (Win+`)")
        hud_act.triggered.connect(self.hud.toggle)

        snap_act = menu.addAction("📸  Snapshot Now")
        snap_act.triggered.connect(self.daemon.force_snapshot)

        menu.addSeparator()

        quit_act = menu.addAction("✕  Quit WorkSpace")
        quit_act.triggered.connect(self._quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)

    def _wire(self):
        # Daemon → Spotlight
        self.daemon.new_desktop_detected.connect(self._on_new_desktop)

        # Spotlight → Daemon
        self.spotlight.session_confirmed.connect(self._on_session_named)
        self.spotlight.session_cancelled.connect(self._on_session_cancelled)

        # HUD actions
        self.hud.restore_requested.connect(self._on_restore)
        self.hud.delete_requested.connect(lambda _: self.main_window.refresh())
        self.hud.open_dashboard.connect(self._show_dashboard)

        # Hotkeys
        self.hotkeys.hud_toggle_requested.connect(self.hud.toggle)
        self.hotkeys.snapshot_requested.connect(self.daemon.force_snapshot)

        # Daemon → Main window refresh
        self.daemon.snapshot_saved.connect(lambda _: None)  # refresh on demand

    # ── Event Handlers ────────────────────────────────────────────────────────

    def _on_new_desktop(self, desktop_id: str):
        """New virtual desktop created — show spotlight to name the session."""
        # Store desktop_id for when user confirms
        self._pending_desktop_id = desktop_id
        QTimer.singleShot(300, self.spotlight.show_prompt)

    def _on_session_named(self, name: str):
        """User confirmed a session name."""
        desktop_id = getattr(self, "_pending_desktop_id", None)
        # _pending_desktop_id is set by the daemon when it detects the new desktop.
        # We do NOT fall back to get_current_desktop_id() here — if the user
        # switched away while typing, we still want the session tied to the
        # NEW desktop that triggered the spotlight, not whichever is active now.
        if not desktop_id:
            # Fallback only if daemon somehow didn't set it (shouldn't happen)
            desktop_id = get_current_desktop_id()
            print(f"[Main] Warning: _pending_desktop_id was unset, using current: {desktop_id}")

        icon = _pick_icon(name)
        session_id = db.create_session(name, icon, desktop_id)

        if desktop_id:
            self.daemon.register_session(session_id, desktop_id)

        self.tray.showMessage(
            "Session Started",
            f"{icon} \"{name}\" · first snapshot in 10s",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )
        self.main_window.refresh()
        self._pending_desktop_id = None

    def _on_session_cancelled(self):
        """User pressed Esc — don't save this desktop as a session."""
        self._pending_desktop_id = None
        self.tray.showMessage(
            "WorkSpace",
            "Session tracking skipped.",
            QSystemTrayIcon.MessageIcon.NoIcon,
            1500
        )

    def _on_restore(self, session_id: int):
        """User clicked restore in HUD — launch everything."""
        import restore as restorer
        result = restorer.restore_session(session_id)
        session = db.get_session(session_id)
        name = session["name"] if session else "session"
        self.tray.showMessage(
            "Session Restored",
            f"Reopened {result['total']} item(s) for \"{name}\"",
            QSystemTrayIcon.MessageIcon.Information,
            2500
        )
        self.main_window.refresh()

    def _show_dashboard(self):
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()
        self.main_window.refresh()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_dashboard()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.hud.toggle()

    def _quit(self):
        self.daemon.stop()
        self.tray.hide()
        self.app.quit()


# ── Icon picker ───────────────────────────────────────────────────────────────

def _pick_icon(name: str) -> str:
    name_lower = name.lower()
    rules = [
        (["lab", "assignment", "hw", "homework"], "🔧"),
        (["web", "frontend", "react", "vue", "html", "css"], "🌐"),
        (["ml", "ai", "machine", "deep", "neural", "model"], "🤖"),
        (["db", "database", "sql", "mongo"], "🗄"),
        (["network", "socket", "tcp", "udp"], "🔌"),
        (["os", "operating", "kernel", "system"], "💻"),
        (["research", "paper", "thesis", "survey"], "📄"),
        (["dsa", "algorithm", "data structure", "tree", "graph"], "🌳"),
        (["security", "crypto", "cipher", "attack"], "🔐"),
        (["design", "ui", "ux", "figma", "sketch"], "🎨"),
        (["math", "calculus", "algebra", "proof"], "📐"),
        (["finance", "invest", "stock", "trade"], "📈"),
        (["video", "edit", "media", "content"], "🎬"),
        (["game", "unity", "unreal", "godot"], "🎮"),
    ]
    for keywords, icon in rules:
        if any(k in name_lower for k in keywords):
            return icon
    return "🗂"


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Proper Ctrl+C / SIGINT handling — exit cleanly instead of dropping to REPL
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("WorkSpace Manager")
    app.setOrganizationName("WorkSpace")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(APP_STYLE)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "WorkSpace", "System tray not available on this system.")
        sys.exit(1)

    controller = WorkSpaceApp(app)  # noqa — keep reference alive

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

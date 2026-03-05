"""
main.py — WorkSpace Manager entry point.
Run with:  python main.py
"""

import sys
import os
import threading
from pathlib import Path

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QPixmap, QIcon, QLinearGradient, QFont
)
from PyQt6.QtCore import Qt, QRect

import db
from ui.main_window import MainWindow
from ui.styles import APP_STYLE, ACCENT, ACCENT2, BG, TEXT


# ── Tray icon ─────────────────────────────────────────────────────────────────

def make_tray_icon() -> QIcon:
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
    p.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, "⊞")
    p.end()
    return QIcon(px)


# ── Global hotkey (Ctrl+Alt+W to show/raise window) ──────────────────────────

def start_hotkey_listener(window: MainWindow):
    def _listen():
        try:
            import keyboard
            keyboard.add_hotkey("ctrl+alt+w", lambda: window.show() or window.raise_())
            keyboard.wait()
        except Exception as e:
            print(f"[Hotkey] Unavailable: {e}")

    t = threading.Thread(target=_listen, daemon=True)
    t.start()


# ── Daemon + Spotlight wiring ─────────────────────────────────────────────────

def start_daemon(window: MainWindow):
    """
    Initialise and start the virtual-desktop daemon.
    Wire its new_desktop_detected signal → Spotlight prompt.
    Only runs on Windows where pyvda is available.
    """
    try:
        from daemon import WorkSpaceDaemon
        from ui.spotlight import SpotlightPrompt

        daemon = WorkSpaceDaemon()

        _active_spotlights: dict[str, SpotlightPrompt] = {}

        def _show_spotlight(desktop_id: str):
            if desktop_id in _active_spotlights:
                return   # already showing for this desktop
            prompt = SpotlightPrompt(desktop_id)

            def _on_confirmed(session_id: int, did: str):
                daemon.register_session(session_id, did)
                _active_spotlights.pop(did, None)
                window._load_sessions()

            def _on_dismissed():
                _active_spotlights.pop(desktop_id, None)

            prompt.confirmed.connect(_on_confirmed)
            prompt.dismissed.connect(_on_dismissed)
            _active_spotlights[desktop_id] = prompt
            prompt.show()
            prompt.raise_()
            prompt.activateWindow()

        daemon.new_desktop_detected.connect(_show_spotlight)
        daemon.snapshot_saved.connect(lambda sid: window._load_sessions())
        daemon.start()

        return daemon

    except Exception as e:
        print(f"[Daemon] Could not start: {e}")
        return None


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WorkSpace Manager")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(APP_STYLE)

    db.init_db()

    window = MainWindow()
    window.show()

    # System tray
    tray_icon = make_tray_icon()
    tray = QSystemTrayIcon(tray_icon, app)

    tray_menu = QMenu()
    tray_menu.setStyleSheet(f"""
        QMenu {{
            background: #111118; border: 1px solid #2a2a3a;
            border-radius: 10px; padding: 6px;
        }}
        QMenu::item {{ padding: 7px 18px; border-radius: 6px; color: #e8e8f0; }}
        QMenu::item:selected {{ background: rgba(124,106,247,0.10); color: #a78bfa; }}
    """)
    show_action = tray_menu.addAction("⊞  Open WorkSpace")
    show_action.triggered.connect(lambda: (window.show(), window.raise_()))
    tray_menu.addSeparator()
    quit_action = tray_menu.addAction("Quit")
    quit_action.triggered.connect(app.quit)

    tray.setContextMenu(tray_menu)
    tray.activated.connect(
        lambda reason: (window.show(), window.raise_())
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray.show()

    start_hotkey_listener(window)
    _daemon = start_daemon(window)   # keep reference alive

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
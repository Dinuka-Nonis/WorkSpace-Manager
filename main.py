"""
main.py — WorkSpace Manager entry point.
Run with:  python main.py

Memory-leak fixes in this version:
  • RestoreWorker gets parent=app + finished.connect(deleteLater) — Qt owns the
    C++ object and frees it after the thread finishes. No more _active_workers list.
  • Tray menus: each rebuild calls old_menu.deleteLater() before replacing,
    so QMenu objects don't accumulate on every right-click.
  • Single tray.activated connection (was duplicated in previous version).
  • SnapshotWorker defined at module level (in main_window.py) — not re-created
    per button click.
"""

import sys
import os
import threading
from pathlib import Path

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QDialog
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QPixmap, QIcon,
    QLinearGradient, QFont
)
from PyQt6.QtCore import Qt, QRect, QThread, pyqtSignal

import db
from ui.main_window import MainWindow
from ui.styles import APP_STYLE, ACCENT, ACCENT2

TRAY_STYLE = """
    QMenu {
        background: #FFFFFF; border: 1.5px solid rgba(0,0,0,0.10);
        border-radius: 12px; padding: 6px;
    }
    QMenu::item { padding: 8px 18px; border-radius: 7px; color: #111; font-size: 14px; }
    QMenu::item:selected { background: #F0F0ED; color: #111; }
    QMenu::separator { height: 1px; background: rgba(0,0,0,0.07); margin: 4px 8px; }
"""


# ── Tray icon ──────────────────────────────────────────────────────────────────

def make_tray_icon() -> QIcon:
    px = QPixmap(64, 64)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(4, 4, 56, 56, 14, 14)
    grad = QLinearGradient(0, 0, 64, 64)
    grad.setColorAt(0, QColor("#111111"))
    grad.setColorAt(1, QColor("#333333"))
    p.fillPath(path, grad)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", 28)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, "⊞")
    p.end()
    return QIcon(px)


# ── Restore worker ─────────────────────────────────────────────────────────────

class RestoreWorker(QThread):
    done = pyqtSignal(dict)

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        # Qt will free the C++ object once the thread finishes — no leak.
        self.finished.connect(self.deleteLater)

    def run(self):
        import restore
        self.done.emit(restore.restore_session(self.session_id))


# ── Global hotkey ──────────────────────────────────────────────────────────────

HOTKEY = "ctrl+alt+w"

def start_hotkey_listener(window: MainWindow, tray: QSystemTrayIcon):
    def _listen():
        try:
            import keyboard
            keyboard.add_hotkey(HOTKEY, lambda: _show_window(window))
            keyboard.wait()
        except ImportError:
            tray.setToolTip(
                "WorkSpace Manager (hotkey unavailable — install 'keyboard' package)"
            )
        except Exception as e:
            tray.setToolTip(f"WorkSpace Manager (hotkey unavailable: {e})")

    threading.Thread(target=_listen, daemon=True).start()


def _show_window(window: MainWindow):
    window.show()
    window.raise_()
    window.activateWindow()


# ── Windows shutdown hook ──────────────────────────────────────────────────────

def register_shutdown_hook():
    if sys.platform != "win32":
        return
    try:
        import win32api, win32con

        def _on_shutdown(ctrl_type):
            if ctrl_type in (
                win32con.CTRL_SHUTDOWN_EVENT,
                win32con.CTRL_LOGOFF_EVENT,
                win32con.CTRL_CLOSE_EVENT,
            ):
                try:
                    sessions = db.get_all_sessions()
                    if sessions:
                        sid = sessions[0]["id"]
                        from core.snapshot import capture_running_apps
                        running = capture_running_apps()
                        if running:
                            db.add_items_bulk(sid, running)
                except Exception as e:
                    print(f"[Shutdown] Auto-snapshot failed: {e}")
                return True
            return False

        win32api.SetConsoleCtrlHandler(_on_shutdown, True)
    except ImportError:
        pass
    except Exception as e:
        print(f"[Shutdown] Registration failed: {e}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WorkSpace Manager")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(APP_STYLE)

    db.init_db()
    register_shutdown_hook()

    # Pre-warm the Chrome native host so it's ready when Save Snapshot is clicked
    try:
        from core.snapshot import _prewarm_native_host
        threading.Thread(target=_prewarm_native_host, daemon=True).start()
    except Exception:
        pass

    window = MainWindow()
    window.show()

    # ── System tray ────────────────────────────────────────────────────────────
    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip("WorkSpace Manager")

    def _quick_restore(sid: int):
        # parent=app keeps the worker alive; deleteLater (via finished signal)
        # frees it once the thread exits — no manual list needed.
        w = RestoreWorker(sid, parent=app)
        def _on_done(result):
            s    = db.get_session(sid)
            name = s["name"] if s else "Session"
            tray.showMessage(
                "WorkSpace",
                f'Restored "{name}" — {result["opened"]} items opened',
                QSystemTrayIcon.MessageIcon.Information, 3000,
            )
            window._load_sessions()
        w.done.connect(_on_done)
        w.start()

    def _do_snapshot_tray():
        """Non-interactive snapshot from tray — saves all detected items."""
        sessions = db.get_all_sessions()
        if not sessions:
            tray.showMessage(
                "WorkSpace", "No sessions — create one first.",
                QSystemTrayIcon.MessageIcon.Warning, 2500,
            )
            return
        window._save_snapshot(sessions[0]["id"])

    # ── Tray menu builder ──────────────────────────────────────────────────────
    # We keep a single-element list so we can call deleteLater on the OLD menu
    # before replacing it — prevents QMenu objects from accumulating in memory.

    def _build_tray_menu() -> QMenu:
        menu = QMenu()
        menu.setStyleSheet(TRAY_STYLE)

        sessions = db.get_all_sessions()[:5]
        if sessions:
            hdr = menu.addAction("Recent Sessions")
            hdr.setEnabled(False)
            for s in sessions:
                action = menu.addAction(f"  {s['name']}")
                sid = s["id"]
                action.triggered.connect(
                    lambda checked, _sid=sid: _quick_restore(_sid)
                )
            menu.addSeparator()

        menu.addAction("⊞  Open WorkSpace").triggered.connect(
            lambda: _show_window(window)
        )
        menu.addAction("⊕  Save Snapshot").triggered.connect(_do_snapshot_tray)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(app.quit)
        return menu

    _menu_holder: list[QMenu] = [_build_tray_menu()]
    tray.setContextMenu(_menu_holder[0])

    def _on_tray_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            # Delete old menu after Qt is done with it, then set fresh one
            old = _menu_holder[0]
            new = _build_tray_menu()
            _menu_holder[0] = new
            tray.setContextMenu(new)
            old.deleteLater()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            _show_window(window)

    tray.activated.connect(_on_tray_activated)
    tray.show()

    start_hotkey_listener(window, tray)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

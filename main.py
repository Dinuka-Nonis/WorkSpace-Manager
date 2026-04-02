"""
main.py — WorkSpace Manager entry point.
Floating-only architecture: drop zone overlay + wallet panel + system tray.

No main window — everything is driven by:
  • Right-edge drop zone  (appears on any window drag)
  • Wallet panel          (Ctrl+Alt+W hotkey)
  • System tray           (right-click for sessions / quit)

Run:  python main.py
Deps: PyQt6  psutil  pywin32  keyboard
"""

import sys
import os
import time
import shutil
import threading
import signal
from pathlib import Path

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QPixmap, QIcon,
    QLinearGradient, QFont
)
from PyQt6.QtCore import Qt, QRect, QThread, pyqtSignal, QTimer

import db
from ui.drop_zone    import DropZoneOverlay
from ui.wallet_panel import WalletPanel

HOTKEY_TOGGLE_WALLET  = "ctrl+alt+w"
HOTKEY_SHOW_SESSIONS  = "ctrl+shift+space"

TRAY_STYLE = """
    QMenu {
        background: #FFFFFF; border: 1.5px solid rgba(0,0,0,0.10);
        border-radius: 12px; padding: 6px;
    }
    QMenu::item { padding: 8px 18px; border-radius: 7px; color: #111; font-size: 14px; }
    QMenu::item:selected { background: #F0F0ED; color: #111; }
    QMenu::separator { height: 1px; background: rgba(0,0,0,0.07); margin: 4px 8px; }
"""


# ── First-run setup ───────────────────────────────────────────────────────────

def _get_appdata_dir() -> Path:
    """Return %APPDATA%\\WorkSpaceManager, creating it if needed."""
    appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    d = Path(appdata) / "WorkSpaceManager"
    d.mkdir(parents=True, exist_ok=True)
    return d


def first_run_setup():
    """
    Runs silently on every launch but only does real work once.
    All operations are idempotent — safe to call repeatedly.

    Steps:
      1. Extract workspace_host.exe from the PyInstaller bundle (frozen only).
      2. Write the native host manifest and register it in the registry.
      3. Add WorkSpaceManager.exe to Windows startup (first run only).
      4. Touch a marker file so step 3 is skipped on future launches.
    """
    app_dir = _get_appdata_dir()
    marker  = app_dir / ".setup_done"

    # ── 1. Extract workspace_host.exe from the bundle ─────────────────────────
    # sys._MEIPASS is set by PyInstaller when the app is frozen into an EXE.
    # When running from source (python main.py) this block is skipped entirely.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled_host = Path(meipass) / "workspace_host.exe"
        target_host  = app_dir / "workspace_host.exe"
        if bundled_host.exists() and not target_host.exists():
            shutil.copy2(str(bundled_host), str(target_host))
            print(f"[Setup] Extracted workspace_host.exe → {target_host}")

    # ── 2. Register the native messaging host ─────────────────────────────────
    try:
        from native_host.install_host import write_manifest, register_in_registry
        manifest_path = write_manifest()
        register_in_registry(manifest_path)
        print(f"[Setup] Native host registered: {manifest_path}")
    except Exception as e:
        print(f"[Setup] Native host registration failed (non-fatal): {e}")

    # ── 3. Add to Windows startup (only on the very first run) ────────────────
    if not marker.exists():
        try:
            import winreg
            # sys.executable is the .exe path when frozen, or python.exe in source mode.
            exe_path    = sys.executable
            key_path    = r"Software\Microsoft\Windows\CurrentVersion\Run"
            startup_cmd = f'"{exe_path}"'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "WorkSpaceManager", 0,
                                  winreg.REG_SZ, startup_cmd)
            print(f"[Setup] Added to Windows startup: {startup_cmd}")
        except Exception as e:
            print(f"[Setup] Startup registration failed (non-fatal): {e}")

        # Mark setup as done regardless — avoids retrying on every launch
        try:
            marker.touch()
        except Exception:
            pass


# ── Tray icon ─────────────────────────────────────────────────────────────────

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


# ── Restore worker ────────────────────────────────────────────────────────────

class RestoreWorker(QThread):
    done = pyqtSignal(dict)

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.finished.connect(self.deleteLater)

    def run(self):
        import restore
        self.done.emit(restore.restore_session(self.session_id))


def _invoke_on_main(fn):
    QTimer.singleShot(0, fn)


# ── Hotkey listener ───────────────────────────────────────────────────────────

def start_hotkey_listener(wallet_panel: WalletPanel, tray: QSystemTrayIcon):
    def _listen():
        try:
            import keyboard
        except ImportError:
            tray.setToolTip("WorkSpace Manager (hotkeys unavailable — pip install keyboard)")
            return
        try:
            keyboard.add_hotkey(HOTKEY_TOGGLE_WALLET,
                                lambda: _invoke_on_main(wallet_panel.toggle))
        except Exception as e:
            print(f"[Hotkey] Could not register {HOTKEY_TOGGLE_WALLET}: {e}")
        try:
            keyboard.add_hotkey(HOTKEY_SHOW_SESSIONS,
                                lambda: _invoke_on_main(wallet_panel.toggle))
        except Exception as e:
            print(f"[Hotkey] Could not register {HOTKEY_SHOW_SESSIONS}: {e}")
        try:
            while True:
                time.sleep(1)
        except Exception as e:
            print(f"[Hotkey] Listener error: {e}")

    threading.Thread(target=_listen, daemon=True).start()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WorkSpace Manager")
    app.setQuitOnLastWindowClosed(False)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    _sig = QTimer()
    _sig.timeout.connect(lambda: None)
    _sig.start(200)

    # Run silent first-time setup before anything else
    first_run_setup()

    db.init_db()

    drop_zone    = DropZoneOverlay()
    wallet_panel = WalletPanel()

    drop_zone.show()

    # ── Drag watcher (Windows only) ───────────────────────────────────────────
    watcher = None
    if sys.platform == "win32":
        from core.drag_watcher import DragWatcher
        watcher = DragWatcher(parent=app)

        def _on_drag_started(app_info: dict):
            drop_zone.on_drag_started(app_info)
            # IMPORTANT: use the final resting rect (fully visible position),
            # NOT the current animated/partial rect — that was the save bug.
            watcher.set_drop_zone_rect(*drop_zone.drop_zone_final_rect())

        def _on_dropped(app_info: dict):
            drop_zone.on_dropped(app_info)
            if wallet_panel.isVisible():
                wallet_panel._refresh()

        watcher.drag_started.connect(_on_drag_started)
        watcher.dropped_in_zone.connect(_on_dropped)
        watcher.drag_cancelled.connect(drop_zone.on_drag_cancelled)
        watcher.start()

    # ── Tray ──────────────────────────────────────────────────────────────────
    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip("WorkSpace Manager\nCtrl+Shift+Space / Ctrl+Alt+W → sessions\nDrag window to right edge to save")

    def _quick_restore(sid: int):
        w = RestoreWorker(sid, parent=app)
        def _on_done(result):
            s    = db.get_session(sid)
            name = s["name"] if s else "Session"
            tray.showMessage("WorkSpace",
                             f'Restored "{name}" — {result["opened"]} items opened',
                             QSystemTrayIcon.MessageIcon.Information, 3000)
        w.done.connect(_on_done)
        w.start()

    def _build_tray_menu() -> QMenu:
        menu = QMenu()
        menu.setStyleSheet(TRAY_STYLE)
        sessions = db.get_all_sessions()[:5]
        if sessions:
            hdr = menu.addAction("Recent Sessions")
            hdr.setEnabled(False)
            for s in sessions:
                action = menu.addAction(f"  {s['icon']}  {s['name']}")
                sid = s["id"]
                action.triggered.connect(lambda checked, _sid=sid: _quick_restore(_sid))
            menu.addSeparator()
        menu.addAction("⧉  Sessions  (Ctrl+Alt+W)").triggered.connect(wallet_panel.toggle)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(app.quit)
        return menu

    _menu_holder: list[QMenu] = [_build_tray_menu()]
    tray.setContextMenu(_menu_holder[0])

    def _on_tray_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            old = _menu_holder[0]
            new = _build_tray_menu()
            _menu_holder[0] = new
            tray.setContextMenu(new)
            old.deleteLater()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            wallet_panel.toggle()

    tray.activated.connect(_on_tray_activated)
    tray.show()

    start_hotkey_listener(wallet_panel, tray)

    app.aboutToQuit.connect(lambda: watcher.stop() if watcher else None)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
"""Window capture using pyvda + win32gui."""

import logging
from typing import Optional

try:
    import win32gui
    import win32process
    import psutil
    import pyvda
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False

from src.db.models import CapturedWindow, AppType

logger = logging.getLogger("workspace.capture")

PROCESS_TYPE_MAP = {
    "code.exe": AppType.VSCODE,
    "chrome.exe": AppType.CHROME,
    "firefox.exe": AppType.FIREFOX,
    "acrord32.exe": AppType.PDF_VIEWER,
    "sumatrapdf.exe": AppType.PDF_VIEWER,
    "windowsterminal.exe": AppType.TERMINAL,
}

IGNORED_PROCESSES = {
    "explorer.exe", "textinputhost.exe", "shellexperiencehost.exe",
    "searchui.exe", "applicationframehost.exe", "systemsettings.exe",
}


class WindowCapture:
    def __init__(self, session_id: int, desktop_id: str):
        self.session_id = session_id
        self.desktop_id = desktop_id

    def capture(self, snapshot_id: int) -> list[CapturedWindow]:
        if not WINDOWS_AVAILABLE:
            logger.warning("Windows APIs not available")
            return []

        windows = []
        seen_hwnds = set()

        try:
            apps = pyvda.get_apps_by_z_order(current_desktop=False)
        except Exception as e:
            logger.error(f"pyvda failed: {e}")
            return []

        for app in apps:
            if str(app.desktop_id) != self.desktop_id:
                continue

            hwnd = app.hwnd
            if hwnd in seen_hwnds or not win32gui.IsWindowVisible(hwnd):
                continue

            seen_hwnds.add(hwnd)
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                continue

            window = self._build_window(hwnd, title, snapshot_id)
            if window:
                windows.append(window)

        logger.debug(f"Captured {len(windows)} windows")
        return windows

    def _build_window(self, hwnd: int, title: str, snapshot_id: int) -> Optional[CapturedWindow]:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            pname = proc.name().lower()

            if pname in IGNORED_PROCESSES:
                return None

            exe_path = proc.exe()
            cmd_args = proc.cmdline()
            app_type = PROCESS_TYPE_MAP.get(pname, AppType.GENERIC)

            try:
                cwd = proc.cwd()
            except:
                cwd = None

            return CapturedWindow(
                id=None,
                session_id=self.session_id,
                snapshot_id=snapshot_id,
                hwnd=hwnd,
                process_name=pname,
                window_title=title,
                app_type=app_type,
                exe_path=exe_path,
                working_dir=cwd,
                cmd_args=cmd_args,
            )

        except Exception as e:
            logger.debug(f"Skip hwnd {hwnd}: {e}")
            return None
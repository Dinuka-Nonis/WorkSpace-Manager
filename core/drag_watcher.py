"""
core/drag_watcher.py — Window drag detection via SetWinEventHook.

Key fixes vs previous version:
  VS Code: now reads cmdline of the specific dragged PID to get its exact
           open folder — no longer reads the global storage.json which always
           returned the last-active window regardless of which one you dragged.

  Chrome : no longer skipped. When a Chrome/Edge window is dragged, we read
           the active tab URL from the address bar via Windows UIAutomation.
           Requires:  pip install uiautomation
           Falls back gracefully (logs a hint) if the package isn't installed.
"""

import sys
import ctypes
import ctypes.wintypes
import os
import json
from pathlib import Path
from urllib.parse import urlparse, unquote

from PyQt6.QtCore import QThread, pyqtSignal

EVENT_SYSTEM_MOVESIZESTART = 0x000A
EVENT_SYSTEM_MOVESIZEEND   = 0x000B
WINEVENT_OUTOFCONTEXT      = 0x0000


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd",    ctypes.wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam",  ctypes.wintypes.WPARAM),
        ("lParam",  ctypes.wintypes.LPARAM),
        ("time",    ctypes.c_uint),
        ("pt",      ctypes.wintypes.POINT),
    ]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _uri_to_local_path(uri: str) -> str | None:
    try:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            return None
        raw = unquote(parsed.path)
        if raw.startswith("/") and len(raw) > 3 and raw[2] == ":":
            raw = raw[1:]
        raw = os.path.normpath(raw)
        return raw if os.path.exists(raw) else None
    except Exception:
        return None


def _vscode_folder_from_cmdline(pid: int, exe: str) -> dict | None:
    """
    Get the exact folder/workspace open in THIS specific VS Code instance
    by reading its process command-line arguments.

    VS Code is launched as:
      Code.exe [flags...] <folder_or_workspace_path>

    This is always correct for the specific window being dragged, unlike
    storage.json which only records the globally last-active window.
    """
    try:
        import psutil
        proc    = psutil.Process(pid)
        cmdline = proc.cmdline()   # e.g. ['Code.exe', 'C:\\projects\\myapp']
    except Exception:
        return None

    # Skip argv[0] (the exe itself); collect non-flag, path-like args
    candidate_paths: list[str] = []
    for arg in cmdline[1:]:
        if arg.startswith("-"):
            continue
        # Normalise and check existence
        p = os.path.normpath(arg)
        if os.path.exists(p):
            candidate_paths.append(p)

    if not candidate_paths:
        return None

    path     = candidate_paths[0]
    exe_stem = Path(exe).stem.lower()

    if "cursor" in exe_stem:
        app_name = "Cursor"
    elif "insiders" in exe_stem:
        app_name = "VS Code Insiders"
    else:
        app_name = "VS Code"

    name = os.path.basename(path.rstrip("/\\"))
    if path.endswith(".code-workspace"):
        label = f"{app_name} — {name.replace('.code-workspace', '')} (workspace)"
    else:
        label = f"{app_name} — {name}"

    return {
        "type":        "app",
        "path_or_url": f"vscode-folder:{exe}||{path}",
        "label":       label,
    }


def _vscode_folder_from_storage(exe: str) -> dict | None:
    """
    Fallback: read VS Code storage.json to find any open folder.
    Less accurate (global, not per-instance) but works when cmdline is empty.
    """
    appdata   = os.getenv("APPDATA", "")
    code_stem = Path(exe).stem.lower()

    variants = [
        ("code - insiders", "Code - Insiders", "VS Code Insiders"),
        ("cursor",          "Cursor",           "Cursor"),
        ("code",            "Code",             "VS Code"),
    ]

    for stem_match, appdata_dir, display_name in variants:
        if stem_match not in code_stem:
            continue
        candidates = [
            os.path.join(appdata, appdata_dir, "storage.json"),
            os.path.join(appdata, appdata_dir, "User", "storage.json"),
            os.path.join(appdata, appdata_dir, "User", "globalStorage", "storage.json"),
        ]
        storage_json = next((p for p in candidates if os.path.exists(p)), None)
        if not storage_json:
            continue
        try:
            with open(storage_json, encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
            ws   = data.get("windowsState", {})
            last = ws.get("lastActiveWindow", {})
            folder_uri = last.get("folder") or last.get("folderUri")
            if folder_uri:
                path = _uri_to_local_path(folder_uri)
                if path:
                    name = os.path.basename(path.rstrip("/\\"))
                    return {
                        "type":        "app",
                        "path_or_url": f"vscode-folder:{exe}||{path}",
                        "label":       f"{display_name} — {name}",
                    }
        except Exception as e:
            print(f"[DragWatcher] storage.json fallback error: {e}")
        break

    return None


def _get_chrome_active_url(hwnd: int) -> str | None:
    """
    Read the active tab URL from a Chrome/Edge/Brave window via
    Windows UIAutomation (reads the address bar text directly).

    Requires:  pip install uiautomation
    Returns None silently if the package is unavailable or the read fails.
    """
    try:
        import uiautomation as auto  # type: ignore
        ctrl = auto.ControlFromHandle(hwnd)
        if ctrl is None:
            return None

        # Chrome/Edge address bar is an Edit named "Address and search bar"
        # (localised builds may differ, so try both known names)
        for name in ("Address and search bar", "Address bar"):
            try:
                edit = ctrl.EditControl(Name=name)
                if edit.Exists(0, 0):
                    val = edit.GetValuePattern().Value
                    if val and ("." in val or val.startswith("http")):
                        # Ensure it has a scheme
                        if not val.startswith(("http://", "https://", "file://")):
                            val = "https://" + val
                        return val
            except Exception:
                continue
    except ImportError:
        # Only log once
        if not getattr(_get_chrome_active_url, "_warned", False):
            _get_chrome_active_url._warned = True  # type: ignore
            print("[DragWatcher] Chrome URL detection disabled — "
                  "run: pip install uiautomation")
    except Exception as e:
        print(f"[DragWatcher] Chrome URL read error: {e}")
    return None


def _get_file_explorer_windows(hwnd: int) -> list[dict]:
    """Enumerate open File Explorer windows via Shell COM."""
    if sys.platform != "win32":
        return []

    results: list[dict] = []
    seen: set[str] = set()

    def _add(loc_url: str):
        folder_path = _uri_to_local_path(loc_url)
        if not folder_path:
            return
        norm = os.path.normcase(folder_path)
        if norm in seen:
            return
        seen.add(norm)
        name = os.path.basename(folder_path.rstrip("/\\")) or folder_path
        results.append({
            "type":        "app",
            "path_or_url": f"explorer-folder:{folder_path}",
            "label":       f"File Explorer — {name}",
        })

    try:
        import comtypes.client  # type: ignore
        shell   = comtypes.client.CreateObject("Shell.Application")
        windows = shell.Windows()
        for i in range(windows.Count):
            try:
                win = windows.Item(i)
                if win is None:
                    continue
                loc = getattr(win, "LocationURL", None) or ""
                if loc.startswith("file://"):
                    _add(loc)
            except Exception:
                continue
    except Exception:
        try:
            import win32com.client  # type: ignore
            shell = win32com.client.Dispatch("Shell.Application")
            for win in shell.Windows():
                try:
                    loc = getattr(win, "LocationURL", None) or ""
                    if loc.startswith("file://"):
                        _add(loc)
                except Exception:
                    continue
        except Exception:
            pass

    return results


# ── DragWatcher ────────────────────────────────────────────────────────────────

class DragWatcher(QThread):
    """
    Watches for system-wide window drag events via SetWinEventHook.

    Signals
    -------
    drag_started(dict)     — user began dragging a window
    dropped_in_zone(dict)  — released inside the drop zone rect
    drag_cancelled()       — released outside the drop zone
    """

    drag_started    = pyqtSignal(dict)
    dropped_in_zone = pyqtSignal(dict)
    drag_cancelled  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drop_zone_rect: tuple[int, int, int, int] | None = None
        self._current_drag: dict | None = None
        self._hook      = None
        self._hook_proc = None
        self._running   = False
        self._thread_id = 0
        self.finished.connect(self.deleteLater)

    def set_drop_zone_rect(self, x: int, y: int, w: int, h: int):
        """Set where the fully-visible drop zone sits on screen."""
        self._drop_zone_rect = (x, y, w, h)

    def stop(self):
        self._running = False
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)

    def run(self):
        if sys.platform != "win32":
            return

        self._running   = True
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        user32          = ctypes.windll.user32

        WinEventProc = ctypes.WINFUNCTYPE(
            None,
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.HWND,
            ctypes.wintypes.LONG,
            ctypes.wintypes.LONG,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
        )

        def _callback(hHook, event, hwnd, idObject, idChild, dwThread, dwTime):
            try:
                if event == EVENT_SYSTEM_MOVESIZESTART:
                    self._on_move_start(hwnd)
                elif event == EVENT_SYSTEM_MOVESIZEEND:
                    self._on_move_end(hwnd)
            except Exception as e:
                print(f"[DragWatcher] callback error: {e}")

        self._hook_proc = WinEventProc(_callback)
        self._hook = user32.SetWinEventHook(
            EVENT_SYSTEM_MOVESIZESTART, EVENT_SYSTEM_MOVESIZEEND,
            0, self._hook_proc, 0, 0, WINEVENT_OUTOFCONTEXT,
        )

        if not self._hook:
            print("[DragWatcher] SetWinEventHook failed")
            return

        print("[DragWatcher] Hook installed — watching for window drags")

        msg = MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._hook:
            user32.UnhookWinEvent(self._hook)
            self._hook = None
        print("[DragWatcher] Hook removed")

    # ── Internal handlers ──────────────────────────────────────────────────────

    def _on_move_start(self, hwnd: int):
        info = self._capture_window_info(hwnd)
        if info is None:
            self._current_drag = None
            return
        self._current_drag = info
        self.drag_started.emit(info)

    def _on_move_end(self, hwnd: int):
        if self._current_drag is None:
            return
        info               = self._current_drag
        self._current_drag = None
        if self._cursor_in_drop_zone():
            self.dropped_in_zone.emit(info)
        else:
            self.drag_cancelled.emit()

    def _cursor_in_drop_zone(self) -> bool:
        if self._drop_zone_rect is None:
            return False
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        x, y, w, h = self._drop_zone_rect
        return x <= pt.x <= x + w and y <= pt.y <= y + h

    def _capture_window_info(self, hwnd: int) -> dict | None:
        try:
            import psutil
        except ImportError:
            return None

        try:
            pid_val_raw = ctypes.wintypes.DWORD(0)
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_val_raw))
            pid_val = pid_val_raw.value
            if not pid_val:
                return None

            proc = psutil.Process(pid_val)
            exe  = proc.exe()
            if not exe:
                return None

            exe_path = Path(exe)
            stem     = exe_path.stem.lower()

            # ── Background / noise ─────────────────────────────────────────────
            _SKIP = frozenset({
                "svchost", "conhost", "csrss", "lsass", "wininit", "winlogon",
                "dwm", "sihost", "fontdrvhost", "runtimebroker",
                "backgroundtaskhost", "taskhostw", "spoolsv", "searchhost",
                "textinputhost", "applicationframehost", "shellexperiencehost",
                "startmenuexperiencehost", "lockapp", "logonui",
                "python", "pythonw", "python3", "node", "nodejs",
                "java", "javaw", "ruby", "perl", "php",
                "bash", "sh", "zsh", "powershell", "pwsh", "cmd",
            })
            if stem in _SKIP:
                return None

            # ── Chrome / Edge / Brave — read URL via UIAutomation ──────────────
            _BROWSER_STEMS = {
                "chrome": "Chrome", "chromium": "Chromium",
                "msedge": "Edge",   "brave":    "Brave",
                "firefox": "Firefox",
            }
            if stem in _BROWSER_STEMS:
                browser_name = _BROWSER_STEMS[stem]
                url = _get_chrome_active_url(hwnd)
                if url:
                    # Get tab title from window title (strip " - Browser Name" suffix)
                    buf = ctypes.create_unicode_buffer(512)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                    title = buf.value.strip()
                    for suffix in (f" - {browser_name}", f" — {browser_name}",
                                   " - Google Chrome", " - Microsoft Edge"):
                        if title.endswith(suffix):
                            title = title[: -len(suffix)].strip()
                            break
                    label = title or url
                    return {
                        "type":        "url",
                        "path_or_url": url,
                        "label":       label,
                        "hwnd":        hwnd,
                        "pid":         pid_val,
                        "exe":         exe,
                    }
                # UIAutomation not installed or failed — skip silently
                return None

            # ── VS Code / Cursor ───────────────────────────────────────────────
            if stem in ("code", "code - insiders", "cursor"):
                # Primary: read cmdline of THIS specific instance
                item = _vscode_folder_from_cmdline(pid_val, exe)
                if item is None:
                    # Fallback: storage.json (global, less accurate)
                    item = _vscode_folder_from_storage(exe)
                if item is None:
                    item = {
                        "type":        "app",
                        "path_or_url": f"vscode-folder:{exe}||",
                        "label":       "VS Code",
                    }
                item["hwnd"] = hwnd
                item["pid"]  = pid_val
                item["exe"]  = exe
                return item

            # ── File Explorer ──────────────────────────────────────────────────
            if stem == "explorer":
                items = _get_file_explorer_windows(hwnd)
                if items:
                    item      = items[0]
                    item["hwnd"] = hwnd
                    item["pid"]  = pid_val
                    item["exe"]  = exe
                    return item
                return None

            # ── UWP ────────────────────────────────────────────────────────────
            wa_norm = os.path.normcase(r"C:\Program Files\WindowsApps")
            if wa_norm in os.path.normcase(exe):
                return {
                    "type":        "app",
                    "path_or_url": f"uwp:{exe}",
                    "label":       exe_path.stem,
                    "hwnd":        hwnd,
                    "pid":         pid_val,
                    "exe":         exe,
                }

            # ── Everything else ────────────────────────────────────────────────
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value.strip()

            label = title
            if " - " in label:
                parts = label.split(" - ")
                last  = parts[-1].strip()
                if len(last) < 40:
                    label = last
            if not label:
                label = exe_path.stem

            return {
                "type":        "app",
                "path_or_url": exe,
                "label":       label,
                "hwnd":        hwnd,
                "pid":         pid_val,
                "exe":         exe,
            }

        except Exception as e:
            print(f"[DragWatcher] capture error hwnd={hwnd}: {e}")
            return None

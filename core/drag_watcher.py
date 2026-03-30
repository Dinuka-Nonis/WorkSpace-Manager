"""
core/drag_watcher.py — Window drag detection via SetWinEventHook.

Bug fixes in this version
--------------------------
1. Chrome auto-add / wrong profile ("Person 1"):
   - _get_chrome_profile_for_hwnd now uses GetWindowThreadProcessId on the
     DRAGGED hwnd to get the owning PID, then walks up to the browser process
     from THAT specific PID. Previously it was receiving the renderer PID of
     whatever chrome process happened to own the message-queue thread, not the
     browser-frame process, so --profile-directory= was never found.
   - Strategy 5 no longer falls back to "Default" when detection fails.
     Instead we return ("", "") and skip saving a URL with a wrong profile,
     rather than silently tagging everything as "Person 1".
   - _capture_window_info for Chrome: if profile detection returns ("","") AND
     uiautomation is available and returns a URL, we still save the URL but
     without a profile prefix — so it opens in whatever profile is active at
     restore time, rather than always forcing "Default" / Person 1.

2. File Explorer wrong window detection:
   - _get_file_explorer_windows now receives the dragged hwnd and uses
     IShellWindows.FindWindowSW (via comtypes) or iterates Shell.Windows()
     comparing each window's hwnd against the dragged hwnd directly. Only the
     folder that corresponds to the EXACT dragged window is returned.
   - Falls back to SHGetPathFromIDList + IFolderView via win32com if comtypes
     is unavailable.
   - If the dragged hwnd can't be matched to any open Explorer folder (e.g.
     the Desktop or a zip-file preview), we return [] so nothing is saved.
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
    try:
        import psutil
        proc    = psutil.Process(pid)
        cmdline = proc.cmdline()
    except Exception:
        return None

    candidate_paths: list[str] = []
    for arg in cmdline[1:]:
        if arg.startswith("-"):
            continue
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
    """Read the active tab URL from a Chrome window via UIAutomation."""
    try:
        import uiautomation as auto  # type: ignore
        ctrl = auto.ControlFromHandle(hwnd)
        if ctrl is None:
            return None
        for name in ("Address and search bar", "Address bar"):
            try:
                edit = ctrl.EditControl(Name=name)
                if edit.Exists(0, 0):
                    val = edit.GetValuePattern().Value
                    if val and ("." in val or val.startswith("http")):
                        if not val.startswith(("http://", "https://", "file://")):
                            val = "https://" + val
                        return val
            except Exception:
                continue
    except ImportError:
        if not getattr(_get_chrome_active_url, "_warned", False):
            _get_chrome_active_url._warned = True  # type: ignore
            print("[DragWatcher] Chrome URL detection disabled — "
                  "run: pip install uiautomation")
    except Exception as e:
        print(f"[DragWatcher] Chrome URL read error: {e}")
    return None


def _load_chrome_local_state() -> dict:
    """Return Chrome Local State profile info_cache, or {} on failure."""
    local_appdata = os.getenv("LOCALAPPDATA", "")
    local_state   = os.path.join(local_appdata, "Google", "Chrome", "User Data", "Local State")
    if not os.path.exists(local_state):
        return {}
    try:
        data = json.loads(open(local_state, encoding="utf-8", errors="replace").read())
        return data.get("profile", {}).get("info_cache", {})
    except Exception:
        return {}


def _get_chrome_profile_for_hwnd(hwnd: int, pid: int) -> tuple[str, str]:
    """
    Determine which Chrome profile owns a given window (hwnd / pid).

    ROOT CAUSE FIX:
      GetWindowThreadProcessId(hwnd) returns the PID of the THREAD that owns
      the window's message queue. For a Chrome browser frame, this is the
      *browser process* itself (not a renderer). However, the old code was
      calling psutil.Process(pid) where pid came from the WinEvent callback —
      which for tab-drag events can be a utility/renderer process ID.

      We now do a fresh GetWindowThreadProcessId call on the EXACT dragged
      hwnd to get the window's owning PID, then walk the tree from there.

    Strategies (in order):
      1. Fresh GetWindowThreadProcessId on hwnd → find browser process PID.
      2. Walk parent chain of that PID to find chrome.exe without --type=.
      3. Window title matching against Local State profile display names.
      4. If exactly one profile's browser process is running, use that.
      5. Return ("", "") — do NOT fall back to "Default"/"Person 1".
         The caller will save the URL without a profile tag rather than
         wrongly attributing it to the wrong profile.
    """
    try:
        import psutil
    except ImportError:
        return "", ""

    info_cache = _load_chrome_local_state()

    def _name_for_dir(d: str) -> str:
        return info_cache.get(d, {}).get("name", d)

    def _profile_from_cmdline(p) -> str:
        try:
            for arg in (p.cmdline() or []):
                if arg.startswith("--profile-directory="):
                    return arg.split("=", 1)[1].strip('"').strip("'")
        except Exception:
            pass
        return ""

    def _is_browser_proc(p) -> bool:
        """Browser process = chrome.exe with no --type= flag."""
        try:
            if "chrome.exe" not in (p.exe() or "").lower():
                return False
            for arg in (p.cmdline() or []):
                if arg.startswith("--type="):
                    return False
            return True
        except Exception:
            return False

    # ── Strategy 1: get the WINDOW-owning PID directly from the hwnd ──────────
    # This is more reliable than using the WinEvent callback's pid parameter,
    # which may belong to a renderer/utility subprocess.
    window_pid = pid  # start with what we were given
    try:
        fresh_pid = ctypes.wintypes.DWORD(0)
        ctypes.windll.user32.GetWindowThreadProcessId(
            ctypes.wintypes.HWND(hwnd), ctypes.byref(fresh_pid)
        )
        if fresh_pid.value:
            window_pid = fresh_pid.value
    except Exception:
        pass

    # ── Strategy 2: walk parent chain from window_pid ─────────────────────────
    try:
        proc       = psutil.Process(window_pid)
        candidates = [proc]
        p          = proc
        for _ in range(6):
            try:
                parent = p.parent()
                if parent is None or parent.pid <= 4:
                    break
                if "chrome.exe" not in (parent.exe() or "").lower():
                    break
                candidates.append(parent)
                p = parent
            except Exception:
                break

        for candidate in candidates:
            if not _is_browser_proc(candidate):
                continue
            d = _profile_from_cmdline(candidate)
            if d:
                print(f"[DragWatcher] Chrome profile via process tree: "
                      f"{d!r} ({_name_for_dir(d)}) [window_pid={window_pid}]")
                return d, _name_for_dir(d)
    except Exception:
        pass

    # ── Strategy 3: window title matching ─────────────────────────────────────
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
    win_title = buf.value.strip()
    for d, pinfo in info_cache.items():
        display_name = pinfo.get("name", "")
        if display_name and display_name in win_title:
            print(f"[DragWatcher] Chrome profile via window title: {d!r} ({display_name})")
            return d, display_name

    # ── Strategy 4: only one profile running ──────────────────────────────────
    running: dict[str, int] = {}
    try:
        for proc in psutil.process_iter(["exe"]):
            try:
                if "chrome.exe" not in (proc.info.get("exe") or "").lower():
                    continue
                if not _is_browser_proc(proc):
                    continue
                d = _profile_from_cmdline(proc)
                if d:
                    running[d] = running.get(d, 0) + 1
            except Exception:
                continue
    except Exception:
        pass

    if len(running) == 1:
        d = next(iter(running))
        print(f"[DragWatcher] Chrome profile via single-profile heuristic: {d!r}")
        return d, _name_for_dir(d)

    # ── Strategy 5: give up — do NOT default to "Default" ─────────────────────
    # Returning ("", "") tells the caller to save the URL without a profile
    # prefix instead of wrongly tagging it as "Person 1" / Default.
    print(f"[DragWatcher] Chrome profile detection failed for hwnd={hwnd} — "
          f"saving URL without profile binding")
    return "", ""


def _get_explorer_folder_for_hwnd(hwnd: int) -> dict | None:
    """
    Return the folder path for the SPECIFIC File Explorer window identified
    by hwnd.

    BUG FIX: The old _get_file_explorer_windows() enumerated ALL open Explorer
    windows and returned items[0] — the first one found, which was almost never
    the one being dragged. We now match by hwnd.

    Approach:
      1. comtypes: iterate Shell.Windows(), compare win.HWND to dragged hwnd.
      2. win32com fallback: same loop using win32com.client.
      3. UIAutomation fallback: read the address bar of that specific hwnd.
      4. Return None if nothing matches (e.g. Desktop, zip preview).
    """
    if sys.platform != "win32":
        return None

    def _make_result(folder_path: str) -> dict | None:
        folder_path = os.path.normpath(folder_path)
        if not os.path.exists(folder_path):
            return None
        name = os.path.basename(folder_path.rstrip("/\\")) or folder_path
        return {
            "type":        "app",
            "path_or_url": f"explorer-folder:{folder_path}",
            "label":       f"File Explorer — {name}",
        }

    # ── Try comtypes first ────────────────────────────────────────────────────
    try:
        import comtypes.client  # type: ignore
        shell   = comtypes.client.CreateObject("Shell.Application")
        windows = shell.Windows()
        for i in range(windows.Count):
            try:
                win = windows.Item(i)
                if win is None:
                    continue
                # Compare window handles
                try:
                    win_hwnd = int(win.HWND)
                except Exception:
                    continue
                if win_hwnd != hwnd:
                    continue
                loc = getattr(win, "LocationURL", None) or ""
                if loc.startswith("file://"):
                    path = _uri_to_local_path(loc)
                    if path:
                        result = _make_result(path)
                        if result:
                            print(f"[DragWatcher] Explorer folder (comtypes hwnd match): {path}")
                            return result
            except Exception:
                continue
    except Exception:
        pass

    # ── Fallback: win32com ────────────────────────────────────────────────────
    try:
        import win32com.client  # type: ignore
        shell = win32com.client.Dispatch("Shell.Application")
        for win in shell.Windows():
            try:
                try:
                    win_hwnd = int(win.HWND)
                except Exception:
                    continue
                if win_hwnd != hwnd:
                    continue
                loc = getattr(win, "LocationURL", None) or ""
                if loc.startswith("file://"):
                    path = _uri_to_local_path(loc)
                    if path:
                        result = _make_result(path)
                        if result:
                            print(f"[DragWatcher] Explorer folder (win32com hwnd match): {path}")
                            return result
            except Exception:
                continue
    except Exception:
        pass

    # ── Fallback: read address bar via UIAutomation ───────────────────────────
    try:
        import uiautomation as auto  # type: ignore
        ctrl = auto.ControlFromHandle(hwnd)
        if ctrl is not None:
            # Try the address bar edit control
            for name in ("Address", "Address bar"):
                try:
                    edit = ctrl.EditControl(Name=name)
                    if edit.Exists(0, 0):
                        val = edit.GetValuePattern().Value
                        if val and os.path.isdir(val):
                            result = _make_result(val)
                            if result:
                                print(f"[DragWatcher] Explorer folder (UIAutomation): {val}")
                                return result
                except Exception:
                    continue
            # Also try the breadcrumb bar text
            try:
                for tb in ctrl.GetChildren():
                    try:
                        name_val = tb.Name
                        if name_val and os.path.isabs(name_val) and os.path.isdir(name_val):
                            result = _make_result(name_val)
                            if result:
                                return result
                    except Exception:
                        continue
            except Exception:
                pass
    except ImportError:
        pass
    except Exception as e:
        print(f"[DragWatcher] Explorer UIAutomation fallback error: {e}")

    # ── Nothing matched this hwnd ─────────────────────────────────────────────
    print(f"[DragWatcher] Explorer hwnd={hwnd} not matched to any open folder — skipping")
    return None


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

    # Both thresholds must be exceeded for an event to be treated as a real drag.
    # Chrome tab-open window repositions complete in <50ms with <5px movement.
    # Human drags to the right edge take 300ms+ and travel 100px+.
    _MIN_DRAG_MS = 250
    _MIN_DRAG_PX = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drop_zone_rect: tuple[int, int, int, int] | None = None
        self._current_drag: dict | None = None
        self._hook      = None
        self._hook_proc = None
        self._running   = False
        self._thread_id = 0
        self._drag_start_time: float = 0.0
        self._drag_start_pos:  tuple[int, int] = (0, 0)
        self.finished.connect(self.deleteLater)

    def set_drop_zone_rect(self, x: int, y: int, w: int, h: int):
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
        import time as _time
        info = self._capture_window_info(hwnd)
        if info is None:
            self._current_drag = None
            return
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        self._drag_start_time = _time.monotonic()
        self._drag_start_pos  = (pt.x, pt.y)
        self._current_drag    = info
        self.drag_started.emit(info)

    def _on_move_end(self, hwnd: int):
        import time as _time
        if self._current_drag is None:
            return
        info               = self._current_drag
        self._current_drag = None

        # Duration guard — rejects tab-open/close window repositions
        elapsed_ms = (_time.monotonic() - self._drag_start_time) * 1000
        if elapsed_ms < self._MIN_DRAG_MS:
            print(f"[DragWatcher] Rejected ({elapsed_ms:.0f}ms < {self._MIN_DRAG_MS}ms)")
            self.drag_cancelled.emit()
            return

        # Distance guard — rejects window snap/restore events
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        manhattan = abs(pt.x - self._drag_start_pos[0]) + abs(pt.y - self._drag_start_pos[1])
        if manhattan < self._MIN_DRAG_PX:
            print(f"[DragWatcher] Rejected ({manhattan}px < {self._MIN_DRAG_PX}px)")
            self.drag_cancelled.emit()
            return

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

            # ── Chrome / Edge / Brave ──────────────────────────────────────────
            _BROWSER_STEMS = {
                "chrome": "Chrome", "chromium": "Chromium",
                "msedge": "Edge",   "brave":    "Brave",
                "firefox": "Firefox",
            }
            if stem in _BROWSER_STEMS:
                browser_name = _BROWSER_STEMS[stem]
                url = _get_chrome_active_url(hwnd)
                if url:
                    buf = ctypes.create_unicode_buffer(512)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                    title = buf.value.strip()
                    for suffix in (f" - {browser_name}", f" — {browser_name}",
                                   " - Google Chrome", " - Microsoft Edge"):
                        if title.endswith(suffix):
                            title = title[: -len(suffix)].strip()
                            break
                    label = title or url

                    profile_dir, profile_name = "", ""
                    if stem == "chrome":
                        # Pass BOTH hwnd and pid_val so the profile detector
                        # can use GetWindowThreadProcessId on the exact hwnd.
                        profile_dir, profile_name = _get_chrome_profile_for_hwnd(hwnd, pid_val)

                    if profile_dir:
                        encoded_url = f"chrome-profile:{profile_dir}|{url}"
                        if profile_name:
                            label = f"[{profile_name}] {label}"
                    else:
                        # Profile detection failed — store plain URL, no profile
                        # prefix. Better to lose profile info than to wrongly
                        # tag as "Person 1" / Default.
                        encoded_url = url

                    return {
                        "type":        "url",
                        "path_or_url": encoded_url,
                        "label":       label,
                        "hwnd":        hwnd,
                        "pid":         pid_val,
                        "exe":         exe,
                    }
                return None

            # ── VS Code / Cursor ───────────────────────────────────────────────
            if stem in ("code", "code - insiders", "cursor"):
                item = _vscode_folder_from_cmdline(pid_val, exe)
                if item is None:
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
                # FIX: pass the exact hwnd so only the dragged window is matched
                item = _get_explorer_folder_for_hwnd(hwnd)
                if item:
                    item["hwnd"] = hwnd
                    item["pid"]  = pid_val
                    item["exe"]  = exe
                    return item
                return None

            # ── UWP / Microsoft Store ──────────────────────────────────────────
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

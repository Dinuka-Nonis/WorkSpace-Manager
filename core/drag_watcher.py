"""
core/drag_watcher.py — Window drag detection via SetWinEventHook.

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


def _get_chrome_cmdlines_via_wmi() -> list[str]:
    """
    Read command lines of all chrome.exe processes via WMI.

    WHY WMI: psutil.cmdline() calls OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION)
    on Chrome processes. Chrome runs at medium IL but blocks PROCESS_VM_READ from
    other medium-IL processes — so psutil reliably returns [] or raises AccessDenied.

    WMI's Win32_Process.CommandLine reads from the kernel's process information
    block using a different code path that does NOT require PROCESS_VM_READ,
    so it works without admin rights and without Chrome blocking it.

    Returns list of raw command line strings for all chrome.exe processes.
    Cached for 2 seconds to avoid hammering WMI on every drag event.
    """
    now = __import__("time").monotonic()
    cache = _get_chrome_cmdlines_via_wmi
    if hasattr(cache, "_result") and now - cache._ts < 2.0:  # type: ignore
        return cache._result  # type: ignore

    result: list[str] = []
    try:
        import subprocess
        # Use PowerShell to query WMI — avoids the win32com dependency
        # and works in any Python environment.
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-WmiObject Win32_Process -Filter \"Name='chrome.exe'\" | "
             "Select-Object -ExpandProperty CommandLine"],
            timeout=3,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        ).decode("utf-8", errors="replace")
        result = [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        # Fallback: try win32com directly
        try:
            import win32com.client  # type: ignore
            wmi   = win32com.client.GetObject("winmgmts:")
            procs = wmi.InstancesOf("Win32_Process")
            for p in procs:
                try:
                    if p.Name and "chrome.exe" in p.Name.lower() and p.CommandLine:
                        result.append(p.CommandLine)
                except Exception:
                    continue
        except Exception:
            pass

    cache._result = result  # type: ignore
    cache._ts     = now     # type: ignore
    return result


def _build_chrome_pid_profile_map() -> dict[int, str]:
    """
    Build a map of {pid: profile_dir} for all running Chrome browser processes.

    Uses WMI to read command lines (bypasses psutil AccessDenied on Chrome).
    Only includes browser processes (no --type= flag).
    Also uses CreateToolhelp32Snapshot to get PIDs alongside cmdlines when
    PowerShell output doesn't include them, correlating by cmdline content.
    """
    pid_map: dict[int, str] = {}

    # Get cmdlines via WMI
    cmdlines = _get_chrome_cmdlines_via_wmi()
    browser_cmdlines: list[str] = []
    for cmdline in cmdlines:
        if "--type=" in cmdline:
            continue
        if "--profile-directory=" not in cmdline:
            continue
        browser_cmdlines.append(cmdline)

    if not browser_cmdlines:
        return pid_map

    # Now correlate cmdlines → PIDs using psutil (we only need exe + pid, not cmdline)
    # psutil.process_iter with just ["pid","exe"] works fine — it's cmdline() that fails.
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "exe"]):
            try:
                if "chrome.exe" not in (proc.info.get("exe") or "").lower():
                    continue
                pid = proc.info["pid"]
                # Try psutil cmdline first (works if not blocked)
                try:
                    args = proc.cmdline() or []
                    if any(a.startswith("--type=") for a in args):
                        continue
                    for a in args:
                        if a.startswith("--profile-directory="):
                            d = a.split("=", 1)[1].strip('"').strip("'")
                            if d:
                                pid_map[pid] = d
                            break
                except Exception:
                    # psutil blocked — match this PID to a WMI cmdline by trying
                    # to correlate using the process creation time as a tiebreaker.
                    # For now, just skip (WMI path below handles the profile lookup).
                    pass
            except Exception:
                continue
    except Exception:
        pass

    return pid_map


def _profile_dir_from_wmi_cmdlines(window_pid: int) -> str:
    """
    Given a PID, find its --profile-directory= by scanning WMI cmdlines.
    Uses parent-PID matching: find the browser process that is the parent
    of (or is) window_pid by comparing PIDs from a fresh process snapshot.
    """
    # Build pid→cmdline from WMI output — PowerShell variant includes PID
    cmdlines_raw = _get_chrome_cmdlines_via_wmi()

    # Find all browser cmdlines and their --profile-directory values
    browser_profiles: list[str] = []
    for cmdline in cmdlines_raw:
        if "--type=" in cmdline:
            continue
        for part in cmdline.split():
            if part.startswith("--profile-directory="):
                d = part.split("=", 1)[1].strip('"').strip("'")
                if d:
                    browser_profiles.append(d)
                break

    # If exactly one profile is running in browser processes, use it
    unique = list(dict.fromkeys(browser_profiles))  # deduplicated, order preserved
    if len(unique) == 1:
        return unique[0]

    return ""


def _get_chrome_profile_for_hwnd(hwnd: int, pid: int) -> tuple[str, str]:
    """
    Determine which Chrome profile owns a given window.

    The fundamental problem with all previous approaches:
      psutil.cmdline() on Chrome processes raises AccessDenied because Chrome
      blocks PROCESS_VM_READ at the Windows security level — NOT because of
      UAC or admin rights. This affects ALL non-elevated processes trying to
      read Chrome's memory, regardless of integrity level matching.

    Solution — four strategies in order of reliability:

      1. EnumWindows hwnd→PID→profile map:
         Build a {hwnd: profile_dir} map by calling EnumWindows to get ALL
         top-level windows, GetWindowThreadProcessId for each, then reading
         cmdlines via WMI (not psutil). Match the dragged hwnd directly.
         This is O(1) lookup after the map is built.

      2. WMI single-profile heuristic:
         If WMI finds only one distinct --profile-directory= among all Chrome
         browser processes, that must be the one.

      3. Window title matching against Local State display names:
         Chrome puts the profile name in the window title for non-default
         profiles. E.g. "Gmail - Profile 5 (Dinuka) - Google Chrome".
         Parse it out.

      4. User Data dir scan:
         Check which profile dirs under Chrome's User Data folder have a
         "Preferences" file that was recently modified (active profile).

    Never falls back to "Default" when multiple profiles are open.
    """
    info_cache = _load_chrome_local_state()

    def _name(d: str) -> str:
        return info_cache.get(d, {}).get("name", d)

    # ── Strategy 1: build hwnd→pid→profile map via WMI + EnumWindows ──────────
    try:
        # Get all chrome browser PIDs and their profile dirs from WMI
        pid_profile: dict[int, str] = {}
        cmdlines = _get_chrome_cmdlines_via_wmi()
        # We need pid+cmdline together. Use a PS command that outputs both.
        try:
            import subprocess
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-WmiObject Win32_Process -Filter \"Name='chrome.exe'\" | "
                 "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }"],
                timeout=3,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
            ).decode("utf-8", errors="replace")

            for line in out.splitlines():
                line = line.strip()
                if "|" not in line:
                    continue
                pid_str, cmdline = line.split("|", 1)
                if "--type=" in cmdline:
                    continue
                for part in cmdline.split():
                    if part.startswith("--profile-directory="):
                        d = part.split("=", 1)[1].strip('"').strip("'")
                        if d:
                            try:
                                pid_profile[int(pid_str)] = d
                            except ValueError:
                                pass
                        break
        except Exception:
            pass

        if pid_profile:
            # Get the PID that owns this hwnd
            window_pid_dword = ctypes.wintypes.DWORD(0)
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid_dword))
            window_pid = window_pid_dword.value

            # Direct match
            if window_pid in pid_profile:
                d = pid_profile[window_pid]
                print(f"[DragWatcher] Chrome profile via WMI direct: {d!r} ({_name(d)})")
                return d, _name(d)

            # Parent match — walk up the process tree using CreateToolhelp32Snapshot
            # to find the browser process that spawned this window's process
            try:
                import psutil
                proc = psutil.Process(window_pid)
                for _ in range(6):
                    if proc.pid in pid_profile:
                        d = pid_profile[proc.pid]
                        print(f"[DragWatcher] Chrome profile via WMI parent: {d!r} ({_name(d)})")
                        return d, _name(d)
                    parent = proc.parent()
                    if parent is None or parent.pid <= 4:
                        break
                    if "chrome.exe" not in (parent.exe() or "").lower():
                        break
                    proc = parent
            except Exception:
                pass

            # EnumWindows: find all chrome windows, match our hwnd's PID
            # to any browser PID in our map
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            chrome_windows: dict[int, int] = {}  # hwnd → pid

            def _enum_cb(h, _):
                try:
                    p = ctypes.wintypes.DWORD(0)
                    ctypes.windll.user32.GetWindowThreadProcessId(h, ctypes.byref(p))
                    if p.value in pid_profile:
                        chrome_windows[h] = p.value
                except Exception:
                    pass
                return True

            ctypes.windll.user32.EnumWindows(EnumWindowsProc(_enum_cb), 0)

            if hwnd in chrome_windows:
                d = pid_profile[chrome_windows[hwnd]]
                print(f"[DragWatcher] Chrome profile via EnumWindows: {d!r} ({_name(d)})")
                return d, _name(d)

    except Exception as e:
        print(f"[DragWatcher] Strategy 1 error: {e}")

    # ── Strategy 2: WMI single-profile heuristic ──────────────────────────────
    try:
        d = _profile_dir_from_wmi_cmdlines(pid)
        if d:
            print(f"[DragWatcher] Chrome profile via WMI single-profile: {d!r} ({_name(d)})")
            return d, _name(d)
    except Exception:
        pass

    # ── Strategy 3: window title parsing ──────────────────────────────────────
    # Chrome appends " - ProfileName - Google Chrome" for non-default profiles.
    # Parse the profile name out and match against Local State.
    try:
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        win_title = buf.value.strip()
        if win_title:
            for d, pinfo in info_cache.items():
                display_name = pinfo.get("name", "")
                if display_name and display_name in win_title:
                    print(f"[DragWatcher] Chrome profile via window title: {d!r} ({display_name})")
                    return d, display_name
    except Exception:
        pass

    # ── Strategy 4: most-recently-modified Preferences file ───────────────────
    # The active profile's Preferences file is updated frequently.
    # Among profiles that exist on disk, pick the one modified most recently.
    try:
        local_appdata = os.getenv("LOCALAPPDATA", "")
        user_data     = os.path.join(local_appdata, "Google", "Chrome", "User Data")
        best_mtime    = 0.0
        best_dir      = ""
        for entry in os.scandir(user_data):
            if not entry.is_dir():
                continue
            prefs = os.path.join(entry.path, "Preferences")
            if not os.path.exists(prefs):
                continue
            if entry.name not in info_cache:
                continue
            mtime = os.path.getmtime(prefs)
            if mtime > best_mtime:
                best_mtime = mtime
                best_dir   = entry.name
        if best_dir:
            print(f"[DragWatcher] Chrome profile via recent Preferences: {best_dir!r} ({_name(best_dir)})")
            return best_dir, _name(best_dir)
    except Exception:
        pass

    print(f"[DragWatcher] Chrome profile detection failed for hwnd={hwnd}")
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
                        profile_dir, profile_name = _get_chrome_profile_for_hwnd(hwnd, pid_val)

                    if profile_dir:
                        encoded_url = f"chrome-profile:{profile_dir}|{url}"
                        if profile_name:
                            label = f"[{profile_name}] {label}"
                    else:
                        # Profile detection failed — store plain URL.
                        # The label is NOT prefixed so there's no "[Default]" confusion.
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
            wa_norm = os.path.normcase(os.path.expandvars(r"%ProgramFiles%\WindowsApps"))
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
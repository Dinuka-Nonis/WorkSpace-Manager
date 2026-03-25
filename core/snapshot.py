"""
core/snapshot.py — Snapshot capture for WorkSpace Manager.

Key change: capture_running_apps() now returns FOREGROUND apps only —
processes that have a visible, non-minimized window. This filters out
background services, updaters, and startup helpers that the user never
consciously opened.

The user then sees a checklist and picks which ones to save, so nothing
gets stored without explicit confirmation.
"""

import os
import sys
import time
import json
import threading
from pathlib import Path


# ── Heuristics for "is this a real foreground app?" ──────────────────────────
#
# We use two filters on top of the app-registry cross-reference:
#   1. The process must have at least one visible, non-zero-size window
#      (Win32: EnumWindows + IsWindowVisible + GetWindowRect).
#   2. A small block-list of exe stems that are always background noise even
#      when they technically have a window handle.
#
# On non-Windows we fall back to registry-match only (no window check).

_BACKGROUND_STEMS = frozenset({
    # Office / MS helpers
    "officeclicktorun", "msoia", "msosync", "onedrive", "onedrivesetup",
    "searchindexer", "searchhost", "searchapp",
    # MSI / hardware helpers
    "msiapservice", "msibgs", "nahimicnotifysys", "nahimicnotifysys",
    "audiodg", "ibtsiva", "igfxem", "igfxhk", "igfxsrvc",
    # Windows internals
    "svchost", "conhost", "csrss", "lsass", "wininit", "winlogon",
    "dwm", "explorer",          # explorer is the shell, not "open by user"
    "sihost", "fontdrvhost",
    "runtimebroker", "backgroundtaskhost", "taskhostw",
    "spoolsv", "wuauclt", "trustedinstaller",
    # Updaters / crash reporters
    "crashpad_handler", "crashreporter", "update", "updater",
    "helperservice", "setup", "installer",
    # Terminals launched by other apps (not user-opened)
    "cmd",              # cmd.exe is almost always a child process
    "conhost",
})


def _has_visible_window_win32(pid: int) -> bool:
    """
    Return True if the process has at least one visible, non-trivial window.
    Uses ctypes so we don't need pywin32.
    """
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32

        found = ctypes.c_bool(False)

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                          ctypes.wintypes.HWND,
                                          ctypes.wintypes.LPARAM)

        def _enum_cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            # GetWindowTextLength > 0 means the window has a title
            if user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            # Check process id
            proc_id = ctypes.wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if proc_id.value != pid:
                return True
            # Check window has non-zero size
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if rect.right - rect.left < 10 or rect.bottom - rect.top < 10:
                return True
            found.value = True
            return False  # stop enumeration

        cb = WNDENUMPROC(_enum_cb)
        user32.EnumWindows(cb, 0)
        return found.value
    except Exception:
        return False


def capture_running_apps() -> list[dict]:
    """
    Return app items for currently running foreground applications that
    are in the installed-app registry. Deduplicated by exe path.

    On Windows: only processes with a real visible window are included.
    On other platforms: registry-match only (no window filter).

    Returns a list of dicts: {type, path_or_url, label}
    """
    try:
        import psutil
    except ImportError:
        return []

    try:
        from core.app_registry import get_installed_apps
        known: dict[str, dict] = {
            os.path.normcase(a["exe_path"]): a
            for a in get_installed_apps()
            if a.get("exe_path")
        }
    except Exception:
        return []

    is_win = sys.platform == "win32"
    seen:    set[str]  = set()
    results: list[dict] = []

    for proc in psutil.process_iter(["exe", "pid", "name"]):
        try:
            raw_exe = proc.info.get("exe") or ""
            if not raw_exe:
                continue

            key = os.path.normcase(raw_exe)
            if key in seen:
                continue
            if key not in known:
                continue

            # Block-list check on stem
            stem = Path(raw_exe).stem.lower()
            if stem in _BACKGROUND_STEMS:
                continue
            # Also block anything whose stem contains these substrings
            if any(sub in stem for sub in ("helper", "updater", "service",
                                           "agent", "daemon", "notif",
                                           "crash", "report")):
                continue

            # On Windows, require a real visible window
            if is_win:
                pid = proc.info.get("pid") or 0
                if pid and not _has_visible_window_win32(pid):
                    continue

            seen.add(key)
            app = known[key]
            results.append({
                "type":        "app",
                "path_or_url": app["exe_path"],
                "label":       app["name"],
            })
        except Exception:
            continue

    return results


# ── Chrome-tab capture (side-channel) ─────────────────────────────────────────

_TAB_REQUEST_TIMEOUT = 3.0

def request_tabs_from_extension(session_id: int) -> list[dict]:
    """
    Ask the native host to pull tabs from Chrome via the side-channel file.
    Returns [] if host is not running or times out.
    """
    appdata   = Path(os.getenv("APPDATA", ".")) / "WorkSpaceManager"
    req_file  = appdata / "tab_request.json"
    resp_file = appdata / "tab_response.json"

    try:
        if resp_file.exists():
            resp_file.unlink()
        req_file.write_text(
            json.dumps({"session_id": session_id, "ts": time.time()}),
            encoding="utf-8",
        )
    except Exception:
        return []

    deadline = time.time() + _TAB_REQUEST_TIMEOUT
    while time.time() < deadline:
        if resp_file.exists():
            try:
                payload   = json.loads(resp_file.read_text(encoding="utf-8"))
                req_file.unlink(missing_ok=True)
                resp_file.unlink(missing_ok=True)
                return [
                    {
                        "type":        "url",
                        "path_or_url": t["url"],
                        "label":       t.get("title") or t["url"],
                    }
                    for t in payload.get("tabs", [])
                    if t.get("url")
                ]
            except Exception:
                break
        time.sleep(0.12)

    req_file.unlink(missing_ok=True)
    return []


# ── Scan only (no DB write) — for the picker dialog ──────────────────────────

def scan_for_picker(session_id: int) -> dict:
    """
    Scan running apps and Chrome tabs concurrently.
    Returns raw lists so the UI can show a picker before any DB write.

    {
      "apps": [{type, path_or_url, label}, ...],
      "tabs": [{type, path_or_url, label}, ...],
    }
    """
    apps: list[dict] = []
    tabs: list[dict] = []
    app_done = threading.Event()
    tab_done = threading.Event()

    def _get_apps():
        nonlocal apps
        try:
            apps = capture_running_apps()
        except Exception:
            apps = []
        app_done.set()

    def _get_tabs():
        nonlocal tabs
        try:
            tabs = request_tabs_from_extension(session_id)
        except Exception:
            tabs = []
        tab_done.set()

    ta = threading.Thread(target=_get_apps, daemon=True)
    tt = threading.Thread(target=_get_tabs,  daemon=True)
    ta.start(); tt.start()
    app_done.wait(timeout=6.0)
    tab_done.wait(timeout=_TAB_REQUEST_TIMEOUT + 0.5)

    return {"apps": apps, "tabs": tabs}

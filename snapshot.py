"""
snapshot.py — Captures open windows on the current virtual desktop.
Uses win32gui for window enumeration and psutil for process info.
Uses pyvda to filter by virtual desktop.
"""

import os
import sys

# Guard: this module only works on Windows
if sys.platform != "win32":
    def snapshot_desktop(desktop_id: str = None) -> list[dict]:
        return []
else:
    import psutil

    try:
        import win32gui
        import win32process
        import win32con
        WIN32_AVAILABLE = True
    except ImportError:
        WIN32_AVAILABLE = False

    try:
        from pyvda import AppView, VirtualDesktop, get_virtual_desktops
        PYVDA_AVAILABLE = True
    except ImportError:
        PYVDA_AVAILABLE = False

    # Apps to exclude from snapshots (system/background processes)
    EXCLUDED_EXE = {
        "explorer.exe", "dwm.exe", "winlogon.exe", "csrss.exe",
        "svchost.exe", "lsass.exe", "services.exe", "smss.exe",
        "taskhost.exe", "conhost.exe", "SearchUI.exe", "ShellExperienceHost.exe",
        "ApplicationFrameHost.exe", "SystemSettings.exe", "WorkSpaceManager.exe",
    }

    # Minimum window title length to consider
    MIN_TITLE_LEN = 2

    def _get_process_info(pid: int) -> dict:
        try:
            proc = psutil.Process(pid)
            exe = proc.exe()
            return {
                "exe_path": exe,
                "exe_name": os.path.basename(exe),
                "pid": pid,
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return {"exe_path": "", "exe_name": "", "pid": pid}

    def _is_real_window(hwnd: int) -> bool:
        """Filter out invisible, minimized-to-tray, and system windows."""
        if not WIN32_AVAILABLE:
            return False
        if not win32gui.IsWindowVisible(hwnd):
            return False
        title = win32gui.GetWindowText(hwnd)
        if len(title) < MIN_TITLE_LEN:
            return False
        # Must be a top-level window (no parent)
        if win32gui.GetParent(hwnd):
            return False
        # Must have WS_CAPTION style (title bar)
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        if not (style & win32con.WS_CAPTION):
            return False
        return True

    def _get_desktop_id_for_window(hwnd: int) -> str | None:
        """Get the virtual desktop GUID for a window."""
        if not PYVDA_AVAILABLE:
            return None
        try:
            view = AppView(hwnd)
            desktop = view.virtual_desktop()   # FIXED: was .desktop() — wrong API
            return str(desktop.id) if desktop else None
        except Exception:
            return None

    def snapshot_desktop(desktop_id: str = None) -> list[dict]:
        """
        Return list of window dicts on the given virtual desktop.
        If desktop_id is None, snapshots the current desktop.
        """
        if not WIN32_AVAILABLE:
            return []

        # Determine target desktop ID
        target_id = desktop_id
        if target_id is None and PYVDA_AVAILABLE:
            try:
                target_id = str(VirtualDesktop.current().id)
            except Exception:
                target_id = None

        captured = []

        def enum_handler(hwnd, _):
            if not _is_real_window(hwnd):
                return

            # If we have pyvda, filter by desktop.
            # STRICT: if we can't determine the window's desktop (returns None),
            # we skip it — better to miss a window than include wrong-desktop windows.
            if PYVDA_AVAILABLE and target_id:
                win_desktop = _get_desktop_id_for_window(hwnd)
                if win_desktop != target_id:   # None != target_id → correctly excluded
                    return

            try:
                title = win32gui.GetWindowText(hwnd)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc_info = _get_process_info(pid)

                if proc_info["exe_name"].lower() in EXCLUDED_EXE:
                    return

                captured.append({
                    "hwnd": hwnd,
                    "title": title,
                    **proc_info,
                })
            except Exception:
                pass

        try:
            win32gui.EnumWindows(enum_handler, None)
        except Exception:
            pass

        return captured


def get_current_desktop_id() -> str | None:
    """Get the GUID of the currently active virtual desktop."""
    if sys.platform != "win32" or not PYVDA_AVAILABLE:
        return None
    try:
        return str(VirtualDesktop.current().id)
    except Exception:
        return None


def get_all_desktop_ids() -> list[str]:
    """Return IDs of all virtual desktops."""
    if sys.platform != "win32" or not PYVDA_AVAILABLE:
        return []
    try:
        return [str(d.id) for d in get_virtual_desktops()]
    except Exception:
        return []


def get_desktop_count() -> int:
    """Return the number of virtual desktops."""
    if sys.platform != "win32":
        return 1
    if not PYVDA_AVAILABLE:
        return 1
    try:
        return len(get_virtual_desktops())
    except Exception:
        return 1


def friendly_app_name(exe_name: str) -> str:
    """Map exe names to human-friendly names."""
    mapping = {
        "Code.exe": "VS Code",
        "code.exe": "VS Code",
        "chrome.exe": "Chrome",
        "firefox.exe": "Firefox",
        "msedge.exe": "Edge",
        "brave.exe": "Brave",
        "opera.exe": "Opera",
        "SumatraPDF.exe": "Sumatra PDF",
        "AcroRd32.exe": "Adobe Reader",
        "Acrobat.exe": "Adobe Acrobat",
        "WINWORD.EXE": "Word",
        "EXCEL.EXE": "Excel",
        "POWERPNT.EXE": "PowerPoint",
        "notepad.exe": "Notepad",
        "notepad++.exe": "Notepad++",
        "WindowsTerminal.exe": "Terminal",
        "wt.exe": "Terminal",
        "cmd.exe": "CMD",
        "powershell.exe": "PowerShell",
        "python.exe": "Python",
        "pythonw.exe": "Python",
        "pycharm64.exe": "PyCharm",
        "idea64.exe": "IntelliJ",
        "webstorm64.exe": "WebStorm",
        "postman.exe": "Postman",
        "slack.exe": "Slack",
        "discord.exe": "Discord",
        "Obsidian.exe": "Obsidian",
        "figma.exe": "Figma",
        "Teams.exe": "Teams",
        "zoom.exe": "Zoom",
        "vlc.exe": "VLC",
        "mspaint.exe": "Paint",
        "devenv.exe": "Visual Studio",
    }
    return mapping.get(exe_name, exe_name.replace(".exe", "").replace(".EXE", ""))

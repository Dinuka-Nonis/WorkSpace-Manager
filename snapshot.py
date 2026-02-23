"""
snapshot.py — Per-desktop window capture using pyvda + win32gui.

Core insight: get_apps_by_z_order() is a TOP-LEVEL function that returns
ALL AppView objects across ALL virtual desktops. Each AppView has:
  .hwnd             — the window handle
  .virtual_desktop() — which VirtualDesktop it belongs to

Correct approach:
  1. Call get_apps_by_z_order() ONCE to get everything
  2. For each AppView, call .virtual_desktop().id to know which desktop
  3. Group by desktop_id → return the group you need

This is the only reliable method. Asking each hwnd "which desktop?" via
AppView(hwnd).virtual_desktop() fails silently for most apps.
"""

import os
import sys

if sys.platform != "win32":
    def snapshot_all_desktops() -> dict:
        return {}
    def snapshot_desktop(desktop_id=None) -> list:
        return []
    def get_current_desktop_id():
        return None
    def get_all_desktop_ids() -> list:
        return []
    def get_desktop_count() -> int:
        return 1
    def get_desktop_number(desktop_id) -> int | None:
        return None
    def friendly_app_name(exe_name: str) -> str:
        return exe_name
else:
    import psutil

    try:
        import win32gui, win32process, win32con
        WIN32_AVAILABLE = True
    except ImportError:
        WIN32_AVAILABLE = False
        print("[Snapshot] WARNING: pywin32 not installed.")

    try:
        from pyvda import AppView, VirtualDesktop, get_virtual_desktops, get_apps_by_z_order
        PYVDA_AVAILABLE = True
    except ImportError:
        PYVDA_AVAILABLE = False
        print("[Snapshot] WARNING: pyvda not installed.")

    EXCLUDED_EXE = {
        "explorer.exe", "dwm.exe", "winlogon.exe", "csrss.exe",
        "svchost.exe", "lsass.exe", "services.exe", "smss.exe",
        "taskhost.exe", "conhost.exe", "searchui.exe", "shellexperiencehost.exe",
        "applicationframehost.exe", "systemsettings.exe", "workspacemanager.exe",
        "searchhost.exe", "startmenuexperiencehost.exe", "textinputhost.exe",
        "runtimebroker.exe", "sihost.exe", "taskhostw.exe",
    }

    def _is_capturable(hwnd: int) -> bool:
        if not hwnd or not win32gui.IsWindowVisible(hwnd):
            return False
        title = win32gui.GetWindowText(hwnd)
        if len(title.strip()) < 2:
            return False
        if win32gui.GetParent(hwnd) != 0:
            return False
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        if not (style & win32con.WS_CAPTION):
            return False
        return True

    def _get_proc_info(pid: int) -> dict:
        try:
            proc = psutil.Process(pid)
            exe = proc.exe()
            return {"exe_path": exe, "exe_name": os.path.basename(exe), "pid": pid}
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return {"exe_path": "", "exe_name": "", "pid": pid}

    def snapshot_all_desktops() -> dict[str, list[dict]]:
        """
        Returns {desktop_id: [window_dict, ...]} for ALL virtual desktops.
        Uses get_apps_by_z_order() — the correct top-level pyvda function
        that returns every AppView the desktop manager knows about.
        """
        result: dict[str, list[dict]] = {}

        if not WIN32_AVAILABLE or not PYVDA_AVAILABLE:
            return result

        try:
            all_apps = get_apps_by_z_order()
            print(f"[Snapshot] {len(all_apps)} total app views across all desktops")
        except Exception as e:
            print(f"[Snapshot] get_apps_by_z_order() failed: {e}")
            return result

        for app in all_apps:
            try:
                hwnd = app.hwnd
                if not _is_capturable(hwnd):
                    continue

                # Which desktop does this window live on?
                try:
                    vd = app.virtual_desktop()
                    desktop_id = str(vd.id)
                except Exception:
                    continue  # can't determine desktop → skip

                title = win32gui.GetWindowText(hwnd)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = _get_proc_info(pid)

                if proc["exe_name"].lower() in EXCLUDED_EXE:
                    continue

                result.setdefault(desktop_id, []).append({
                    "hwnd": hwnd,
                    "title": title,
                    **proc,
                })

            except Exception:
                continue

        # Summary log
        for did, wins in result.items():
            exes = ", ".join(sorted({w["exe_name"] for w in wins}))
            print(f"[Snapshot]   Desktop {did[:8]}…: {len(wins)} windows [{exes}]")

        return result

    def snapshot_desktop(desktop_id: str = None) -> list[dict]:
        """Windows for a single desktop. Calls snapshot_all_desktops() internally."""
        if desktop_id is None:
            desktop_id = get_current_desktop_id()
        if not desktop_id:
            return []
        return snapshot_all_desktops().get(desktop_id, [])

    def get_current_desktop_id() -> str | None:
        if not PYVDA_AVAILABLE:
            return None
        try:
            return str(VirtualDesktop.current().id)
        except Exception:
            return None

    def get_all_desktop_ids() -> list[str]:
        if not PYVDA_AVAILABLE:
            return []
        try:
            return [str(d.id) for d in get_virtual_desktops()]
        except Exception:
            return []

    def get_desktop_count() -> int:
        if not PYVDA_AVAILABLE:
            return 1
        try:
            return len(get_virtual_desktops())
        except Exception:
            return 1

    def get_desktop_number(desktop_id: str) -> int | None:
        """1-based desktop number for display (Desktop 1, Desktop 2, ...)."""
        if not PYVDA_AVAILABLE:
            return None
        try:
            for i, d in enumerate(get_virtual_desktops(), 1):
                if str(d.id) == desktop_id:
                    return i
        except Exception:
            pass
        return None

    def friendly_app_name(exe_name: str) -> str:
        mapping = {
            "Code.exe": "VS Code", "code.exe": "VS Code",
            "chrome.exe": "Chrome", "firefox.exe": "Firefox",
            "msedge.exe": "Edge", "brave.exe": "Brave",
            "SumatraPDF.exe": "Sumatra PDF",
            "AcroRd32.exe": "Adobe Reader", "Acrobat.exe": "Adobe Acrobat",
            "WINWORD.EXE": "Word", "EXCEL.EXE": "Excel",
            "POWERPNT.EXE": "PowerPoint", "notepad.exe": "Notepad",
            "notepad++.exe": "Notepad++", "WindowsTerminal.exe": "Terminal",
            "wt.exe": "Terminal", "cmd.exe": "CMD",
            "powershell.exe": "PowerShell", "python.exe": "Python",
            "pythonw.exe": "Python", "pycharm64.exe": "PyCharm",
            "idea64.exe": "IntelliJ", "webstorm64.exe": "WebStorm",
            "postman.exe": "Postman", "slack.exe": "Slack",
            "discord.exe": "Discord", "Obsidian.exe": "Obsidian",
            "figma.exe": "Figma", "Teams.exe": "Teams",
            "zoom.exe": "Zoom", "vlc.exe": "VLC",
            "blender.exe": "Blender", "devenv.exe": "Visual Studio",
        }
        return mapping.get(exe_name, exe_name.replace(".exe", "").replace(".EXE", ""))

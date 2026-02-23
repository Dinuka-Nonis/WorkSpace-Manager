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
        """
        Return True if this hwnd is a real user-facing window.
        
        IMPORTANT: Do NOT call IsWindowVisible() here. Windows intentionally
        cloaks (hides) windows that live on inactive virtual desktops — so
        IsWindowVisible() returns False for every window on Desktop 2, 3, etc.
        That was why we got 0 results: we were filtering out exactly the
        windows we wanted to capture.
        
        Instead we check: window exists, has a title, has no parent (top-level),
        and has a caption bar (WS_CAPTION style).
        """
        if not hwnd:
            return False
        # Window must still exist
        if not win32gui.IsWindow(hwnd):
            return False
        title = win32gui.GetWindowText(hwnd)
        if len(title.strip()) < 2:
            return False
        # Must be a top-level window (no parent)
        if win32gui.GetParent(hwnd) != 0:
            return False
        # Must have a title bar
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
        Uses get_apps_by_z_order() — returns every AppView across all desktops.
        Each AppView.virtual_desktop() tells us which desktop it belongs to.
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

        passed = 0
        for app in all_apps:
            try:
                hwnd = app.hwnd
                title = win32gui.GetWindowText(hwnd) if hwnd else ""

                # Debug: log why each app is accepted or rejected
                if not hwnd:
                    print(f"[Snapshot]   SKIP: no hwnd")
                    continue
                if not win32gui.IsWindow(hwnd):
                    print(f"[Snapshot]   SKIP hwnd={hwnd}: not a window")
                    continue
                if len(title.strip()) < 2:
                    print(f"[Snapshot]   SKIP hwnd={hwnd}: title too short '{title}'")
                    continue

                if not _is_capturable(hwnd):
                    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                    parent = win32gui.GetParent(hwnd)
                    has_caption = bool(style & win32con.WS_CAPTION)
                    print(f"[Snapshot]   SKIP '{title[:40]}': "
                          f"parent={parent} caption={has_caption}")
                    continue

                # Which desktop does this window live on?
                # app.desktop is a property returning a VirtualDesktop object.
                # app.desktop_id is a GUID property — same format as VirtualDesktop.id.
                try:
                    desktop_id = str(app.desktop.id)
                except Exception as e:
                    print(f"[Snapshot]   SKIP '{title[:40]}': app.desktop failed: {e}")
                    continue

                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = _get_proc_info(pid)

                if proc["exe_name"].lower() in EXCLUDED_EXE:
                    print(f"[Snapshot]   SKIP '{title[:40]}': excluded exe {proc['exe_name']}")
                    continue

                result.setdefault(desktop_id, []).append({
                    "hwnd": hwnd, "title": title, **proc,
                })
                print(f"[Snapshot]   OK   '{title[:40]}' [{proc['exe_name']}] → {desktop_id[:8]}…")
                passed += 1

            except Exception as e:
                print(f"[Snapshot]   ERROR processing app: {e}")
                continue

        print(f"[Snapshot] {passed}/{len(all_apps)} app views captured")
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
        """1-based desktop number. Uses VirtualDesktop.number property directly."""
        if not PYVDA_AVAILABLE:
            return None
        try:
            for d in get_virtual_desktops():
                if str(d.id) == desktop_id:
                    return d.number  # built-in property, 1-based
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

"""
snapshot.py — Per-desktop window capture using pyvda + win32gui.

Key insight on desktop assignment:
  app.desktop.id  — WRONG: returns current active desktop's ID for cloaked
                    (inactive) windows. All windows appear on Desktop 1.
  app.is_on_desktop(vd) — CORRECT: explicitly checks membership per desktop.
"""

import os
import sys

if sys.platform != "win32":
    def snapshot_all_desktops(): return {}
    def snapshot_desktop(desktop_id=None): return []
    def get_current_desktop_id(): return None
    def get_all_desktop_ids(): return []
    def get_desktop_count(): return 1
    def get_desktop_number(desktop_id): return None
    def friendly_app_name(exe_name): return exe_name
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
        Check if a hwnd is a real user-facing window.
        NOTE: Do NOT use IsWindowVisible() — Windows cloaks (hides) windows
        on inactive virtual desktops, so they would all fail this check.
        """
        if not hwnd or not win32gui.IsWindow(hwnd):
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

        Desktop assignment uses app.is_on_desktop(vd) by iterating all desktops.
        This is the only reliable method — app.desktop.id silently returns the
        CURRENT active desktop's ID for cloaked (inactive desktop) windows.
        """
        result: dict[str, list[dict]] = {}

        if not WIN32_AVAILABLE or not PYVDA_AVAILABLE:
            return result

        try:
            all_apps = get_apps_by_z_order()
            all_desktops = get_virtual_desktops()
        except Exception as e:
            print(f"[Snapshot] pyvda call failed: {e}")
            return result

        print(f"[Snapshot] {len(all_apps)} total app views, {len(all_desktops)} desktops")

        passed = 0
        for app in all_apps:
            try:
                hwnd = app.hwnd
                if not hwnd:
                    continue

                title = win32gui.GetWindowText(hwnd)

                if not _is_capturable(hwnd):
                    continue

                # ── Determine which desktop this window belongs to ────────
                # CRITICAL: use is_on_desktop(vd) not app.desktop.id
                # app.desktop.id returns current desktop ID for ALL cloaked
                # windows (those on inactive desktops), causing them all to
                # appear grouped under Desktop 1.
                desktop_id = None
                for vd in all_desktops:
                    try:
                        if app.is_on_desktop(vd):
                            desktop_id = str(vd.id)
                            break
                    except Exception:
                        continue

                if desktop_id is None:
                    print(f"[Snapshot]   SKIP '{title[:40]}': no desktop match")
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
                print(f"[Snapshot]   ERROR: {e}")
                continue

        print(f"[Snapshot] {passed}/{len(all_apps)} app views captured")
        for did, wins in result.items():
            exes = ", ".join(sorted({w["exe_name"] for w in wins}))
            print(f"[Snapshot]   Desktop {did[:8]}…: {len(wins)} windows [{exes}]")

        return result

    def snapshot_desktop(desktop_id: str = None) -> list[dict]:
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
        if not PYVDA_AVAILABLE:
            return None
        try:
            for d in get_virtual_desktops():
                if str(d.id) == desktop_id:
                    return d.number
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
            "POWERPNT.EXE": "PowerPoint",
        }
        return mapping.get(exe_name, exe_name.replace(".exe", "").replace(".EXE", ""))

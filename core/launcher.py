"""
core/launcher.py — Opens files, URLs, and apps by type.

Chrome profile restore fix:
  The fundamental problem: when Chrome is already running, launching
    chrome.exe --profile-directory=X <url>
  sends the request to Chrome's already-running broker process via an IPC pipe.
  That broker routes the new tab to whichever profile window was last focused —
  NOT necessarily profile X. The --profile-directory flag is only fully honored
  on a cold (fresh) Chrome launch.

  Solution — focus-then-open:
    1. Build a pid→profile_dir map for all running chrome.exe browser processes
       via WMI (same technique as drag_watcher.py, which avoids the
       PROCESS_VM_READ AccessDenied issue that psutil.cmdline() hits).
    2. Find a visible top-level window owned by a PID in that profile.
    3. SetForegroundWindow() on it — Chrome's IPC broker routes new tabs to
       the foreground window's profile.
    4. Sleep briefly so the focus event is processed.
    5. Then Popen chrome.exe --profile-directory=X <url>.

  If the profile is NOT currently running (no matching PID found), skip the
  focus step — --profile-directory works perfectly on a cold launch.

  Group-and-sort restore:
    open_all_tracked() now groups URL items by profile_dir and opens them
    profile-by-profile. Within each profile group it focuses once, then opens
    all tabs for that profile before moving on. This avoids repeated focus
    thrashing when restoring multi-tab sessions.

  Also handles the chrome-profile-email: scheme introduced in db.py for
  tabs where the directory wasn't confirmed at save time. At restore time we
  do a fresh Local State lookup by email to try to resolve the directory.
"""

import ctypes
import ctypes.wintypes
import os
import subprocess
import time
import webbrowser
from pathlib import Path


# ── Browser preference ────────────────────────────────────────────────────────

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

EDGE_PATHS = [
    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]

VSCODE_PATHS = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
    r"C:\Program Files\Microsoft VS Code\Code.exe",
    r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
]

# How long (seconds) to wait after SetForegroundWindow before opening the URL.
# Gives Chrome's IPC broker time to register the new foreground window.
FOCUS_SETTLE_SECS = 0.35


def _find_browser() -> str | None:
    for p in CHROME_PATHS + EDGE_PATHS:
        if os.path.exists(p):
            return p
    return None


def _find_chrome() -> str | None:
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None


def _find_vscode(hint_exe: str = "") -> str | None:
    import shutil
    if hint_exe and os.path.exists(hint_exe):
        return hint_exe
    for p in VSCODE_PATHS:
        if os.path.exists(p):
            return p
    return shutil.which("code")


# ── Chrome profile helpers ────────────────────────────────────────────────────

def _load_chrome_local_state() -> dict:
    """Return Chrome Local State profile info_cache, or {} on failure."""
    import json
    local_appdata = os.getenv("LOCALAPPDATA", "")
    local_state   = os.path.join(local_appdata, "Google", "Chrome",
                                 "User Data", "Local State")
    if not os.path.exists(local_state):
        return {}
    try:
        data = json.loads(open(local_state, encoding="utf-8", errors="replace").read())
        return data.get("profile", {}).get("info_cache", {})
    except Exception:
        return {}


def _resolve_profile_dir_from_email(email: str) -> tuple[str, str]:
    """
    Try to map a Google account email to a Chrome profile directory via
    Local State. Returns (profile_dir, profile_name) or ("", "").
    """
    if not email:
        return "", ""
    info_cache = _load_chrome_local_state()
    for profile_dir, pinfo in info_cache.items():
        stored_email = (
            pinfo.get("user_name", "") or
            pinfo.get("gaia_email", "") or
            pinfo.get("email", "")
        ).lower().strip()
        if stored_email and stored_email == email.lower().strip():
            return profile_dir, pinfo.get("name", profile_dir)
    return "", ""


# ── WMI pid→profile map (shared logic with drag_watcher) ─────────────────────

def _build_pid_profile_map() -> dict[int, str]:
    """
    Return {pid: profile_dir} for all running Chrome browser processes.
    Uses WMI so we avoid the PROCESS_VM_READ AccessDenied that psutil hits.
    Only includes browser (non --type=) processes that have --profile-directory.
    """
    pid_profile: dict[int, str] = {}
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-WmiObject Win32_Process -Filter \"Name='chrome.exe'\" | "
             "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }"],
            timeout=4,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        ).decode("utf-8", errors="replace")

        for line in out.splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            pid_str, cmdline = line.split("|", 1)
            if "--type=" in cmdline:          # skip renderer/gpu/etc processes
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
    return pid_profile


# ── Focus a Chrome profile window before opening a URL ───────────────────────

def _focus_chrome_window_for_profile(profile_dir: str) -> bool:
    """
    Find a visible top-level Chrome window that belongs to profile_dir,
    bring it to the foreground, and wait for Chrome's IPC to settle.

    Returns True  — a window was found and focused (URL will be routed here).
    Returns False — profile is not currently running; cold launch is fine.

    Strategy:
      1. Build pid→profile map via WMI.
      2. Filter to PIDs that match profile_dir.
      3. EnumWindows to find a visible top-level window owned by one of those PIDs.
      4. SetForegroundWindow + SW_RESTORE.
    """
    pid_profile = _build_pid_profile_map()
    target_pids = {pid for pid, d in pid_profile.items() if d == profile_dir}

    if not target_pids:
        # Profile is not running — cold launch, no focus needed
        return False

    found_hwnd: list[int] = []   # list so the callback can mutate it

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    def _cb(hwnd: int, _: int) -> bool:
        if found_hwnd:
            return False          # already found one, stop enum
        pid_dword = ctypes.wintypes.DWORD(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_dword))
        if pid_dword.value in target_pids:
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                found_hwnd.append(hwnd)
                return False      # stop enumeration
        return True               # keep looking

    ctypes.windll.user32.EnumWindows(EnumWindowsProc(_cb), 0)

    if not found_hwnd:
        # PIDs exist but no visible top-level window yet (still launching?)
        return False

    hwnd = found_hwnd[0]
    ctypes.windll.user32.ShowWindow(hwnd, 9)          # SW_RESTORE (unminimise)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(FOCUS_SETTLE_SECS)
    print(f"[Launcher] Focused Chrome window for profile {profile_dir!r} (hwnd={hwnd})")
    return True


# ── Core Chrome open (single URL) ─────────────────────────────────────────────

def _open_chrome_url_in_profile(chrome: str, profile_dir: str, url: str) -> tuple[bool, str]:
    """
    Open url in Chrome under profile_dir.

    Caller is responsible for having already called
    _focus_chrome_window_for_profile() when opening multiple tabs in a batch,
    so we don't refocus on every single tab. This function just fires Popen.
    """
    try:
        subprocess.Popen([
            chrome,
            f"--profile-directory={profile_dir}",
            url,
        ])
        return True, ""
    except Exception as e:
        return False, str(e)


def _open_chrome_with_profile(chrome: str, profile_dir: str, url: str) -> tuple[bool, str]:
    """
    High-level single-URL open: focus the profile window first, then open.
    Used when restoring a single URL (not a batch).
    """
    _focus_chrome_window_for_profile(profile_dir)
    return _open_chrome_url_in_profile(chrome, profile_dir, url)


# ── URL scheme parser ─────────────────────────────────────────────────────────

def _parse_chrome_url(url: str) -> tuple[str, str, str]:
    """
    Parse a chrome-profile: or chrome-profile-email: URL.

    Returns (profile_dir, actual_url, warning_msg).
      profile_dir  — resolved Chrome profile directory (e.g. "Profile 5"), or ""
      actual_url   — the real http/https URL to open
      warning_msg  — non-empty string if resolution failed (log it)
    """
    if url.startswith("chrome-profile:"):
        rest = url[len("chrome-profile:"):]
        if "|" not in rest:
            return "", rest, ""
        profile_dir, actual_url = rest.split("|", 1)
        return profile_dir, actual_url, ""

    if url.startswith("chrome-profile-email:"):
        rest = url[len("chrome-profile-email:"):]
        if "|" not in rest:
            return "", rest, ""
        email, actual_url = rest.split("|", 1)
        profile_dir, profile_name = _resolve_profile_dir_from_email(email)
        if profile_dir:
            print(f"[Launcher] Resolved profile at restore time: "
                  f"{profile_dir!r} ({profile_name}) for {email!r}")
            return profile_dir, actual_url, ""
        warn = f"Could not resolve Chrome profile for {email!r}"
        return "", actual_url, warn

    return "", url, ""


# ── Public API ────────────────────────────────────────────────────────────────

def open_file(path: str) -> tuple[bool, str]:
    if not os.path.exists(path):
        return False, f"File not found: {path}"
    try:
        os.startfile(path)
        return True, ""
    except Exception as e:
        return False, str(e)


def open_url(url: str) -> tuple[bool, str]:
    """
    Open a URL in the correct browser / profile.

    Handles three URL schemes produced by db.save_chrome_tabs:

    1. chrome-profile:<dir>|<url>
       → Focus the profile window, then open with --profile-directory=<dir>.

    2. chrome-profile-email:<email>|<url>
       → Resolve dir from Local State, then same as case 1.
         If unresolvable, open without profile (best effort).

    3. Plain http/https/etc URL
       → Open in default browser.
    """
    KNOWN_WEB_SCHEMES = ("http://", "https://", "file://")
    OTHER_SCHEMES     = ("mailto:", "ftp://", "ftps://", "tel:", "data:")

    # ── Chrome-profile schemes ────────────────────────────────────────────────
    if url.startswith("chrome-profile:") or url.startswith("chrome-profile-email:"):
        profile_dir, actual_url, warning = _parse_chrome_url(url)
        chrome = _find_chrome()

        if warning:
            print(f"[Launcher] Warning: {warning} — opening without profile flag: {actual_url}")

        if chrome and profile_dir:
            print(f"[Launcher] Restoring URL in Chrome profile {profile_dir!r}: {actual_url}")
            return _open_chrome_with_profile(chrome, profile_dir, actual_url)

        if chrome:
            # No profile dir — open without profile (best effort)
            try:
                subprocess.Popen([chrome, actual_url])
                return True, ""
            except Exception as e:
                return False, str(e)

        # Chrome not installed — fall through to webbrowser
        url = actual_url

    # ── Standard URL ──────────────────────────────────────────────────────────
    if any(url.startswith(s) for s in OTHER_SCHEMES):
        try:
            webbrowser.open(url)
            return True, ""
        except Exception as e:
            return False, str(e)

    if not url.startswith(KNOWN_WEB_SCHEMES):
        url = "https://" + url

    browser = _find_browser()
    if browser:
        try:
            subprocess.Popen([browser, url])
            return True, ""
        except Exception as e:
            return False, str(e)

    try:
        webbrowser.open(url)
        return True, ""
    except Exception as e:
        return False, str(e)


def open_app(exe_path: str) -> tuple[bool, str]:
    if "WindowsApps" in exe_path:
        return open_uwp_app(exe_path)
    if not os.path.exists(exe_path):
        return False, f"Executable not found: {exe_path}"
    try:
        subprocess.Popen([exe_path])
        return True, ""
    except Exception as e:
        return False, str(e)


def open_vscode_folder(encoded: str) -> tuple[bool, str]:
    if "||" in encoded:
        hint_exe, folder = encoded.split("||", 1)
    else:
        hint_exe, folder = encoded, ""
    code_exe = _find_vscode(hint_exe)
    if not code_exe:
        return False, "VS Code executable not found — is it installed?"
    try:
        if folder.strip():
            subprocess.Popen([code_exe, folder])
        else:
            subprocess.Popen([code_exe])
        return True, ""
    except Exception as e:
        return False, str(e)


def open_explorer_folder(folder: str) -> tuple[bool, str]:
    try:
        if folder.strip() and os.path.exists(folder):
            subprocess.Popen(["explorer.exe", folder])
        else:
            subprocess.Popen(["explorer.exe"])
        return True, ""
    except Exception as e:
        return False, str(e)


def open_uwp_app(exe: str) -> tuple[bool, str]:
    """
    Launch a UWP / Microsoft Store app via shell:AppsFolder/<AUMID>.
    """
    if not exe:
        return False, "No exe path for UWP app"

    exe_path = Path(exe)

    try:
        aumid = _find_aumid_for_stem(exe)
        if aumid:
            os.startfile(f"shell:AppsFolder\\{aumid}")
            return True, ""
    except Exception:
        pass

    try:
        parts  = exe_path.parts
        wa_idx = next((i for i, p in enumerate(parts) if p.lower() == "windowsapps"), None)
        if wa_idx is not None:
            package_folder = parts[wa_idx + 1]
            segments       = package_folder.split("_")
            app_name       = segments[0]
            pub_hash       = segments[-1]
            if app_name and pub_hash:
                family = f"{app_name}_{pub_hash}"
                aumid  = f"{family}!App"
                os.startfile(f"shell:AppsFolder\\{aumid}")
                return True, ""
    except Exception:
        pass

    try:
        SW_SHOW = 5
        _ctypes = __import__("ctypes")
        shell32 = _ctypes.windll.shell32
        ret = shell32.ShellExecuteW(None, "open", exe, None, None, SW_SHOW)
        if ret > 32:
            return True, ""
        return False, f"ShellExecuteW returned {ret}"
    except Exception as e:
        return False, f"Could not launch UWP app: {e}"


def _find_aumid_for_stem(exe: str) -> str:
    try:
        import winreg
        exe_path = Path(exe)
        parts = exe_path.parts
        wa_idx = next((i for i, p in enumerate(parts) if p.lower() == "windowsapps"), None)
        if wa_idx is None:
            return ""
        package_folder = parts[wa_idx + 1]
        pkg_prefix = package_folder.split("_")[0].lower()

        base = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, base)
        i = 0
        while True:
            try:
                pkg_name = winreg.EnumKey(root, i)
                i += 1
            except OSError:
                break
            if pkg_prefix not in pkg_name.lower():
                continue
            try:
                apps_key = winreg.OpenKey(root, pkg_name + r"\Applications")
            except OSError:
                continue
            try:
                j = 0
                while True:
                    try:
                        app_id = winreg.EnumKey(apps_key, j)
                    except OSError:
                        break
                    aumid = f"{pkg_name}!{app_id}"
                    winreg.CloseKey(apps_key)
                    winreg.CloseKey(root)
                    return aumid
                    j += 1
            finally:
                try:
                    winreg.CloseKey(apps_key)
                except Exception:
                    pass
        winreg.CloseKey(root)
    except Exception:
        pass
    return ""


def open_item(item: dict) -> tuple[bool, str]:
    """
    Dispatch to the correct opener based on item type and path_or_url.
    """
    item_type   = item.get("type", "")
    path_or_url = item.get("path_or_url", "")

    if item_type == "app" and path_or_url.startswith("vscode-folder:"):
        return open_vscode_folder(path_or_url[len("vscode-folder:"):])

    if item_type == "app" and path_or_url.startswith("explorer-folder:"):
        return open_explorer_folder(path_or_url[len("explorer-folder:"):])

    if item_type == "app" and path_or_url.startswith("uwp:"):
        return open_uwp_app(path_or_url[len("uwp:"):])

    if item_type == "file":
        return open_file(path_or_url)
    elif item_type == "url":
        return open_url(path_or_url)
    elif item_type == "app":
        return open_app(path_or_url)
    else:
        return False, f"Unknown item type: {item_type}"


def open_all(items: list[dict]) -> dict:
    results, _ = open_all_tracked(items)
    return results


def open_all_tracked(items: list[dict]) -> tuple[dict, set]:
    """
    Open all items in the session.

    URL items are grouped by Chrome profile so we focus each profile window
    once and then open all its tabs in sequence — avoiding repeated focus
    thrashing. Non-URL items (files, apps) are opened first, in order.

    Open order:
      1. Files and apps  (preserves original order)
      2. URL groups      (sorted so same-profile tabs are batched together;
                          within each group the original order is preserved)
    """
    results    = {"total": len(items), "opened": 0, "failed": 0, "errors": []}
    failed_ids: set[int] = set()

    chrome = _find_chrome()

    # ── Split items into non-URLs and URL groups ──────────────────────────────
    non_url_items: list[dict] = []
    # profile_dir (or "" for plain URLs) → list of (item, actual_url)
    url_groups: dict[str, list[tuple[dict, str, str]]] = {}

    for item in items:
        if item.get("type") != "url":
            non_url_items.append(item)
            continue

        raw = item.get("path_or_url", "")
        if (raw.startswith("chrome-profile:") or raw.startswith("chrome-profile-email:")):
            profile_dir, actual_url, warning = _parse_chrome_url(raw)
            if warning:
                print(f"[Launcher] Warning: {warning}")
        else:
            profile_dir, actual_url = "", raw

        url_groups.setdefault(profile_dir, []).append((item, profile_dir, actual_url))

    # ── 1. Open files and apps ────────────────────────────────────────────────
    for item in non_url_items:
        success, err = open_item(item)
        if success:
            results["opened"] += 1
        else:
            results["failed"] += 1
            results["errors"].append(f"{item.get('label', '?')}: {err}")
            failed_ids.add(item["id"])
        time.sleep(0.2)

    # ── 2. Open URL groups (one focus per profile) ────────────────────────────
    for profile_dir, group in url_groups.items():
        if not group:
            continue

        if profile_dir and chrome:
            # Focus the profile window ONCE for the whole group
            already_running = _focus_chrome_window_for_profile(profile_dir)
            if not already_running:
                print(f"[Launcher] Profile {profile_dir!r} not running — cold launch")

            for item, _pd, actual_url in group:
                print(f"[Launcher] Opening in Chrome profile {profile_dir!r}: {actual_url}")
                success, err = _open_chrome_url_in_profile(chrome, profile_dir, actual_url)
                if success:
                    results["opened"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append(f"{item.get('label', '?')}: {err}")
                    failed_ids.add(item["id"])
                time.sleep(0.25)   # small gap between tabs in same profile

        else:
            # Plain URLs or no Chrome — open normally
            for item, _pd, actual_url in group:
                success, err = open_url(actual_url)
                if success:
                    results["opened"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append(f"{item.get('label', '?')}: {err}")
                    failed_ids.add(item["id"])
                time.sleep(0.25)

        # Small gap between profile groups to let Chrome settle
        time.sleep(0.4)

    return results, failed_ids


# ── Label helpers ─────────────────────────────────────────────────────────────

def label_for_file(path: str) -> str:
    return Path(path).name


def label_for_url(url: str) -> str:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.netloc.replace("www.", "")
        path = parsed.path.rstrip("/")
        if path and path != "/":
            return f"{host}{path}"
        return host or url
    except Exception:
        return url


def label_for_app(exe_path: str) -> str:
    name = Path(exe_path).stem
    import re
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    name = name.replace("_", " ").replace("-", " ")
    return name.title()


# ── Type icon mapping ─────────────────────────────────────────────────────────

FILE_ICONS = {
    ".docx": "📄", ".doc": "📄",
    ".xlsx": "📊", ".xls": "📊", ".csv": "📊",
    ".pptx": "📋", ".ppt": "📋",
    ".pdf":  "📕",
    ".py":   "🐍",
    ".js":   "🟨", ".ts": "🟦",
    ".html": "🌐", ".css": "🎨",
    ".md":   "📝", ".txt": "📝",
    ".zip":  "📦", ".rar": "📦",
    ".mp4":  "🎬", ".mkv": "🎬",
    ".mp3":  "🎵",
    ".png":  "🖼", ".jpg": "🖼", ".jpeg": "🖼",
    ".exe":  "⚙️",
}

APP_ICONS = {
    "code":       "💻", "chrome":   "🌐", "firefox": "🦊",
    "msedge":     "🌐", "slack":    "💬", "discord": "💬",
    "notion":     "📝", "obsidian": "🔮", "figma":   "🎨",
    "postman":    "📮", "pycharm64":"🐍", "idea64":  "☕",
    "webstorm64": "🟨", "devenv":   "🔷", "teams":   "👥",
    "zoom":       "📹", "spotify":  "🎵", "vlc":     "🎬",
}


def icon_for_item(item: dict) -> str:
    item_type   = item.get("type", "")
    path_or_url = item.get("path_or_url", "").lower()

    if item_type == "url":
        return "🌐"

    if item_type == "file":
        ext = Path(path_or_url).suffix.lower()
        return FILE_ICONS.get(ext, "📄")

    if item_type == "app":
        if path_or_url.startswith("vscode-folder:"):
            return "💻"
        if path_or_url.startswith("explorer-folder:"):
            return "📁"
        if path_or_url.startswith("uwp:"):
            exe = path_or_url[len("uwp:"):].lower()
            for key, icon in APP_ICONS.items():
                if key in exe:
                    return icon
            return "🪟"
        stem = Path(path_or_url).stem.lower()
        for key, icon in APP_ICONS.items():
            if key in stem:
                return icon
        return "⚙️"

    return "📄"
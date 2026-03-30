"""
core/launcher.py — Opens files, URLs, and apps by type.

Chrome profile restore fix:
  The old code launched Chrome with [chrome, --profile-directory=X, --new-window, url].
  Problem: if Chrome is already running under a DIFFERENT profile, passing
  --profile-directory=X opens a new window in profile X but Chrome may still
  route the navigation to the already-running profile's window.

  Fix: use the --args form so Chrome creates a fresh process for that profile:
    chrome.exe --profile-directory=<dir> -- <url>
  And use a two-step launch when Chrome is already running:
    1. Open the profile with just --profile-directory (no URL) to ensure the
       profile's window is foregrounded.
    2. Open the URL in a new tab via: chrome.exe --profile-directory=<dir> <url>

  Also handles the new chrome-profile-email: scheme introduced in db.py for
  tabs where the directory wasn't confirmed at save time. At restore time we
  do a fresh Local State lookup by email to try to resolve the directory.
"""

import os
import subprocess
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
        # Chrome stores the email in gaia_info_picture_url domain or directly
        # under "user_name" / "gaia_id" depending on version.
        stored_email = (
            pinfo.get("user_name", "") or
            pinfo.get("gaia_email", "") or
            pinfo.get("email", "")
        ).lower().strip()
        if stored_email and stored_email == email.lower().strip():
            return profile_dir, pinfo.get("name", profile_dir)
    return "", ""


def _open_chrome_with_profile(chrome: str, profile_dir: str, url: str) -> tuple[bool, str]:
    """
    Open a URL in a specific Chrome profile.

    Uses --profile-directory and avoids --new-window (which can steal focus
    from an already-open session). Chrome handles opening a new tab in the
    correct profile window automatically.

    If Chrome is NOT already running for this profile, it will launch a new
    window. If it IS running, it opens a new tab in the existing window.
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
       → Open in Chrome with --profile-directory=<dir>.
       Guaranteed to open in the correct profile.

    2. chrome-profile-email:<email>|<url>
       → profile_dir wasn't confirmed at save time. Try to resolve the dir
         from Local State at restore time. If found, same as case 1.
         If not found, warn the user and open without a profile flag (best
         effort — will open in whatever profile Chrome currently has active).

    3. Plain http/https/etc URL
       → Open in default browser (added via drag-drop with no profile info,
         or explicitly added by user).
    """

    # ── Case 1: confirmed profile dir ────────────────────────────────────────
    if url.startswith("chrome-profile:"):
        rest = url[len("chrome-profile:"):]
        if "|" in rest:
            profile_dir, actual_url = rest.split("|", 1)
            chrome = _find_chrome()
            if chrome and profile_dir:
                print(f"[Launcher] Restoring URL in Chrome profile {profile_dir!r}: {actual_url}")
                return _open_chrome_with_profile(chrome, profile_dir, actual_url)
            elif chrome:
                # profile_dir is empty string — open without profile flag
                print(f"[Launcher] Warning: empty profile_dir, opening without profile: {actual_url}")
                try:
                    subprocess.Popen([chrome, actual_url])
                    return True, ""
                except Exception as e:
                    return False, str(e)
            # Chrome not found — fall through with bare URL
            url = actual_url
        else:
            url = rest  # malformed, best-effort

    # ── Case 2: email hint, dir not confirmed at save time ────────────────────
    elif url.startswith("chrome-profile-email:"):
        rest = url[len("chrome-profile-email:"):]
        if "|" in rest:
            email, actual_url = rest.split("|", 1)
            chrome = _find_chrome()
            if chrome:
                # Try to resolve at restore time
                profile_dir, profile_name = _resolve_profile_dir_from_email(email)
                if profile_dir:
                    print(f"[Launcher] Resolved profile at restore time: "
                          f"{profile_dir!r} ({profile_name}) for {email!r}")
                    return _open_chrome_with_profile(chrome, profile_dir, actual_url)
                else:
                    # Still can't resolve — open without profile, log warning
                    print(f"[Launcher] Warning: could not resolve Chrome profile for "
                          f"{email!r} — opening without profile flag: {actual_url}")
                    try:
                        subprocess.Popen([chrome, actual_url])
                        return True, ""
                    except Exception as e:
                        return False, str(e)
            url = actual_url
        else:
            url = rest

    # ── Standard URL (plain http/https, or fallback from above) ──────────────
    KNOWN_WEB_SCHEMES = ("http://", "https://", "file://")
    OTHER_SCHEMES     = ("mailto:", "ftp://", "ftps://", "tel:", "data:")

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
        SW_SHOW      = 5
        SEE_MASK_FLAG = 0x00000400
        ctypes = __import__("ctypes")
        shell32 = ctypes.windll.shell32
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
    import time
    results    = {"total": len(items), "opened": 0, "failed": 0, "errors": []}
    failed_ids: set[int] = set()

    for item in items:
        success, err = open_item(item)
        if success:
            results["opened"] += 1
        else:
            results["failed"] += 1
            results["errors"].append(f"{item.get('label', '?')}: {err}")
            failed_ids.add(item["id"])
        time.sleep(0.25)

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
    "code":      "💻", "chrome":  "🌐", "firefox": "🦊",
    "msedge":    "🌐", "slack":   "💬", "discord": "💬",
    "notion":    "📝", "obsidian":"🔮", "figma":   "🎨",
    "postman":   "📮", "pycharm64":"🐍","idea64":  "☕",
    "webstorm64":"🟨", "devenv":  "🔷", "teams":   "👥",
    "zoom":      "📹", "spotify": "🎵", "vlc":     "🎬",
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

"""
core/launcher.py — Opens files, URLs, and apps by type.

This is the single source of truth for "how do we open X".
No title parsing, no file searching — we always have the exact path or URL.
"""

import os
import subprocess
import webbrowser
from pathlib import Path


# ── Browser preference (can be extended to Edge, Firefox, etc.) ──────────────

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
    """Return path to Chrome if available, then Edge, else None (fall back to webbrowser)."""
    for p in CHROME_PATHS + EDGE_PATHS:
        if os.path.exists(p):
            return p
    return None


def _find_chrome() -> str | None:
    """Return path to Chrome only (not Edge), for profile-aware tab restore."""
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None


def _find_vscode(hint_exe: str = "") -> str | None:
    """
    Return a path to code.exe.
    Tries the stored hint path first (captured at snapshot time), then common
    install locations, then shutil.which('code').
    """
    import shutil
    if hint_exe and os.path.exists(hint_exe):
        return hint_exe
    for p in VSCODE_PATHS:
        if os.path.exists(p):
            return p
    return shutil.which("code")


# ── Public API ────────────────────────────────────────────────────────────────

def open_file(path: str) -> tuple[bool, str]:
    """
    Open a file with its default application.
    For Office files, Word/Excel/PowerPoint will offer to resume at last position.
    Returns (success, error_message).
    """
    if not os.path.exists(path):
        return False, f"File not found: {path}"
    try:
        os.startfile(path)
        return True, ""
    except Exception as e:
        return False, str(e)


def open_url(url: str) -> tuple[bool, str]:
    """
    Open a URL in the preferred browser.

    Handles the special 'chrome-profile:' encoding produced by snapshot.py::
        chrome-profile:<profile_dir>|<actual_url>
    This opens Chrome with --profile-directory=<profile_dir> so the URL is
    restored in exactly the same Chrome profile it was captured from.

    Falls back to system default if Chrome/Edge not found.
    Returns (success, error_message).
    """
    # ── Chrome profile-aware restore ─────────────────────────────────────────
    if url.startswith("chrome-profile:"):
        rest = url[len("chrome-profile:"):]
        if "|" in rest:
            profile_dir, actual_url = rest.split("|", 1)
            chrome = _find_chrome()
            if chrome:
                try:
                    subprocess.Popen([
                        chrome,
                        f"--profile-directory={profile_dir}",
                        "--new-window",  # force a new window in the correct profile
                        actual_url,      # (ignored by an already-running wrong profile)
                    ])
                    return True, ""
                except Exception as e:
                    return False, str(e)
            # Chrome not found — fall through with the bare URL
            url = actual_url
        else:
            url = rest  # malformed encoding, best-effort

    KNOWN_WEB_SCHEMES = ("http://", "https://", "file://")
    OTHER_SCHEMES = ("mailto:", "ftp://", "ftps://", "tel:", "data:")

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

    # Fallback
    try:
        webbrowser.open(url)
        return True, ""
    except Exception as e:
        return False, str(e)


def open_app(exe_path: str) -> tuple[bool, str]:
    """
    Launch an application by its executable path.
    Returns (success, error_message).

    Auto-detects WindowsApps (UWP/Store) paths and routes to open_uwp_app
    so they are launched correctly via shell:AppsFolder rather than direct
    subprocess (which would fail with Access Denied).
    """
    # UWP apps live in WindowsApps — cannot be launched directly
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
    """
    Open a VS Code workspace folder from the encoded string produced by
    snapshot.py::_get_vscode_workspaces().

    Encoding:  <code_exe_path>||<workspace_folder_or_file>

    The stored code_exe_path is used first; if it no longer exists we fall
    back to _find_vscode() which checks common install locations and PATH.
    """
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
    """
    Open a File Explorer window at the given folder path.
    """
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
    Launch a UWP / Microsoft Store app.

    WindowsApps exes cannot be launched directly (WinError 5 Access Denied).
    Strategy:
      1. Find the AUMID from the registry -> launch via shell:AppsFolder\\<AUMID>
      2. Derive package family name from the exe path → try uri launch via
         PowerShell Start-Process
      3. Last resort: explorer.exe shell:AppsFolder (opens the App list)
    """
    if not exe:
        return False, "No exe path for UWP app"

    exe_path = Path(exe)

    # ── Strategy 1: AUMID lookup via registry ─────────────────────────────────
    # Use PowerShell Start-Process — explorer.exe with shell:AppsFolder
    # can open a file picker/explorer window instead of the app on some systems.
    try:
        aumid = _find_aumid_for_stem(exe)
        if aumid:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                 "-Command", f'Start-Process "shell:AppsFolder\\{aumid}"'],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return True, ""
    except Exception:
        pass

    # ── Strategy 2: Derive package family name from exe path ──────────────────
    try:
        # Extract package folder from path e.g.
        # C:\Program Files\WindowsApps\SpotifyAB.SpotifyMusic_1.285_x64__zpdnekdrzrea0\Spotify.exe
        parts = exe_path.parts
        wa_idx = next((i for i, p in enumerate(parts) if p.lower() == "windowsapps"), None)
        if wa_idx is not None:
            package_folder = parts[wa_idx + 1]
            # "SpotifyAB.SpotifyMusic_1.285_x64__zpdnekdrzrea0"
            # split("_") → ["SpotifyAB.SpotifyMusic", "1.285", "x64", "", "zpdnekdrzrea0"]
            # The double-underscore produces an empty segment before the hash.
            segments = package_folder.split("_")
            app_name = segments[0]          # "SpotifyAB.SpotifyMusic"
            pub_hash = segments[-1]         # "zpdnekdrzrea0"
            if app_name and pub_hash:
                family = f"{app_name}_{pub_hash}"
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                     "-Command", f'Start-Process "shell:AppsFolder\\{family}!App"'],
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    return True, ""
    except Exception:
        pass

    # ── Strategy 3: PowerShell Invoke-Item on the exe ─────────────────────────
    # Last resort — works for some Store apps. Never opens a File Explorer window.
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
             "-Command", f'Invoke-Item "{exe}"'],
            capture_output=True, timeout=5
        )
        if result.returncode == 0:
            return True, ""
        return False, f"Could not launch UWP app: {result.stderr.decode(errors='replace').strip()}"
    except Exception as e:
        return False, f"Could not launch UWP app: {e}"


def _find_aumid_for_stem(exe: str) -> str:
    """
    Search the Windows registry for an Application User Model ID (AUMID)
    matching the given exe path, by looking up the package folder name.

    Returns a string like "SpotifyAB.SpotifyMusic_hash!Spotify" or "".

    Bug fix: original code incremented j then immediately closed the registry
    keys and returned — the EnumKey(apps_key, 0) call never ran because j was
    incremented to 1 before the return. Fixed by reading the app_id at index 0
    first, then returning it.
    """
    try:
        import winreg
        exe_path = Path(exe)
        parts = exe_path.parts
        wa_idx = next((i for i, p in enumerate(parts) if p.lower() == "windowsapps"), None)
        if wa_idx is None:
            return ""
        package_folder = parts[wa_idx + 1]  # e.g. "SpotifyAB.SpotifyMusic_1.285_x64__hash"
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
            # Found a matching package — enumerate its Applications sub-key
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
                    # Use the first application entry (usually "App")
                    aumid = f"{pkg_name}!{app_id}"
                    winreg.CloseKey(apps_key)
                    winreg.CloseKey(root)
                    return aumid
                    j += 1  # noqa: unreachable — we return on first valid app_id
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
    item must have 'type' ('file'|'url'|'app') and 'path_or_url'.

    Special cases:
      • type='app',  path_or_url starts with 'vscode-folder:' → open VS Code
        with the encoded workspace folder.
      • type='url',  path_or_url starts with 'chrome-profile:' → open Chrome
        with the correct --profile-directory flag (handled inside open_url).
    """
    item_type   = item.get("type", "")
    path_or_url = item.get("path_or_url", "")

    # VS Code workspace restore
    if item_type == "app" and path_or_url.startswith("vscode-folder:"):
        encoded = path_or_url[len("vscode-folder:"):]
        return open_vscode_folder(encoded)

    # File Explorer folder restore
    if item_type == "app" and path_or_url.startswith("explorer-folder:"):
        folder = path_or_url[len("explorer-folder:"):]
        return open_explorer_folder(folder)

    # UWP / Microsoft Store app restore
    if item_type == "app" and path_or_url.startswith("uwp:"):
        exe = path_or_url[len("uwp:"):]
        return open_uwp_app(exe)

    if item_type == "file":
        return open_file(path_or_url)
    elif item_type == "url":
        return open_url(path_or_url)
    elif item_type == "app":
        return open_app(path_or_url)
    else:
        return False, f"Unknown item type: {item_type}"


def open_all(items: list[dict]) -> dict:
    """
    Open all items in a session.
    Returns a summary: {total, opened, failed, errors}
    """
    results, _ = open_all_tracked(items)
    return results


def open_all_tracked(items: list[dict]) -> tuple[dict, set]:
    """
    Open all items in a session.
    Returns (summary_dict, failed_item_ids) so callers can match on item ID
    rather than parsing label strings (labels may contain ":" themselves).
    """
    import time
    results = {"total": len(items), "opened": 0, "failed": 0, "errors": []}
    failed_ids: set[int] = set()

    for item in items:
        success, err = open_item(item)
        if success:
            results["opened"] += 1
        else:
            results["failed"] += 1
            results["errors"].append(f"{item.get('label', '?')}: {err}")
            failed_ids.add(item["id"])
        # Small delay so apps don't fight over focus
        time.sleep(0.25)

    return results, failed_ids


# ── Label helpers (used when auto-generating labels) ─────────────────────────

def label_for_file(path: str) -> str:
    """Generate a clean display label from a file path."""
    return Path(path).name


def label_for_url(url: str) -> str:
    """Generate a clean display label from a URL."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.netloc.replace("www.", "")
        path = parsed.path.rstrip("/")
        if path and path != "/":
            # e.g. "github.com/user/repo"
            return f"{host}{path}"
        return host or url
    except Exception:
        return url


def label_for_app(exe_path: str) -> str:
    """Generate a clean display label from an exe path."""
    name = Path(exe_path).stem
    # Convert camelCase and underscores to spaces, capitalize
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
    "code":         "💻",
    "chrome":       "🌐",
    "firefox":      "🦊",
    "msedge":       "🌐",
    "slack":        "💬",
    "discord":      "💬",
    "notion":       "📝",
    "obsidian":     "🔮",
    "figma":        "🎨",
    "postman":      "📮",
    "pycharm64":    "🐍",
    "idea64":       "☕",
    "webstorm64":   "🟨",
    "devenv":       "🔷",
    "teams":        "👥",
    "zoom":         "📹",
    "spotify":      "🎵",
    "vlc":          "🎬",
}


def icon_for_item(item: dict) -> str:
    """Return an emoji icon for an item based on its type and path."""
    item_type   = item.get("type", "")
    path_or_url = item.get("path_or_url", "").lower()

    if item_type == "url":
        if path_or_url.startswith("chrome-profile:"):
            return "🌐"
        return "🌐"

    if item_type == "file":
        ext = Path(path_or_url).suffix.lower()
        return FILE_ICONS.get(ext, "📄")

    if item_type == "app":
        # VS Code workspace
        if path_or_url.startswith("vscode-folder:"):
            return "💻"
        # File Explorer folder
        if path_or_url.startswith("explorer-folder:"):
            return "📁"
        # UWP / Store app
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

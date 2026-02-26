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


def _find_browser() -> str | None:
    """Return path to Chrome if available, then Edge, else None (fall back to webbrowser)."""
    for p in CHROME_PATHS + EDGE_PATHS:
        if os.path.exists(p):
            return p
    return None


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
    Falls back to system default if Chrome/Edge not found.
    Returns (success, error_message).
    """
    if not url.startswith(("http://", "https://", "file://")):
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
    """
    if not os.path.exists(exe_path):
        return False, f"Executable not found: {exe_path}"
    try:
        subprocess.Popen([exe_path])
        return True, ""
    except Exception as e:
        return False, str(e)


def open_item(item: dict) -> tuple[bool, str]:
    """
    Dispatch to the correct opener based on item type.
    item must have 'type' ('file'|'url'|'app') and 'path_or_url'.
    """
    item_type   = item.get("type", "")
    path_or_url = item.get("path_or_url", "")

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
    import time
    results = {"total": len(items), "opened": 0, "failed": 0, "errors": []}

    for item in items:
        success, err = open_item(item)
        if success:
            results["opened"] += 1
        else:
            results["failed"] += 1
            results["errors"].append(f"{item.get('label', '?')}: {err}")
        # Small delay so apps don't fight over focus
        time.sleep(0.25)

    return results


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
        return "🌐"

    if item_type == "file":
        ext = Path(path_or_url).suffix.lower()
        return FILE_ICONS.get(ext, "📄")

    if item_type == "app":
        stem = Path(path_or_url).stem.lower()
        for key, icon in APP_ICONS.items():
            if key in stem:
                return icon
        return "⚙️"

    return "📄"
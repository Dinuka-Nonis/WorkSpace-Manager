"""
restore.py — Reopens all apps, Chrome tabs, and VS Code workspaces
             for a saved session.
"""

import os
import sys
import subprocess
import webbrowser
from pathlib import Path

import db
from snapshot import friendly_app_name


# ─── CHROME ──────────────────────────────────────────────────────────────────

def restore_chrome_tabs(session_id: int) -> int:
    """Open all saved Chrome tabs. Returns count opened."""
    tabs = db.get_chrome_tabs(session_id)
    if not tabs:
        return 0

    urls = [t["url"] for t in tabs if t.get("url") and
            not t["url"].startswith("chrome://") and
            not t["url"].startswith("about:")]

    if not urls:
        return 0

    # Try to open in Chrome specifically
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]

    chrome_exe = next((p for p in chrome_paths if os.path.exists(p)), None)

    if chrome_exe:
        try:
            # First URL opens Chrome, rest open as additional tabs
            subprocess.Popen([chrome_exe, "--new-window", urls[0]])
            import time; time.sleep(1.5)
            for url in urls[1:]:
                subprocess.Popen([chrome_exe, url])
                time.sleep(0.2)
            return len(urls)
        except Exception:
            pass

    # Fallback: system default browser
    for url in urls:
        webbrowser.open(url)
    return len(urls)


# ─── VS CODE ─────────────────────────────────────────────────────────────────

def restore_vscode_windows(windows: list[dict]) -> int:
    """Reopen VS Code windows with their last working directory."""
    code_windows = [w for w in windows if w.get("exe_name", "").lower() in ("code.exe",)]
    if not code_windows:
        return 0

    code_paths = [
        r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ]
    code_paths = [os.path.expandvars(p) for p in code_paths]
    code_exe = next((p for p in code_paths if os.path.exists(p)), "code")

    opened = 0
    for w in code_windows:
        title = w.get("title", "")
        # Title format: "filename — folder — Visual Studio Code"
        # Try to extract folder path from title
        parts = title.replace(" — Visual Studio Code", "").split(" — ")
        if len(parts) >= 2:
            folder_hint = parts[-1].strip()
            if os.path.isdir(folder_hint):
                try:
                    subprocess.Popen([code_exe, folder_hint])
                    opened += 1
                    continue
                except Exception:
                    pass

        # Just open VS Code without a folder
        try:
            subprocess.Popen([code_exe])
            opened += 1
        except Exception:
            pass

    return opened


# ─── PDF FILES ────────────────────────────────────────────────────────────────

def restore_pdf_files(windows: list[dict]) -> int:
    """Reopen PDF viewers with their files."""
    pdf_exes = {"acroRd32.exe", "acrobat.exe", "sumatrapdf.exe", "foxitreader.exe"}
    pdf_windows = [w for w in windows if w.get("exe_name", "").lower() in pdf_exes]
    opened = 0

    for w in pdf_windows:
        title = w.get("title", "")
        # Title usually starts with the filename
        # Try to find the file path from the title
        parts = title.split(" - ")
        if parts:
            filename = parts[0].strip()
            # Search common document folders
            search_dirs = [
                Path.home() / "Documents",
                Path.home() / "Downloads",
                Path.home() / "Desktop",
            ]
            for search_dir in search_dirs:
                matches = list(search_dir.rglob(f"*{filename}*.pdf"))
                if matches:
                    try:
                        os.startfile(str(matches[0]))
                        opened += 1
                        break
                    except Exception:
                        pass

    return opened


# ─── TERMINAL ────────────────────────────────────────────────────────────────

def restore_terminals(windows: list[dict]) -> int:
    """Reopen terminal windows."""
    term_exes = {
        "windowsterminal.exe": "wt",
        "cmd.exe": "cmd",
        "powershell.exe": "powershell",
    }
    terminal_windows = [w for w in windows
                        if w.get("exe_name", "").lower() in term_exes]
    opened = 0

    for w in terminal_windows:
        exe_lower = w.get("exe_name", "").lower()
        cmd = term_exes.get(exe_lower, "cmd")
        try:
            subprocess.Popen([cmd])
            opened += 1
        except Exception:
            pass

    return opened


# ─── GENERIC APPS ────────────────────────────────────────────────────────────

_SKIP_RESTORE_EXES = {
    "code.exe", "chrome.exe", "firefox.exe", "msedge.exe", "brave.exe",
    "acroRd32.exe", "acrobat.exe", "sumatrapdf.exe",
    "windowsterminal.exe", "cmd.exe", "powershell.exe",
    "explorer.exe",
}


def restore_other_apps(windows: list[dict]) -> int:
    """Reopen any other apps by exe path."""
    opened = 0
    seen_exes = set()

    for w in windows:
        exe_name = w.get("exe_name", "").lower()
        exe_path = w.get("exe_path", "")

        if exe_name in _SKIP_RESTORE_EXES:
            continue
        if exe_name in seen_exes:
            continue
        if not exe_path or not os.path.exists(exe_path):
            continue

        try:
            subprocess.Popen([exe_path])
            seen_exes.add(exe_name)
            opened += 1
        except Exception:
            pass

    return opened


# ─── DESKTOP CREATION ────────────────────────────────────────────────────────

def create_restore_desktop() -> str | None:
    """
    Create a brand-new virtual desktop, switch to it, and return its ID.
    All apps launched after this call will open on the new desktop.
    Returns None if pyvda is unavailable or creation fails.
    """
    try:
        import time
        from pyvda import VirtualDesktop, get_virtual_desktops
        VirtualDesktop.create()
        time.sleep(0.6)                    # let Windows register the new desktop
        desktops = get_virtual_desktops()
        new_desktop = desktops[-1]         # newest is always last
        new_desktop.go()                   # switch focus to it
        time.sleep(0.4)                    # let the switch complete
        return str(new_desktop.id)
    except Exception as e:
        print(f"[Restore] Could not create new desktop: {e}")
        return None


# ─── MAIN RESTORE ─────────────────────────────────────────────────────────────

def restore_session(session_id: int) -> dict:
    """
    Full session restore.
    1. Creates a new virtual desktop and switches to it.
    2. Launches all saved apps/tabs on the new desktop.
    3. Returns a summary dict of what was reopened.
    """
    # Step 1 — create a fresh desktop (apps launched below will open here)
    new_desktop_id = create_restore_desktop()

    # Step 2 — relaunch everything
    windows = db.get_windows(session_id)
    tabs_opened = restore_chrome_tabs(session_id)
    vscode_opened = restore_vscode_windows(windows)
    pdf_opened = restore_pdf_files(windows)
    terminal_opened = restore_terminals(windows)
    other_opened = restore_other_apps(windows)

    # Step 3 — mark session active and update its desktop ID
    db.update_session_status(session_id, "active")
    if new_desktop_id:
        import sqlite3
        from datetime import datetime
        # Update the desktop ID so the daemon tracks it correctly on the new desktop
        try:
            import db as _db
            with _db.get_conn() as conn:
                conn.execute(
                    "UPDATE sessions SET virtual_desktop_id=?, updated_at=? WHERE id=?",
                    (new_desktop_id, datetime.now().isoformat(), session_id)
                )
        except Exception as e:
            print(f"[Restore] Could not update desktop ID: {e}")

    return {
        "new_desktop": new_desktop_id is not None,
        "tabs": tabs_opened,
        "vscode": vscode_opened,
        "pdfs": pdf_opened,
        "terminals": terminal_opened,
        "other": other_opened,
        "total": tabs_opened + vscode_opened + pdf_opened + terminal_opened + other_opened,
    }


def get_restore_preview(session_id: int) -> list[str]:
    """Return human-readable list of what will be restored."""
    windows = db.get_windows(session_id)
    tabs = db.get_chrome_tabs(session_id)

    items = []
    if tabs:
        items.append(f"🌐 {len(tabs)} Chrome tab{'s' if len(tabs) != 1 else ''}")

    app_counts: dict[str, int] = {}
    for w in windows:
        name = friendly_app_name(w.get("exe_name", ""))
        if name and name.lower() not in ("explorer", "dwm"):
            app_counts[name] = app_counts.get(name, 0) + 1

    for app, count in sorted(app_counts.items(), key=lambda x: -x[1]):
        if count > 1:
            items.append(f"🪟 {app} ({count} windows)")
        else:
            items.append(f"🪟 {app}")

    return items

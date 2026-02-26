"""
restore.py — Reopens all apps, Chrome tabs, and documents for a saved session.
"""

import os
import sys
import re
import subprocess
import webbrowser
from pathlib import Path

import db
from snapshot import friendly_app_name


# ─── FILE SEARCH HELPERS ──────────────────────────────────────────────────────

def _find_office_file(filename: str, extensions: list[str]) -> str | None:
    """
    Search for an Office document by filename.
    Strategy:
      1. Windows Recent files list (fastest, most reliable)
      2. Common user folders (Documents, Desktop, Downloads, OneDrive)
    Returns the full path string if found, else None.
    """
    import glob

    # 1. Check Windows Recent Files — these are .lnk shortcuts pointing to real files
    recent_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent"
    if recent_dir.exists():
        # The .lnk name usually matches the document name
        stem = Path(filename).stem
        for lnk in recent_dir.glob(f"{stem}*.lnk"):
            try:
                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")
                target = shell.CreateShortcut(str(lnk)).Targetpath
                if target and os.path.exists(target):
                    print(f"[Restore]   Found via Recent: {target}")
                    return target
            except Exception:
                pass

    # 2. Search common folders recursively (depth-limited for speed)
    search_roots = [
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path.home() / "Downloads",
        Path.home() / "OneDrive",
        Path.home() / "OneDrive - Documents",
    ]
    # Also add any drive roots that exist (D:\, E:\, etc.)
    for drive_letter in "CDEFGH":
        p = Path(f"{drive_letter}:\\")
        if p.exists():
            search_roots.append(p / "Users" / os.environ.get("USERNAME", "") / "Documents")

    stem = Path(filename).stem.lower()
    for root in search_roots:
        if not root.exists():
            continue
        try:
            for ext in extensions:
                # rglob but stop at depth 6 to avoid crawling the entire drive
                for match in root.rglob(f"*{stem}*{ext}"):
                    if match.is_file():
                        print(f"[Restore]   Found via search: {match}")
                        return str(match)
        except (PermissionError, OSError):
            continue

    return None


def _extract_office_filename(title: str, extensions: list[str]) -> str | None:
    """
    Extract the document filename from a window title.
    Handles all Office title formats:
      "Member_B_DevLead_Sprint1.docx  -  Last saved ..."
      "Software Requirements Specification.docx"
      "LLM_Canvas_SRS.docx - Word"
      "Educap_Template.pptx  -  Repaired - PowerPoint"
      "Book1.xlsx - Excel"
    """
    title = title.strip()
    for ext in extensions:
        # Find the extension in the title (case-insensitive)
        idx = title.lower().find(ext.lower())
        if idx != -1:
            # Include everything up to and including the extension
            raw = title[:idx + len(ext)]
            # Strip any leading path separators or spaces
            filename = raw.strip().lstrip(r"\/").strip()
            # Take only the final filename component if it has path separators
            filename = os.path.basename(filename)
            if filename:
                return filename
    return None


# ─── OFFICE DOCUMENT RESTORE ─────────────────────────────────────────────────

# Maps exe name → (search extensions, executable paths to try)
OFFICE_APPS = {
    "winword.exe": {
        "extensions": [".docx", ".doc", ".docm", ".rtf"],
        "exe_paths": [
            r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
            r"C:\Program Files\Microsoft Office\Office16\WINWORD.EXE",
        ],
    },
    "excel.exe": {
        "extensions": [".xlsx", ".xls", ".xlsm", ".csv"],
        "exe_paths": [
            r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE",
        ],
    },
    "powerpnt.exe": {
        "extensions": [".pptx", ".ppt", ".pptm"],
        "exe_paths": [
            r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE",
        ],
    },
}


def restore_office_documents(windows: list[dict]) -> int:
    """
    Restore Microsoft Office documents (Word, Excel, PowerPoint).
    
    Key fixes over old approach:
    1. Extracts actual filename from window title
    2. Searches Windows Recent files + common folders for the actual file path
    3. Opens EACH document separately (old code deduped by exe → only 1 opened)
    4. Uses os.startfile() as primary method (respects Windows file associations)
    """
    import time

    office_windows = [
        w for w in windows
        if w.get("exe_name", "").lower() in OFFICE_APPS
    ]

    if not office_windows:
        return 0

    opened = 0
    opened_paths = set()  # deduplicate by FILE PATH not by exe name

    for w in office_windows:
        exe_lower = w.get("exe_name", "").lower()
        title = w.get("title", "")
        app_info = OFFICE_APPS.get(exe_lower, {})
        extensions = app_info.get("extensions", [])

        print(f"[Restore] Office window: '{title[:60]}'")

        # Step 1: Extract filename from title
        filename = _extract_office_filename(title, extensions)
        if not filename:
            print(f"[Restore]   Could not extract filename from title, skipping")
            continue

        print(f"[Restore]   Extracted filename: {filename}")

        # Step 2: Find the actual file on disk
        file_path = _find_office_file(filename, extensions)

        if file_path and file_path not in opened_paths:
            try:
                os.startfile(file_path)  # opens with default app (respects association)
                opened_paths.add(file_path)
                opened += 1
                print(f"[Restore]   Opened: {file_path}")
                time.sleep(0.5)  # give Office time to load each doc
            except Exception as e:
                print(f"[Restore]   startfile failed ({e}), trying subprocess")
                # Fallback: find the Office exe and open directly
                exe_candidates = app_info.get("exe_paths", [])
                office_exe = next((p for p in exe_candidates if os.path.exists(p)), None)
                if office_exe:
                    try:
                        subprocess.Popen([office_exe, file_path])
                        opened_paths.add(file_path)
                        opened += 1
                        time.sleep(0.5)
                    except Exception as e2:
                        print(f"[Restore]   subprocess also failed: {e2}")
        elif not file_path:
            print(f"[Restore]   File '{filename}' not found on disk — skipping")

    return opened


# ─── CHROME TABS ─────────────────────────────────────────────────────────────

def restore_chrome_tabs(session_id: int) -> int:
    tabs = db.get_chrome_tabs(session_id)
    if not tabs:
        return 0

    urls = [t["url"] for t in tabs if t.get("url")
            and not t["url"].startswith("chrome://")
            and not t["url"].startswith("about:")]
    if not urls:
        return 0

    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    chrome_exe = next((p for p in chrome_paths if os.path.exists(p)), None)

    import time
    if chrome_exe:
        try:
            subprocess.Popen([chrome_exe, "--new-window", urls[0]])
            time.sleep(1.5)
            for url in urls[1:]:
                subprocess.Popen([chrome_exe, url])
                time.sleep(0.2)
            return len(urls)
        except Exception:
            pass

    for url in urls:
        webbrowser.open(url)
    return len(urls)


# ─── VS CODE ─────────────────────────────────────────────────────────────────

def restore_vscode_windows(windows: list[dict]) -> int:
    code_windows = [w for w in windows if w.get("exe_name", "").lower() == "code.exe"]
    if not code_windows:
        return 0

    code_paths = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ]
    code_exe = next((p for p in code_paths if os.path.exists(p)), "code")

    opened = 0
    for w in code_windows:
        title = w.get("title", "")
        # Title: "filename — folder — Visual Studio Code"
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
        try:
            subprocess.Popen([code_exe])
            opened += 1
        except Exception:
            pass

    return opened


# ─── TERMINALS ────────────────────────────────────────────────────────────────

def restore_terminals(windows: list[dict]) -> int:
    term_exes = {
        "windowsterminal.exe": "wt",
        "cmd.exe": "cmd",
        "powershell.exe": "powershell",
    }
    terminal_windows = [w for w in windows if w.get("exe_name", "").lower() in term_exes]
    opened = 0
    seen = set()

    for w in terminal_windows:
        exe_lower = w.get("exe_name", "").lower()
        if exe_lower in seen:
            continue
        cmd = term_exes.get(exe_lower, "cmd")
        try:
            subprocess.Popen([cmd])
            seen.add(exe_lower)
            opened += 1
        except Exception:
            pass

    return opened


# ─── GENERIC APPS ────────────────────────────────────────────────────────────

_SKIP_RESTORE_EXES = {
    "code.exe", "chrome.exe", "firefox.exe", "msedge.exe", "brave.exe",
    "acroRd32.exe", "acrobat.exe", "sumatrapdf.exe",
    "windowsterminal.exe", "cmd.exe", "powershell.exe",
    "explorer.exe", "winword.exe", "excel.exe", "powerpnt.exe",
}


def restore_other_apps(windows: list[dict]) -> int:
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
    try:
        import time
        from pyvda import VirtualDesktop, get_virtual_desktops
        VirtualDesktop.create()
        time.sleep(0.6)
        desktops = get_virtual_desktops()
        new_desktop = desktops[-1]
        new_desktop.go()
        time.sleep(0.4)
        return str(new_desktop.id)
    except Exception as e:
        print(f"[Restore] Could not create new desktop: {e}")
        return None


# ─── MAIN RESTORE ─────────────────────────────────────────────────────────────

def restore_session(session_id: int) -> dict:
    """
    Full session restore:
    1. Create a new virtual desktop and switch to it
    2. Restore all apps — Chrome tabs, VS Code, Office docs, terminals, others
    3. Update session's desktop_id in DB
    """
    new_desktop_id = create_restore_desktop()

    windows = db.get_windows(session_id)
    print(f"[Restore] Restoring session {session_id}: {len(windows)} saved windows")
    for w in windows:
        print(f"[Restore]   {w.get('exe_name')} — {w.get('title', '')[:60]}")

    tabs_opened     = restore_chrome_tabs(session_id)
    vscode_opened   = restore_vscode_windows(windows)
    office_opened   = restore_office_documents(windows)   # replaces old pdf+other for Office
    terminal_opened = restore_terminals(windows)
    other_opened    = restore_other_apps(windows)

    db.update_session_status(session_id, "active")
    if new_desktop_id:
        try:
            from datetime import datetime
            with db.get_conn() as conn:
                conn.execute(
                    "UPDATE sessions SET virtual_desktop_id=?, updated_at=? WHERE id=?",
                    (new_desktop_id, datetime.now().isoformat(), session_id)
                )
        except Exception as e:
            print(f"[Restore] Could not update desktop ID: {e}")

    total = tabs_opened + vscode_opened + office_opened + terminal_opened + other_opened
    print(f"[Restore] Done: {total} items restored "
          f"(tabs={tabs_opened} vscode={vscode_opened} office={office_opened} "
          f"terminals={terminal_opened} other={other_opened})")

    return {
        "new_desktop": new_desktop_id is not None,
        "tabs": tabs_opened,
        "vscode": vscode_opened,
        "office": office_opened,
        "terminals": terminal_opened,
        "other": other_opened,
        "total": total,
    }


def get_restore_preview(session_id: int) -> list[str]:
    windows = db.get_windows(session_id)
    tabs = db.get_chrome_tabs(session_id)

    items = []
    if tabs:
        items.append(f"🌐 {len(tabs)} Chrome tab{'s' if len(tabs) != 1 else ''}")

    app_counts: dict[str, int] = {}
    for w in windows:
        name = friendly_app_name(w.get("exe_name", ""))
        if name and name.lower() not in ("explorer", "dwm", "python"):
            app_counts[name] = app_counts.get(name, 0) + 1

    for app, count in sorted(app_counts.items(), key=lambda x: -x[1]):
        items.append(f"🪟 {app} ({count} windows)" if count > 1 else f"🪟 {app}")

    return items

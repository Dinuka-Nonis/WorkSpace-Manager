"""
core/snapshot.py — Snapshot capture for WorkSpace Manager.

Key changes v2:
  • Python, Node, Java and other interpreter/runtime executables are filtered
    out entirely — users never consciously "open" them.
  • Chrome is excluded from the apps list and captured instead via the
    extension (URLs per-profile).
  • VS Code — when running, the open workspace folder(s) are detected from
    VS Code's storage.json and stored as smart 'vscode-folder:' items so
    restore re-opens the right project folder.
  • Chrome profile is detected from the running process's command-line args
    and stored alongside each tab URL so restore opens tabs in the same profile.

Key changes v3:
  • File Explorer (explorer.exe) — open folder windows are captured as
    'explorer-folder:' items so restore re-opens the same folders.
    explorer.exe is no longer silently blocked.
"""

import os
import sys
import time
import json
import threading
from pathlib import Path
from urllib.parse import urlparse, unquote


# ── Block-list: processes that are always background noise ────────────────────

_BACKGROUND_STEMS = frozenset({
    # Office / MS helpers
    "officeclicktorun", "msoia", "msosync", "onedrive", "onedrivesetup",
    "searchindexer", "searchhost", "searchapp",
    # MSI / hardware helpers
    "msiapservice", "msibgs", "nahimicnotifysys",
    "audiodg", "ibtsiva", "igfxem", "igfxhk", "igfxsrvc",
    # Windows internals
    "svchost", "conhost", "csrss", "lsass", "wininit", "winlogon",
    "dwm",
    # NOTE: "explorer" is intentionally NOT here — it's handled specially
    # to capture open File Explorer folder windows.
    "sihost", "fontdrvhost",
    "runtimebroker", "backgroundtaskhost", "taskhostw",
    "spoolsv", "wuauclt", "trustedinstaller",
    # Updaters / crash reporters
    "crashpad_handler", "crashreporter", "update", "updater",
    "helperservice", "setup", "installer",
    # Terminals launched by other apps
    "cmd",

    # ── Language interpreters & runtimes ─────────────────────────────────────
    # These are infrastructure, not apps the user consciously "opens".
    "python", "pythonw", "python3", "pyw",
    "node", "nodejs",
    "java", "javaw", "javaws",
    "ruby", "rbx",
    "perl",
    "php", "php-cgi",
    "r", "rscript", "rgui", "rterm",
    "lua", "luajit",
    "dotnet",
    "mono",
    "wsl",
    "bash", "sh", "zsh", "fish",
    "powershell", "pwsh",

    # ── Build / package tools ─────────────────────────────────────────────────
    "pip", "pip3", "npm", "npx", "yarn", "pnpm",
    "gradle", "mvn",
    "make", "cmake", "msbuild",
    "git", "git-lfs",

    # ── Browsers — captured via extension (URLs + profile) not as raw exe ─────
    # Only Chrome gets this treatment; other browsers appear normally.
    "chrome", "chromium",
})

# Interpreter stems that might have version suffixes, e.g. "python3.14", "node20"
_INTERPRETER_PREFIXES = (
    "python", "pythonw", "python3",
    "node", "nodejs",
    "java", "javaw",
    "ruby", "perl", "php", "lua",
)


def _is_interpreter(stem: str) -> bool:
    """True for versioned interpreter stems like 'python3.14' or 'node20'."""
    for prefix in _INTERPRETER_PREFIXES:
        if stem.startswith(prefix) and stem != prefix:
            suffix = stem[len(prefix):]
            if suffix.replace(".", "").isdigit():
                return True
    return False


# ── Visible-window check (Windows) ───────────────────────────────────────────

def _has_visible_window_win32(pid: int) -> bool:
    """Return True if the process has at least one real visible window."""
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        found  = ctypes.c_bool(False)
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )

        def _enum_cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            proc_id = ctypes.wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if proc_id.value != pid:
                return True
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if rect.right - rect.left < 10 or rect.bottom - rect.top < 10:
                return True
            found.value = True
            return False

        cb = WNDENUMPROC(_enum_cb)
        user32.EnumWindows(cb, 0)
        return found.value
    except Exception:
        return False


# ── VS Code workspace detection ───────────────────────────────────────────────

def _uri_to_local_path(uri: str) -> str | None:
    """
    Convert a VS Code file:// URI to a local OS path.
    Returns None if conversion fails or the path doesn't exist.
    """
    try:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            return None
        raw = unquote(parsed.path)
        # Windows: /D:/projects/foo  →  D:/projects/foo
        if raw.startswith("/") and len(raw) > 3 and raw[2] == ":":
            raw = raw[1:]
        raw = os.path.normpath(raw)
        return raw if os.path.exists(raw) else None
    except Exception:
        return None


def _get_vscode_workspaces(code_exe: str) -> list[dict]:
    """
    Reads VS Code's storage.json to discover which folder(s) or workspace
    files are currently open, and returns them as 'vscode-folder:' items.

    path_or_url encoding:  vscode-folder:<code_exe>||<workspace_path>
    (the || separator never appears in Windows paths)

    Handles VS Code, VS Code Insiders, and Cursor.
    Falls back to a plain "open VS Code" entry if no workspace is found.
    """
    appdata   = os.getenv("APPDATA", "")
    code_stem = Path(code_exe).stem.lower()

    # Each tuple: (substring to match in exe stem, appdata folder, display name)
    variants = [
        ("code - insiders", "Code - Insiders", "VS Code Insiders"),
        ("cursor",          "Cursor",           "Cursor"),
        ("code",            "Code",             "VS Code"),  # must be last (substring)
    ]

    results: list[dict] = []
    seen_paths: set[str] = set()

    for stem_match, appdata_dir, display_name in variants:
        if stem_match not in code_stem:
            continue

        # VS Code moved storage.json between versions — try all known locations
        candidate_paths = [
            os.path.join(appdata, appdata_dir, "storage.json"),
            os.path.join(appdata, appdata_dir, "User", "storage.json"),
            os.path.join(appdata, appdata_dir, "User", "globalStorage", "storage.json"),
        ]
        storage_json = next((p for p in candidate_paths if os.path.exists(p)), None)
        if not storage_json:
            continue

        try:
            with open(storage_json, encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)

            ws = data.get("windowsState", {})
            windows: list[dict] = []

            last = ws.get("lastActiveWindow")
            if isinstance(last, dict):
                windows.append(last)
            for w in ws.get("openedWindows", []):
                if isinstance(w, dict):
                    windows.append(w)

            for window in windows:
                folder_uri = window.get("folder") or window.get("folderUri")
                workspace  = window.get("workspace")
                config_uri = (
                    workspace.get("configPath")
                    if isinstance(workspace, dict) else None
                )

                path: str | None = None
                if folder_uri:
                    path = _uri_to_local_path(folder_uri)
                elif config_uri:
                    path = _uri_to_local_path(config_uri)

                if not path:
                    continue

                norm = os.path.normcase(path)
                if norm in seen_paths:
                    continue
                seen_paths.add(norm)

                name = os.path.basename(path.rstrip("/\\"))
                results.append({
                    "type":        "app",
                    "path_or_url": f"vscode-folder:{code_exe}||{path}",
                    "label":       f"{display_name} — {name}",
                })

        except Exception as e:
            print(f"[Snapshot] VS Code storage.json error ({appdata_dir}): {e}")
            continue

        # Only process the first matching variant
        break

    # Fallback: VS Code is running but no folder was detected
    if not results:
        results.append({
            "type":        "app",
            "path_or_url": f"vscode-folder:{code_exe}||",
            "label":       "VS Code",
        })

    return results


# ── Chrome profile detection ──────────────────────────────────────────────────

def _get_active_chrome_profile() -> tuple[str, str]:
    """
    Detect the active Chrome profile by inspecting running chrome.exe processes
    for the --profile-directory=<dir> command-line flag, then reads
    %LOCALAPPDATA%\\Google\\Chrome\\User Data\\Local State to map the
    directory name to the human-readable display name.

    Returns (profile_dir, profile_display_name)
      e.g. ("Profile 3", "OxzaaScials")
    Returns ("Default", "<name>") when Chrome is running with no explicit flag.
    Returns ("", "") when Chrome is not running at all.
    """
    try:
        import psutil
    except ImportError:
        return "", ""

    local_appdata = os.getenv("LOCALAPPDATA", "")
    local_state_path = os.path.join(
        local_appdata, "Google", "Chrome", "User Data", "Local State"
    )

    # Build: profile directory → human-readable name
    profile_names: dict[str, str] = {}
    if os.path.exists(local_state_path):
        try:
            with open(local_state_path, encoding="utf-8", errors="replace") as fh:
                ls = json.load(fh)
            for dir_name, info in ls.get("profile", {}).get("info_cache", {}).items():
                profile_names[dir_name] = info.get("name", dir_name)
        except Exception:
            pass

    chrome_running      = False
    profile_dir_counts: dict[str, int] = {}

    for proc in psutil.process_iter(["exe", "cmdline"]):
        try:
            exe = proc.info.get("exe") or ""
            if "chrome.exe" not in exe.lower():
                continue
            chrome_running = True
            for arg in (proc.info.get("cmdline") or []):
                if arg.startswith("--profile-directory="):
                    prof = arg.split("=", 1)[1].strip('"').strip("'")
                    profile_dir_counts[prof] = profile_dir_counts.get(prof, 0) + 1
        except Exception:
            continue

    if not chrome_running:
        return "", ""

    if not profile_dir_counts:
        # Chrome running with no explicit profile flag → Default profile
        name = profile_names.get("Default", "Default")
        return "Default", name

    # The profile with the most associated processes = most open windows
    best = max(profile_dir_counts, key=lambda k: profile_dir_counts[k])
    return best, profile_names.get(best, best)


# ── File Explorer open-folder detection ──────────────────────────────────────

def _get_file_explorer_windows() -> list[dict]:
    """
    Enumerate open File Explorer windows using the Shell COM object model and
    return them as 'explorer-folder:' items so restore can re-open the same
    folders.

    path_or_url encoding:  explorer-folder:<absolute_folder_path>
    Falls back to a plain "Open File Explorer" entry if COM is unavailable.

    Only works on Windows.
    """
    if sys.platform != "win32":
        return []

    results: list[dict] = []
    seen_folders: set[str] = set()

    try:
        import comtypes.client  # type: ignore
        shell = comtypes.client.CreateObject("Shell.Application")
        windows = shell.Windows()
        for i in range(windows.Count):
            try:
                win = windows.Item(i)
                if win is None:
                    continue
                # LocationURL is a file:// URI for folder windows
                loc_url = getattr(win, "LocationURL", None) or ""
                if not loc_url.startswith("file://"):
                    continue
                folder_path = _uri_to_local_path(loc_url)
                if not folder_path:
                    continue
                norm = os.path.normcase(folder_path)
                if norm in seen_folders:
                    continue
                seen_folders.add(norm)
                name = os.path.basename(folder_path.rstrip("/\\")) or folder_path
                results.append({
                    "type":        "app",
                    "path_or_url": f"explorer-folder:{folder_path}",
                    "label":       f"File Explorer — {name}",
                })
            except Exception:
                continue
    except Exception:
        # comtypes not available or COM failed — try pywin32 as fallback
        try:
            import win32com.client  # type: ignore
            shell = win32com.client.Dispatch("Shell.Application")
            windows = shell.Windows()
            for win in windows:
                try:
                    loc_url = getattr(win, "LocationURL", None) or ""
                    if not loc_url.startswith("file://"):
                        continue
                    folder_path = _uri_to_local_path(loc_url)
                    if not folder_path:
                        continue
                    norm = os.path.normcase(folder_path)
                    if norm in seen_folders:
                        continue
                    seen_folders.add(norm)
                    name = os.path.basename(folder_path.rstrip("/\\")) or folder_path
                    results.append({
                        "type":        "app",
                        "path_or_url": f"explorer-folder:{folder_path}",
                        "label":       f"File Explorer — {name}",
                    })
                except Exception:
                    continue
        except Exception:
            # Neither COM library available — return a generic entry if
            # explorer.exe has a visible window
            try:
                import psutil
                import ctypes
                import ctypes.wintypes
                for proc in psutil.process_iter(["exe", "pid"]):
                    exe = proc.info.get("exe") or ""
                    if Path(exe).stem.lower() == "explorer":
                        pid = proc.info.get("pid") or 0
                        if pid and _has_visible_window_win32(pid):
                            results.append({
                                "type":        "app",
                                "path_or_url": "explorer-folder:",
                                "label":       "File Explorer",
                            })
                        break
            except Exception:
                pass

    return results


# ── Running apps capture ──────────────────────────────────────────────────────


# ── New strategy: enumerate ALL visible windows directly ──────────────────────
#
# Instead of building a registry of "installed apps" and hoping running
# processes match it, we ask Windows for every visible window, get its
# title + owning process + exe path, and use that as ground truth.
# This captures UWP apps, Store apps, Electron apps, everything —
# with no hardcoded app lists.

def _get_window_title(hwnd) -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value.strip()


def _get_window_rect(hwnd) -> tuple[int, int, int, int]:
    import ctypes, ctypes.wintypes
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _is_real_app_window(hwnd, user32) -> bool:
    """
    True if hwnd is a real top-level application window the user can see.
    Filters out: invisible, zero-title, tiny, tool windows, UWP chrome windows.
    """
    if not user32.IsWindowVisible(hwnd):
        return False
    # Must have a title
    title_len = user32.GetWindowTextLengthW(hwnd)
    if title_len == 0:
        return False
    # Must be a top-level window (no owner / owned by desktop)
    if user32.GetWindow(hwnd, 4) != 0:   # GW_OWNER = 4
        return False
    # Filter by extended window style
    import ctypes
    GWL_EXSTYLE   = -20
    WS_EX_TOOLWINDOW  = 0x00000080
    WS_EX_NOACTIVATE  = 0x08000000
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if ex_style & WS_EX_TOOLWINDOW:
        return False
    # Must have reasonable size
    l, t, r, b = _get_window_rect(hwnd)
    if (r - l) < 50 or (b - t) < 50:
        return False
    return True


def capture_running_apps() -> list[dict]:
    """
    Enumerate all real visible top-level windows and return app items for each.

    Strategy (no hardcoded app lists):
      1. Walk every HWND via EnumWindows
      2. Apply real-window filter (visible, titled, non-tool, big enough)
      3. Get owning PID -> exe path
      4. Skip noise (interpreters, background stems)
      5. Special handling:
           • explorer.exe    → capture folder path via Shell COM
           • code.exe/cursor → capture VS Code workspace folder
           • chrome.exe      → skip (captured via extension)
           • WindowsApps/... → UWP app, derive label from package name
           • everything else → use window title as label, exe as path_or_url
    """
    if sys.platform != "win32":
        return []

    try:
        import psutil, ctypes, ctypes.wintypes
    except ImportError:
        return []

    user32  = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    # Collect (hwnd, pid, exe, title) for every real window
    windows: list[tuple[int, int, str, str]] = []

    def _enum_cb(hwnd, _):
        try:
            if not _is_real_app_window(hwnd, user32):
                return True
            title = _get_window_title(hwnd)
            if not title:
                return True
            proc_id = ctypes.wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            pid = proc_id.value
            try:
                proc = psutil.Process(pid)
                exe  = proc.exe()
            except Exception:
                return True
            if exe:
                windows.append((hwnd, pid, exe, title))
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)

    # Process collected windows into app items
    results:      list[dict] = []
    seen_exe:     set[str]   = set()   # deduplicate by exe (most apps)
    seen_uwp_pkg: set[str]   = set()   # deduplicate UWP by package folder
    vscode_seen:  set[str]   = set()
    explorer_done = False

    _VSCODE_STEMS = {"code", "code - insiders", "cursor"}
    wa_norm = os.path.normcase(r"C:\Program Files\WindowsApps")

    _UWP_NAMES = {
        "spotifyab": "Spotify", "spotify": "Spotify",
        "whatsapp": "WhatsApp", "discord": "Discord",
        "telegram": "Telegram", "claude": "Claude",
        "openai": "ChatGPT", "chatgpt": "ChatGPT",
        "slack": "Slack", "netflix": "Netflix",
        "zunevideo": "Movies & TV", "zune": "Movies & TV",
        "microsoftmovies": "Movies & TV",
        "twitter": "Twitter / X", "instagram": "Instagram",
        "tiktok": "TikTok", "zoom": "Zoom",
        "teams": "Microsoft Teams", "xbox": "Xbox",
        "prime": "Prime Video",
    }

    _UWP_BG_STEMS = frozenset({
        "nahimic3", "rtkuwp", "igcctray", "igcc", "gesturesign",
        "translucenttb", "widgetservice", "widgets", "xboxpcappft",
        "gamingservices", "gamingservicesnet", "phoneexperiencehost",
        "crossdeviceservice", "m365copilot_autostarter", "cowork-svc",
    })

    for hwnd, pid, raw_exe, title in windows:
        try:
            exe_path = Path(raw_exe)
            stem     = exe_path.stem.lower()
            exe_key  = os.path.normcase(raw_exe)

            # ── Chrome — skip, tabs captured via extension ────────────────────
            if stem in ("chrome", "chromium", "msedge", "brave", "firefox", "opera"):
                continue

            # ── Interpreters / runtimes — skip ───────────────────────────────
            if stem in _BACKGROUND_STEMS or _is_interpreter(stem):
                continue

            # ── Background noise substrings ───────────────────────────────────
            if any(s in stem for s in ("crashpad", "conhost", "dwm",
                                        "searchhost", "textinputhost",
                                        "applicationframehost")):
                continue

            # ── UWP / WindowsApps ─────────────────────────────────────────────
            if wa_norm in exe_key:
                if stem in _UWP_BG_STEMS:
                    continue
                if any(kw in stem for kw in ("helper", "service", "server",
                                              "host", "broker", "agent",
                                              "svc", "overlay", "systrap",
                                              "autostart")):
                    continue
                # Derive package folder for dedup
                parts = exe_path.parts
                try:
                    wa_idx = next(i for i, p in enumerate(parts)
                                  if p.lower() == "windowsapps")
                    pkg_folder = parts[wa_idx + 1]
                except (StopIteration, IndexError):
                    pkg_folder = stem
                if pkg_folder in seen_uwp_pkg:
                    continue
                seen_uwp_pkg.add(pkg_folder)
                # Friendly label
                raw_pkg = pkg_folder.split("_")[0]
                label   = raw_pkg.split(".")[-1]
                for key, friendly in _UWP_NAMES.items():
                    if key in raw_pkg.lower():
                        label = friendly
                        break
                results.append({
                    "type":        "app",
                    "path_or_url": f"uwp:{raw_exe}",
                    "label":       label,
                })
                continue

            # ── File Explorer ─────────────────────────────────────────────────
            if stem == "explorer":
                if not explorer_done:
                    explorer_done = True
                    for item in _get_file_explorer_windows():
                        results.append(item)
                continue

            # ── VS Code / Cursor ──────────────────────────────────────────────
            if stem in _VSCODE_STEMS:
                if exe_key not in seen_exe:
                    seen_exe.add(exe_key)
                    for item in _get_vscode_workspaces(raw_exe):
                        if item["path_or_url"] not in vscode_seen:
                            vscode_seen.add(item["path_or_url"])
                            results.append(item)
                continue

            # ── Everything else — use window title + exe path ─────────────────
            if exe_key in seen_exe:
                continue
            seen_exe.add(exe_key)

            # Clean up the title: remove common suffixes like " - Chrome", app name repeats
            label = title
            # Trim overly long window titles to just the app name part
            # Many apps put "Document - AppName" — take last segment after " - "
            if " - " in label:
                parts_title = label.split(" - ")
                # Heuristic: if last segment is short (likely app name), prefer it
                last = parts_title[-1].strip()
                if len(last) < 40:
                    label = last

            results.append({
                "type":        "app",
                "path_or_url": raw_exe,
                "label":       label,
            })
        except Exception:
            continue

    return results


# ── Chrome-tab capture (side-channel via native messaging host) ───────────────

_TAB_REQUEST_TIMEOUT = 10.0   # seconds to wait for Chrome extension response


def _prewarm_native_host():
    """
    Write a dummy tab_request.json so Chrome's native messaging host launches
    and starts polling the side-channel before we actually need it.
    This is a no-op if the host is already running.
    Called once at startup from main.py.
    """
    try:
        appdata  = Path(os.getenv("APPDATA", ".")) / "WorkSpaceManager"
        appdata.mkdir(parents=True, exist_ok=True)
        req_file = appdata / "tab_request.json"
        # Only write if there isn't already a pending request
        if not req_file.exists():
            req_file.write_text(
                json.dumps({"session_id": 0, "ts": time.time(), "prewarm": True}),
                encoding="utf-8",
            )
    except Exception:
        pass


def request_tabs_from_extension(session_id: int) -> list[dict]:
    """
    Ask the native host to pull tabs from Chrome via the side-channel file.
    Enriches each tab URL with the active Chrome profile so restoring opens
    the URL in the same profile.

    path_or_url encoding:  chrome-profile:<profile_dir>|<url>
    Label prefix:          [Profile Name] <page title>

    Returns [] if the native host is not running or the request times out.
    """
    appdata   = Path(os.getenv("APPDATA", ".")) / "WorkSpaceManager"
    req_file  = appdata / "tab_request.json"
    resp_file = appdata / "tab_response.json"

    # Detect active Chrome profile (fast — just reads process cmdlines)
    profile_dir, profile_name = _get_active_chrome_profile()

    try:
        if resp_file.exists():
            resp_file.unlink()
        req_file.write_text(
            json.dumps({"session_id": session_id, "ts": time.time()}),
            encoding="utf-8",
        )
    except Exception:
        return []

    print(f"[Chrome] Waiting for tabs from native host (timeout={_TAB_REQUEST_TIMEOUT}s)...", flush=True)
    deadline = time.time() + _TAB_REQUEST_TIMEOUT
    while time.time() < deadline:
        if resp_file.exists():
            try:
                payload   = json.loads(resp_file.read_text(encoding="utf-8"))
                req_file.unlink(missing_ok=True)
                resp_file.unlink(missing_ok=True)

                tabs: list[dict] = []
                for t in payload.get("tabs", []):
                    raw_url = t.get("url", "")
                    if not raw_url:
                        continue
                    title = t.get("title") or raw_url

                    if profile_dir:
                        # Encode profile so launcher can open with --profile-directory
                        path_or_url = f"chrome-profile:{profile_dir}|{raw_url}"
                        label       = f"[{profile_name}] {title}"
                    else:
                        path_or_url = raw_url
                        label       = title

                    tabs.append({
                        "type":        "url",
                        "path_or_url": path_or_url,
                        "label":       label,
                    })
                return tabs

            except Exception:
                break
        time.sleep(0.12)

    req_file.unlink(missing_ok=True)
    print("[Chrome] Timed out — no response from native host. Is the extension installed and Chrome running?", flush=True)
    return []


# ── Scan only (no DB write) — for the picker dialog ──────────────────────────

def scan_for_picker(session_id: int) -> dict:
    """
    Scan running apps and Chrome tabs concurrently.
    Returns raw lists so the UI can show a picker before any DB write.

    {
      "apps": [{type, path_or_url, label}, ...],
      "tabs": [{type, path_or_url, label}, ...],
    }
    """
    apps: list[dict] = []
    tabs: list[dict] = []
    app_done = threading.Event()
    tab_done = threading.Event()

    def _get_apps():
        nonlocal apps
        try:
            apps = capture_running_apps()
        except Exception:
            apps = []
        app_done.set()

    def _get_tabs():
        nonlocal tabs
        try:
            tabs = request_tabs_from_extension(session_id)
        except Exception:
            tabs = []
        tab_done.set()

    ta = threading.Thread(target=_get_apps, daemon=True)
    tt = threading.Thread(target=_get_tabs,  daemon=True)
    ta.start(); tt.start()
    app_done.wait(timeout=6.0)
    tab_done.wait(timeout=_TAB_REQUEST_TIMEOUT + 0.5)

    return {"apps": apps, "tabs": tabs}

"""
core/app_registry.py — Builds a list of installed Windows applications.

Sources (in priority order):
  1. HKLM/HKCU Uninstall registry keys  — gives display name + install location
  2. Start Menu .lnk shortcuts           — catches anything the registry misses
  3. HKLM App Paths                      — maps exe names to full paths

Returns a list of AppEntry dicts sorted by name, deduplicated by exe path.
Each entry: { name, exe_path, icon_emoji }
"""

import os
import sys
from pathlib import Path


def _icon_for_exe(exe_path: str) -> str:
    """Best-effort emoji for known apps."""
    stem = Path(exe_path).stem.lower()
    known = {
        "code":           "💻",
        "code - insiders":"💻",
        "cursor":         "💻",
        "chrome":         "🌐",
        "firefox":        "🦊",
        "msedge":         "🌐",
        "brave":          "🦁",
        "opera":          "🎭",
        "slack":          "💬",
        "discord":        "💬",
        "teams":          "👥",
        "zoom":           "📹",
        "notion":         "📝",
        "obsidian":       "🔮",
        "figma":          "🎨",
        "postman":        "📮",
        "insomnia":       "📮",
        "pycharm64":      "🐍",
        "pycharm":        "🐍",
        "idea64":         "☕",
        "idea":           "☕",
        "webstorm64":     "🟨",
        "webstorm":       "🟨",
        "clion64":        "🔧",
        "datagrip64":     "🗄",
        "rider64":        "🔷",
        "devenv":         "🔷",
        "winword":        "📄",
        "excel":          "📊",
        "powerpnt":       "📋",
        "onenote":        "📓",
        "outlook":        "📧",
        "teams":          "👥",
        "msaccess":       "🗄",
        "mspub":          "📰",
        "lync":           "📞",
        "spotify":        "🎵",
        "vlc":            "🎬",
        "mpv":            "🎬",
        "potplayer":      "🎬",
        "potplayermini64":"🎬",
        "gimp-2":         "🖼",
        "gimp":           "🖼",
        "photoshop":      "🖼",
        "illustrator":    "🎨",
        "premiere":       "🎬",
        "afterfx":        "✨",
        "blender":        "🧊",
        "unity":          "🎮",
        "unrealEditor":   "🎮",
        "steam":          "🎮",
        "epicgameslauncher":"🎮",
        "goggalaxy":      "🎮",
        "docker desktop": "🐳",
        "docker":         "🐳",
        "dbeaver":        "🗄",
        "tableplus":      "🗄",
        "sourcetree":     "🌿",
        "gitkraken":      "🐙",
        "fork":           "🌿",
        "terminal":       "⬛",
        "windowsterminal":"⬛",
        "powershell":     "🔵",
        "cmd":            "⬛",
        "wezterm":        "⬛",
        "hyper":          "⬛",
        "notepad++":      "📝",
        "notepad":        "📝",
        "sublime_text":   "📝",
        "atom":           "⚛",
        "typora":         "📝",
        "xmind":          "🗺",
        "drawio":         "📐",
        "miro":           "🪄",
        "whatsapp":       "💬",
        "telegram":       "💬",
        "signal":         "💬",
        "thunderbird":    "📧",
        "1password":      "🔑",
        "keepassxc":      "🔑",
        "bitwarden":      "🔑",
        "filezilla":      "📁",
        "winscp":         "📁",
        "putty":          "📡",
        "mobaxterm":      "📡",
    }
    for key, emoji in known.items():
        if key in stem:
            return emoji
    return "⚙️"


# ── Registry reader ───────────────────────────────────────────────────────────

def _read_uninstall_keys() -> list[dict]:
    """
    Read installed apps from Windows Uninstall registry keys.
    Checks both HKLM and HKCU, 64-bit and 32-bit hives.
    """
    if sys.platform != "win32":
        return []

    try:
        import winreg
    except ImportError:
        return []

    results = []
    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for hive, key_path in hives:
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError:
            continue

        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, i)
                i += 1
            except OSError:
                break

            try:
                subkey = winreg.OpenKey(key, subkey_name)

                def _val(name):
                    try:
                        return winreg.QueryValueEx(subkey, name)[0]
                    except OSError:
                        return ""

                display_name = _val("DisplayName")
                install_loc  = _val("InstallLocation")
                display_icon = _val("DisplayIcon")

                winreg.CloseKey(subkey)

                if not display_name:
                    continue
                # Skip updates, components, SDKs, drivers
                skip_keywords = (
                    "update", "redistributable", "runtime", "sdk", "driver",
                    "plugin", "extension", "package", "component", "module",
                    "hotfix", "patch", "service pack", "language pack",
                    "visual c++", "directx", "net framework", ".net",
                )
                if any(kw in display_name.lower() for kw in skip_keywords):
                    continue

                # Try to find the exe path
                exe_path = ""

                # 1. DisplayIcon often points to the exe directly
                if display_icon:
                    # Strip index suffix like ",0"
                    icon_path = display_icon.split(",")[0].strip().strip('"')
                    if icon_path.lower().endswith(".exe") and os.path.exists(icon_path):
                        exe_path = icon_path

                # 2. Search install location for a likely exe
                if not exe_path and install_loc and os.path.isdir(install_loc):
                    # Look for an exe matching the app name
                    name_stem = display_name.split(" ")[0].lower().replace("-", "")
                    for root, dirs, files in os.walk(install_loc):
                        # Don't recurse too deep
                        depth = root[len(install_loc):].count(os.sep)
                        if depth > 2:
                            dirs.clear()
                            continue
                        for f in files:
                            if f.lower().endswith(".exe"):
                                f_stem = Path(f).stem.lower().replace("-", "").replace("_", "")
                                if name_stem[:4] in f_stem:
                                    exe_path = os.path.join(root, f)
                                    break
                        if exe_path:
                            break

                if not exe_path:
                    continue

                results.append({
                    "name":      display_name,
                    "exe_path":  exe_path,
                    "icon_emoji": _icon_for_exe(exe_path),
                })

            except OSError:
                continue

        winreg.CloseKey(key)

    return results


def _read_app_paths() -> list[dict]:
    """
    Read from HKLM App Paths — maps registered exe names to full paths.
    This catches apps like Notepad++, 7-Zip etc. that register here.
    """
    if sys.platform != "win32":
        return []

    try:
        import winreg
    except ImportError:
        return []

    results = []
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"

    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
    except OSError:
        return []

    i = 0
    while True:
        try:
            subkey_name = winreg.EnumKey(key, i)
            i += 1
        except OSError:
            break

        try:
            subkey = winreg.OpenKey(key, subkey_name)
            try:
                exe_path = winreg.QueryValueEx(subkey, "")[0].strip('"')
            except OSError:
                winreg.CloseKey(subkey)
                continue
            winreg.CloseKey(subkey)

            if not exe_path or not os.path.exists(exe_path):
                continue
            if not exe_path.lower().endswith(".exe"):
                continue

            name = Path(subkey_name).stem
            # Clean up common suffixes
            name = name.replace("64", "").replace("32", "")

            results.append({
                "name":       name,
                "exe_path":   exe_path,
                "icon_emoji": _icon_for_exe(exe_path),
            })
        except OSError:
            continue

    winreg.CloseKey(key)
    return results


def _read_start_menu_shortcuts() -> list[dict]:
    """
    Read .lnk shortcuts from the Start Menu folders.
    Catches UWP-adjacent and manually installed apps.
    """
    if sys.platform != "win32":
        return []

    try:
        import win32com.client
    except ImportError:
        return []

    shell = win32com.client.Dispatch("WScript.Shell")
    results = []

    start_dirs = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]

    for start_dir in start_dirs:
        if not start_dir.exists():
            continue
        for lnk in start_dir.rglob("*.lnk"):
            try:
                shortcut = shell.CreateShortcut(str(lnk))
                target = shortcut.TargetPath
                if not target or not target.lower().endswith(".exe"):
                    continue
                if not os.path.exists(target):
                    continue
                # Skip uninstallers and helpers
                stem = Path(target).stem.lower()
                if any(kw in stem for kw in ("uninstall", "setup", "helper", "updater", "crash")):
                    continue

                name = lnk.stem
                results.append({
                    "name":       name,
                    "exe_path":   target,
                    "icon_emoji": _icon_for_exe(target),
                })
            except Exception:
                continue

    return results


# ── Public API ────────────────────────────────────────────────────────────────

_cache: list[dict] | None = None


def get_installed_apps(force_refresh: bool = False) -> list[dict]:
    """
    Returns a deduplicated, sorted list of installed apps.
    Results are cached after the first call (takes ~0.5s).
    Each entry: { name: str, exe_path: str, icon_emoji: str }
    """
    global _cache
    if _cache is not None and not force_refresh:
        print(f"[AppRegistry] Returning {len(_cache)} cached apps")
        return _cache

    all_apps: list[dict] = []

    try:
        uninstall = _read_uninstall_keys()
        print(f"[AppRegistry] Uninstall keys: {len(uninstall)} apps")
        all_apps.extend(uninstall)
    except Exception as e:
        print(f"[AppRegistry] Uninstall keys failed: {e}")

    try:
        app_paths = _read_app_paths()
        print(f"[AppRegistry] App Paths: {len(app_paths)} apps")
        all_apps.extend(app_paths)
    except Exception as e:
        print(f"[AppRegistry] App Paths failed: {e}")

    try:
        shortcuts = _read_start_menu_shortcuts()
        print(f"[AppRegistry] Start Menu shortcuts: {len(shortcuts)} apps")
        all_apps.extend(shortcuts)
    except Exception as e:
        print(f"[AppRegistry] Start Menu shortcuts failed: {e}")

    # Deduplicate by normalized exe path
    seen_paths: set[str] = set()
    seen_names: set[str] = set()
    unique: list[dict] = []

    for app in all_apps:
        norm_path = os.path.normcase(app["exe_path"])
        norm_name = app["name"].lower().strip()

        if norm_path in seen_paths:
            continue
        if norm_name in seen_names:
            # Keep the one with the better (longer/more specific) name
            continue

        seen_paths.add(norm_path)
        seen_names.add(norm_name)
        unique.append(app)

    # Sort alphabetically
    unique.sort(key=lambda a: a["name"].lower())

    _cache = unique
    return _cache


def search_apps(query: str) -> list[dict]:
    """Filter installed apps by name query (case-insensitive substring)."""
    apps = get_installed_apps()
    q = query.lower().strip()
    if not q:
        return apps
    return [a for a in apps if q in a["name"].lower()]
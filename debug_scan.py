"""
Drop this in your workspace-manager folder and run:
    python debug_scan.py
It will print exactly what processes are running, what the registry finds,
and why things are being filtered out.
"""
import os, sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("=" * 60)
print("1. RUNNING PROCESSES (all with visible windows)")
print("=" * 60)
import psutil, ctypes, ctypes.wintypes

user32 = ctypes.windll.user32

def has_visible_window(pid):
    found = ctypes.c_bool(False)
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd): return True
        if user32.GetWindowTextLengthW(hwnd) == 0: return True
        proc_id = ctypes.wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value != pid: return True
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right - rect.left < 10 or rect.bottom - rect.top < 10: return True
        found.value = True
        return False
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found.value

for proc in psutil.process_iter(["exe", "pid", "name"]):
    try:
        exe = proc.info.get("exe") or ""
        pid = proc.info.get("pid") or 0
        if not exe: continue
        stem = Path(exe).stem.lower()
        vis = has_visible_window(pid)
        if vis:
            print(f"  VISIBLE  pid={pid:6}  stem={stem:30}  exe={exe}")
    except Exception:
        continue

print()
print("=" * 60)
print("2. APP REGISTRY — what get_installed_apps() returns")
print("=" * 60)
from core.app_registry import get_installed_apps, _scan_user_install_dirs

print("\n-- User install dirs scan:")
user = _scan_user_install_dirs()
for a in user:
    print(f"  {a['name']:40}  {a['exe_path']}")

print(f"\n-- Total from get_installed_apps(): ", end="")
known = get_installed_apps(force_refresh=True)
print(len(known))

# Check for specific apps
targets = ["code", "spotify", "cursor", "discord", "vscode"]
print("\n-- Searching for target apps in registry:")
for app in known:
    stem = Path(app["exe_path"]).stem.lower()
    if any(t in stem or t in app["name"].lower() for t in targets):
        print(f"  FOUND: {app['name']:40}  {app['exe_path']}")

print()
print("=" * 60)
print("3. LOCALAPPDATA Programs dir contents")
print("=" * 60)
localappdata = os.environ.get("LOCALAPPDATA", "")
programs = Path(localappdata) / "Programs"
print(f"Scanning: {programs}")
if programs.exists():
    for item in sorted(programs.iterdir()):
        print(f"  {'DIR ' if item.is_dir() else 'FILE'}  {item.name}")
        if item.is_dir():
            for sub in item.iterdir():
                if sub.suffix.lower() == ".exe":
                    print(f"         -> {sub.name}")

print()
print("=" * 60)
print("4. APPDATA Spotify check")
print("=" * 60)
appdata = os.environ.get("APPDATA", "")
spotify = Path(appdata) / "Spotify" / "Spotify.exe"
print(f"Spotify path: {spotify}")
print(f"Exists: {spotify.exists()}")

print()
print("=" * 60)
print("5. VSCODE storage.json check")
print("=" * 60)
storage = Path(appdata) / "Code" / "storage.json"
print(f"Storage path: {storage}")
print(f"Exists: {storage.exists()}")
if storage.exists():
    data = json.loads(storage.read_text(encoding="utf-8", errors="replace"))
    ws = data.get("windowsState", {})
    print(f"lastActiveWindow: {json.dumps(ws.get('lastActiveWindow', {}), indent=2)[:300]}")


"""
Drop in workspace-manager folder, run: python debug2.py
Checks VS Code storage.json real location and WindowsApps detection.
"""
import os, sys, json, glob
from pathlib import Path

appdata = os.environ.get("APPDATA", "")
localappdata = os.environ.get("LOCALAPPDATA", "")

print("=== VS Code storage.json search ===")
# Try all common locations
candidates = [
    Path(appdata) / "Code" / "storage.json",
    Path(appdata) / "Code" / "User" / "storage.json",
    Path(appdata) / "Code - Insiders" / "storage.json",
]
for c in candidates:
    print(f"  {c}  exists={c.exists()}")

# Also search broadly
for root, dirs, files in os.walk(Path(appdata)):
    for f in files:
        if f == "storage.json" and "Code" in str(root):
            print(f"  FOUND: {Path(root) / f}")
    dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules", "Cache", "CachedData", "logs")]

print()
print("=== WindowsApps visible processes ===")
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
        if "WindowsApps" not in exe: continue
        vis = has_visible_window(pid)
        print(f"  visible={vis}  pid={pid}  exe={exe}")
    except Exception:
        continue

print()
print("=== VS Code: all running code.exe PIDs and windows ===")
for proc in psutil.process_iter(["exe", "pid", "name", "cmdline"]):
    try:
        exe = proc.info.get("exe") or ""
        pid = proc.info.get("pid") or 0
        if "code.exe" not in exe.lower(): continue
        vis = has_visible_window(pid)
        cmd = (proc.info.get("cmdline") or [])[:3]
        print(f"  pid={pid}  visible={vis}  cmd={cmd}")
    except Exception:
        continue


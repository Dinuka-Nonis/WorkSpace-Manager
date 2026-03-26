"""
Run this to verify your Chrome native messaging setup is correct.
    python check_chrome_setup.py
"""
import os, sys, json, winreg, time
from pathlib import Path

APPDATA = Path(os.getenv("APPDATA", "."))
HOST_NAME = "com.workspace.manager"

print("=" * 60)
print("Chrome Native Messaging Setup Check")
print("=" * 60)

# 1. Registry key
print("\n[1] Registry key")
try:
    reg_path = r"Software\Google\Chrome\NativeMessagingHosts\com.workspace.manager"
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path)
    manifest_path, _ = winreg.QueryValueEx(key, "")
    winreg.CloseKey(key)
    print(f"  ✓ Registry key exists")
    print(f"  ✓ Points to: {manifest_path}")
except Exception as e:
    print(f"  ✗ Registry key missing: {e}")
    print(f"  → Run: python native_host/install_host.py")
    sys.exit(1)

# 2. Manifest file
print("\n[2] Manifest file")
manifest_path = Path(manifest_path)
if manifest_path.exists():
    print(f"  ✓ Manifest exists: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"  ✓ name: {manifest.get('name')}")
    origins = manifest.get("allowed_origins", [])
    print(f"  ✓ allowed_origins: {origins}")
    if any("REPLACE_WITH" in o for o in origins):
        print("  ✗ ERROR: Extension ID not set! Run:")
        print("      python native_host/install_host.py --update-id YOUR_ID")
        sys.exit(1)
    bat_path = Path(manifest.get("path", ""))
    print(f"  ✓ bat path: {bat_path}")
else:
    print(f"  ✗ Manifest missing at {manifest_path}")
    sys.exit(1)

# 3. BAT wrapper
print("\n[3] BAT wrapper")
if bat_path.exists():
    print(f"  ✓ BAT exists")
    print(f"  Content: {bat_path.read_text()}")
else:
    print(f"  ✗ BAT missing: {bat_path}")
    print("  → Run: python native_host/install_host.py")
    sys.exit(1)

# 4. Side-channel directory
print("\n[4] Side-channel directory")
wm_dir = APPDATA / "WorkSpaceManager"
wm_dir.mkdir(parents=True, exist_ok=True)
print(f"  ✓ {wm_dir}")

# 5. Live test — write a tab_request and wait for response
print("\n[5] Live test — send tab request and wait for Chrome response")
print("    (Chrome must be open with the extension installed)")
req_file  = wm_dir / "tab_request.json"
resp_file = wm_dir / "tab_response.json"

if resp_file.exists():
    resp_file.unlink()

req_file.write_text(json.dumps({"session_id": 1, "ts": time.time()}), encoding="utf-8")
print(f"  ✓ Wrote tab_request.json")
print(f"  Waiting up to 15 seconds for response...")

deadline = time.time() + 15
while time.time() < deadline:
    if resp_file.exists():
        payload = json.loads(resp_file.read_text(encoding="utf-8"))
        tabs = payload.get("tabs", [])
        print(f"\n  ✓ GOT RESPONSE — {len(tabs)} tabs received!")
        for t in tabs[:5]:
            print(f"      {t.get('title', '?')[:60]}  →  {t.get('url', '')[:60]}")
        if len(tabs) > 5:
            print(f"      ... and {len(tabs)-5} more")
        resp_file.unlink(missing_ok=True)
        req_file.unlink(missing_ok=True)
        break
    time.sleep(0.5)
    print(".", end="", flush=True)
else:
    print(f"\n  ✗ TIMEOUT — no response after 15 seconds")
    print()
    print("  Possible causes:")
    print("  a) Chrome extension is not installed → chrome://extensions → Load unpacked")
    print("  b) Extension ID in manifest doesn't match → check allowed_origins above")
    print("     Then run: python native_host/install_host.py --update-id YOUR_ID")
    print("  c) Native messaging host not starting → check Chrome extension errors")
    print("     Open chrome://extensions → WorkSpace Manager → Details → Errors")
    print("  d) Wrong Python in BAT file — BAT uses:", bat_path.read_text().split('"')[1])
    req_file.unlink(missing_ok=True)

print("\nDone.")

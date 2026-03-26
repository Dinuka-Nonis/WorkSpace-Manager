"""
native_host/install_host.py — Registers the WorkSpace Native Messaging Host
with Chrome on Windows by writing the manifest to the registry.

Run once after installation:
    python native_host/install_host.py

To uninstall:
    python native_host/install_host.py --uninstall
"""

import sys
import os
import json
import shutil
from pathlib import Path

HOST_NAME = "com.workspace.manager"
HOST_DESCRIPTION = "WorkSpace Manager Native Host"


def get_host_py_path() -> Path:
    return Path(__file__).parent / "host.py"


def get_manifest_dir() -> Path:
    """Where to store the native host manifest JSON."""
    appdata = Path(os.getenv("APPDATA", "."))
    return appdata / "WorkSpaceManager" / "native_host"


def get_manifest_path() -> Path:
    return get_manifest_dir() / f"{HOST_NAME}.json"


def find_python() -> str:
    """Find the path to the current Python interpreter."""
    return sys.executable


def write_manifest():
    """Write the native host manifest JSON file."""
    host_path = get_host_py_path().resolve()
    python_path = find_python()
    print(f"  host.py path : {host_path}")
    print(f"  python path  : {python_path}")

    # Create a wrapper .bat file that Chrome can call
    bat_path = get_manifest_dir() / "workspace_host.bat"

    manifest = {
        "name": HOST_NAME,
        "description": HOST_DESCRIPTION,
        "path": str(bat_path),
        "type": "stdio",
        "allowed_origins": [
            # Replace with your extension ID after loading unpacked
            "chrome-extension://REPLACE_WITH_EXTENSION_ID/"
        ]
    }

    manifest_dir = get_manifest_dir()
    manifest_dir.mkdir(parents=True, exist_ok=True)

    # Write .bat wrapper
    bat_content = f'@echo off\n"{python_path}" "{host_path}" %*\n'
    bat_path.write_text(bat_content)

    # Write manifest JSON
    manifest_path = get_manifest_path()
    manifest_path.write_text(json.dumps(manifest, indent=2))

    return manifest_path, bat_path


def register_in_registry(manifest_path: Path):
    """Write the registry key pointing Chrome to our manifest."""
    try:
        import winreg
        reg_path = r"Software\Google\Chrome\NativeMessagingHosts" + "\\" + HOST_NAME
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
        print(f"✓ Registry key written: HKCU\\{reg_path}")
    except ImportError:
        print("✗ winreg not available (not on Windows)")
    except Exception as e:
        print(f"✗ Registry error: {e}")


def unregister_from_registry():
    try:
        import winreg
        reg_path = r"Software\Google\Chrome\NativeMessagingHosts" + "\\" + HOST_NAME
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_path)
        print(f"✓ Registry key removed: HKCU\\{reg_path}")
    except Exception as e:
        print(f"✗ {e}")


def update_extension_id(extension_id: str):
    """
    Update the allowed_origins in the native host manifest with the real
    extension ID, then re-register in the registry.
    """
    manifest_path = get_manifest_path()
    if not manifest_path.exists():
        print("✗ Manifest not found — run install first (without --update-id)")
        return

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["allowed_origins"] = [f"chrome-extension://{extension_id}/"]
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"✓ Extension ID updated in manifest: {extension_id}")
        register_in_registry(manifest_path)
        print("\n✓ Done! Restart Chrome for changes to take effect.")
    except Exception as e:
        print(f"✗ Failed to update extension ID: {e}")


def install():
    print("\n=== WorkSpace Native Host Installer ===\n")

    manifest_path, bat_path = write_manifest()
    print(f"✓ Manifest written:  {manifest_path}")
    print(f"✓ .bat wrapper:      {bat_path}")

    register_in_registry(manifest_path)

    print(f"""
─────────────────────────────────────────────────────────
  NEXT STEP — Load Chrome Extension & Set Extension ID
─────────────────────────────────────────────────────────
  1. In Chrome, go to:  chrome://extensions/
  2. Enable "Developer mode" (toggle, top-right corner)
  3. Click "Load unpacked" → select the  chrome_extension/  folder
  4. Copy the Extension ID shown (32-character string, e.g. abcdefgh...)
  5. Run this command with your extension ID:

       python native_host/install_host.py --update-id YOUR_EXTENSION_ID

  That's it — Chrome will pick up the change automatically.
─────────────────────────────────────────────────────────
""")


def uninstall():
    print("\n=== WorkSpace Native Host Uninstaller ===\n")
    unregister_from_registry()
    manifest_dir = get_manifest_dir()
    if manifest_dir.exists():
        shutil.rmtree(manifest_dir)
        print(f"✓ Removed: {manifest_dir}")
    print("✓ Uninstall complete.")


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    elif "--update-id" in sys.argv:
        idx = sys.argv.index("--update-id")
        if idx + 1 < len(sys.argv):
            update_extension_id(sys.argv[idx + 1].strip())
        else:
            print("Usage: python install_host.py --update-id YOUR_EXTENSION_ID")
    else:
        install()

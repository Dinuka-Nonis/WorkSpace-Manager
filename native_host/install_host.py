"""
native_host/install_host.py — Registers the WorkSpace Native Messaging Host
with Chrome on Windows by writing the manifest to the registry.

When running as a bundled EXE:
    Called automatically by first_run_setup() in main.py on every launch.
    Points Chrome directly at the extracted workspace_host.exe — no .bat needed.

When running from source (development):
    python native_host/install_host.py

To uninstall:
    python native_host/install_host.py --uninstall

After publishing to the Chrome Web Store, hardcode your permanent extension ID
into EXTENSION_ID below and rebuild the EXE. Users will never need to run
--update-id manually.
"""

import sys
import os
import json
import shutil
from pathlib import Path

HOST_NAME        = "com.workspace.manager"
HOST_DESCRIPTION = "WorkSpace Manager Native Host"

# ── Set this to your permanent Chrome Web Store extension ID once published. ──
# Leave as empty string while still in developer mode — the app will work
# without it for local testing (you set the ID via --update-id instead).
EXTENSION_ID = ""


# ── Path helpers ──────────────────────────────────────────────────────────────

def _is_frozen() -> bool:
    """True when running as a PyInstaller-built EXE."""
    return getattr(sys, "frozen", False)


def _get_appdata_dir() -> Path:
    appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "WorkSpaceManager"


def _get_host_exe_path() -> Path:
    """
    Return the path Chrome should call for native messaging.

    Frozen EXE:   workspace_host.exe was extracted to %APPDATA%\\WorkSpaceManager\\
                  by first_run_setup() in main.py before this function is called.

    Source mode:  Fall back to looking next to this file (for dev use only).
    """
    extracted = _get_appdata_dir() / "workspace_host.exe"
    if extracted.exists():
        return extracted
    # Source-mode fallback — only reached during development
    return Path(__file__).parent / "workspace_host.exe"


def get_manifest_dir() -> Path:
    return _get_appdata_dir() / "native_host"


def get_manifest_path() -> Path:
    return get_manifest_dir() / f"{HOST_NAME}.json"


# ── Manifest writing ──────────────────────────────────────────────────────────

def write_manifest() -> Path:
    """
    Write the native host manifest JSON.

    In EXE mode:    points directly at workspace_host.exe — no .bat wrapper.
    In source mode: writes a .bat wrapper that calls python host.py
                    (same as the original behaviour for development).

    Returns the path to the written manifest file.
    """
    manifest_dir = get_manifest_dir()
    manifest_dir.mkdir(parents=True, exist_ok=True)

    if _is_frozen():
        # ── EXE mode: Chrome calls workspace_host.exe directly ────────────────
        host_exe = _get_host_exe_path()
        print(f"  [install_host] host exe : {host_exe}")

        allowed = ([f"chrome-extension://{EXTENSION_ID}/"]
                   if EXTENSION_ID else [])

        manifest = {
            "name":            HOST_NAME,
            "description":     HOST_DESCRIPTION,
            "path":            str(host_exe),
            "type":            "stdio",
            "allowed_origins": allowed,
        }

    else:
        # ── Source mode: Chrome calls a .bat which calls python host.py ───────
        host_py     = (Path(__file__).parent / "host.py").resolve()
        python_path = sys.executable
        bat_path    = manifest_dir / "workspace_host.bat"

        print(f"  [install_host] host.py     : {host_py}")
        print(f"  [install_host] python path : {python_path}")

        bat_content = f'@echo off\n"{python_path}" "{host_py}" %*\n'
        bat_path.write_text(bat_content, encoding="utf-8")

        allowed = ([f"chrome-extension://{EXTENSION_ID}/"]
                   if EXTENSION_ID else ["chrome-extension://REPLACE_WITH_EXTENSION_ID/"])

        manifest = {
            "name":            HOST_NAME,
            "description":     HOST_DESCRIPTION,
            "path":            str(bat_path),
            "type":            "stdio",
            "allowed_origins": allowed,
        }

    manifest_path = get_manifest_path()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


# ── Registry helpers ──────────────────────────────────────────────────────────

def register_in_registry(manifest_path: Path):
    """Write the HKCU registry key pointing Chrome to our manifest."""
    try:
        import winreg
        reg_path = r"Software\Google\Chrome\NativeMessagingHosts" + "\\" + HOST_NAME
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
        print(f"[install_host] ✓ Registry key written: HKCU\\{reg_path}")
    except ImportError:
        print("[install_host] ✗ winreg not available (not on Windows)")
    except Exception as e:
        print(f"[install_host] ✗ Registry error: {e}")


def unregister_from_registry():
    try:
        import winreg
        reg_path = r"Software\Google\Chrome\NativeMessagingHosts" + "\\" + HOST_NAME
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_path)
        print(f"[install_host] ✓ Registry key removed: HKCU\\{reg_path}")
    except Exception as e:
        print(f"[install_host] ✗ {e}")


# ── Extension ID update (developer mode helper) ───────────────────────────────

def update_extension_id(extension_id: str):
    """
    Patch the allowed_origins in the manifest on disk with a new extension ID,
    then re-register. Used during developer-mode testing when the extension ID
    changes each time you load the unpacked extension on a new machine.

    Once you publish to the Web Store you get a permanent ID — hardcode it into
    EXTENSION_ID at the top of this file and rebuild instead of using this.
    """
    manifest_path = get_manifest_path()
    if not manifest_path.exists():
        print("✗ Manifest not found — make sure the app has been run at least once first.")
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


# ── Uninstall ─────────────────────────────────────────────────────────────────

def uninstall():
    print("\n=== WorkSpace Native Host Uninstaller ===\n")
    unregister_from_registry()
    manifest_dir = get_manifest_dir()
    if manifest_dir.exists():
        shutil.rmtree(manifest_dir)
        print(f"✓ Removed: {manifest_dir}")
    print("✓ Uninstall complete.")


# ── Source-mode installer (dev only) ─────────────────────────────────────────

def install():
    print("\n=== WorkSpace Native Host Installer (source mode) ===\n")
    manifest_path = write_manifest()
    print(f"✓ Manifest written: {manifest_path}")
    register_in_registry(manifest_path)

    if not EXTENSION_ID:
        print("""
─────────────────────────────────────────────────────────
  NEXT STEP — set your Chrome extension ID
─────────────────────────────────────────────────────────
  1. Open Chrome → chrome://extensions/
  2. Enable Developer mode (top-right toggle)
  3. Click Load unpacked → select the chrome_extension/ folder
  4. Copy the Extension ID (32-character string)
  5. Run:
       python native_host/install_host.py --update-id YOUR_EXTENSION_ID

  Or hardcode it permanently in EXTENSION_ID at the top of this file.
─────────────────────────────────────────────────────────
""")
    else:
        print(f"\n✓ Extension ID already set: {EXTENSION_ID}")
        print("✓ Ready — restart Chrome if it was already running.")


# ── Entry point ───────────────────────────────────────────────────────────────

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
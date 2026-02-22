"""
setup.py — One-time setup script for WorkSpace Manager.
  1. Installs Python dependencies
  2. Registers native messaging host for Chrome
  3. Optionally adds to Windows startup
Run:  python setup.py
"""

import sys
import os
import subprocess
from pathlib import Path


def step(msg: str):
    print(f"\n{'─'*50}\n  {msg}\n{'─'*50}")


def run(cmd: list, check=True):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and check:
        print(f"  STDOUT: {result.stdout}")
        print(f"  STDERR: {result.stderr}")
    return result.returncode == 0


def install_deps():
    step("Installing Python dependencies")
    req_path = Path(__file__).parent / "requirements.txt"
    ok = run([sys.executable, "-m", "pip", "install", "-r", str(req_path), "--quiet"])
    if ok:
        print("  ✓ Dependencies installed.")
    else:
        print("  ✗ Some packages failed. Try manually: pip install -r requirements.txt")


def setup_native_host():
    step("Setting up Chrome Native Messaging Host")
    host_script = Path(__file__).parent / "native_host" / "install_host.py"
    subprocess.run([sys.executable, str(host_script)], check=False)


def add_to_startup():
    step("Add WorkSpace to Windows Startup?")
    answer = input("  Start WorkSpace Manager when Windows boots? [y/N]: ").strip().lower()
    if answer != "y":
        print("  ✓ Skipped.")
        return

    try:
        import winreg
        main_py = Path(__file__).parent / "main.py"
        startup_cmd = f'"{sys.executable}" "{main_py}"'

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "WorkSpaceManager", 0, winreg.REG_SZ, startup_cmd)

        print(f"  ✓ Added to startup: {startup_cmd}")
    except Exception as e:
        print(f"  ✗ Could not add to startup: {e}")


def init_db():
    step("Initializing database")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import db
        db.init_db()
        from pathlib import Path as P
        import os
        db_path = P(os.getenv("APPDATA", ".")) / "WorkSpaceManager" / "workspace.db"
        print(f"  ✓ Database initialized at: {db_path}")
    except Exception as e:
        print(f"  ✗ DB init failed: {e}")


def main():
    print("""
╔══════════════════════════════════════════════╗
║          WorkSpace Manager — Setup           ║
║  Mac-inspired session manager for Windows    ║
╚══════════════════════════════════════════════╝
""")

    install_deps()
    init_db()
    setup_native_host()
    add_to_startup()

    print(f"""
{'═'*50}
  ✓ Setup complete!

  To start WorkSpace Manager:
    python main.py

  Or double-click main.py if .py files open with Python.

  Chrome Extension:
    - Open chrome://extensions/
    - Enable Developer Mode
    - Click Load Unpacked → select chrome_extension/
    - Then run: python native_host/install_host.py
      (follow the instructions to add your extension ID)
{'═'*50}
""")


if __name__ == "__main__":
    main()

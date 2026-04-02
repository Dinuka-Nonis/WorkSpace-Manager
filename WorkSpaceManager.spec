# WorkSpaceManager.spec
# Builds the final single WorkSpaceManager.exe.
# workspace_host.exe (built by host.spec) is embedded inside it.
#
# Build order:
#   1. pyinstaller host.spec --distpath dist_host --workpath build_host --noconfirm
#   2. pyinstaller WorkSpaceManager.spec --noconfirm
#
# Final output:  dist\WorkSpaceManager.exe

import sys
import os
from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

# Path to the host exe built in step 1 above
HOST_EXE = os.path.join('dist_host', 'workspace_host.exe')

if not os.path.exists(HOST_EXE):
    raise FileNotFoundError(
        f"\n\nworkspace_host.exe not found at: {HOST_EXE}\n"
        "Build it first with:\n"
        "  pyinstaller host.spec --distpath dist_host --workpath build_host --noconfirm\n"
    )

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Embed workspace_host.exe — extracted to %APPDATA% on first launch
        (HOST_EXE, '.'),
    ],
    hiddenimports=[
        # PyQt6 — core modules PyInstaller sometimes misses
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
        # Windows-specific
        'win32api',
        'win32con',
        'win32gui',
        'win32process',
        'win32com',
        'win32com.client',
        'winreg',
        'comtypes',
        'comtypes.client',
        # Project modules
        'db',
        'restore',
        'core.drag_watcher',
        'core.launcher',
        'core.app_registry',
        'ui.drop_zone',
        'ui.wallet_panel',
        'native_host.install_host',
        'native_host.host',
        # Third-party
        'psutil',
        'keyboard',
        'sqlite3',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Qt modules your app does NOT use — each one saves 5–15 MB
        'PyQt6.QtNetwork',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebChannel',
        'PyQt6.QtMultimedia',
        'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtBluetooth',
        'PyQt6.QtNfc',
        'PyQt6.QtLocation',
        'PyQt6.QtPositioning',
        'PyQt6.QtRemoteObjects',
        'PyQt6.QtSensors',
        'PyQt6.QtSerialPort',
        'PyQt6.Qt3DCore',
        'PyQt6.Qt3DRender',
        'PyQt6.Qt3DInput',
        'PyQt6.Qt3DLogic',
        'PyQt6.Qt3DAnimation',
        'PyQt6.Qt3DExtras',
        'PyQt6.QtCharts',
        'PyQt6.QtDataVisualization',
        'PyQt6.QtOpenGL',
        'PyQt6.QtOpenGLWidgets',
        'PyQt6.QtPdf',
        'PyQt6.QtPdfWidgets',
        'PyQt6.QtSql',
        'PyQt6.QtTest',
        'PyQt6.QtXml',
        'PyQt6.QtDesigner',
        'PyQt6.QtHelp',
        # Heavy stdlib you don't use
        'unittest',
        'email',
        'html',
        'http',
        'xmlrpc',
        'pydoc',
        'doctest',
        'difflib',
        'tarfile',
        'logging.handlers',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WorkSpaceManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        # These DLLs break when UPX-compressed — always exclude them
        'vcruntime140.dll',
        'vcruntime140_1.dll',
        'msvcp140.dll',
        'python3*.dll',
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
    ],
    runtime_tmpdir=None,
    console=False,      # No console window — this is a background tray app
    windowed=True,
    icon=None,          # Replace with: icon='assets/icon.ico'
    disable_windowed_traceback=False,
    target_arch=None,
    version=None,       # Replace with a version file path if needed
)

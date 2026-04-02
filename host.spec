# host.spec
# Builds workspace_host.exe — the Chrome native messaging bridge.
# Run FIRST before building WorkSpaceManager.spec.
#
# Command:
#   pyinstaller host.spec --distpath dist_host --workpath build_host --noconfirm

import sys
from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

a = Analysis(
    ['native_host/host.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'psutil',
        'db',
        'sqlite3',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # No UI in the host — exclude all Qt
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtWidgets',
        'PyQt6.QtGui',
        # Heavy stdlib not used by host.py
        'unittest',
        'email',
        'html',
        'http',
        'urllib',
        'xml',
        'xmlrpc',
        'pydoc',
        'doctest',
        'difflib',
        'inspect',
        'tokenize',
        'ast',
        'dis',
        'opcode',
        'pickletools',
        'tarfile',
        'zipfile',
        'gzip',
        'bz2',
        'lzma',
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
    name='workspace_host',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # MUST be True — Chrome communicates via stdin/stdout
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

"""Small, independent PyInstaller executable used only for atomic updates."""

import os
import sys

WINDOWS = sys.platform == "win32"
ROOT = os.path.dirname(SPECPATH)

analysis = Analysis(
    [os.path.join(SPECPATH, "helper_entry.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[],
    hiddenimports=["pitrac_easy_connect.companion.self_update", "psutil"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["webview", "tkinter", "unittest", "pydoc", "test", "PIL", "numpy"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
helper = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="PiTrac Updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

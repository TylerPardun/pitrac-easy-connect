# PyInstaller specification for the PiTrac app.
#
# Builds for whichever platform it runs on: a .exe on Windows, a .app on macOS.
# PyInstaller bundles the interpreter of the machine it runs on, so a Windows
# build needs a Windows machine — there is no cross-compiling this.
#
#   python -m PyInstaller packaging/PiTracCompanion.spec

import os
import sys

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

# SPECPATH is injected by PyInstaller and is the directory holding this file.
# Paths are derived from it so the build works from any working directory.
ROOT = os.path.dirname(SPECPATH)
ICON = os.path.join(SPECPATH, "icon", "PiTrac.ico" if WINDOWS else "PiTrac.icns")

analysis = Analysis(
    [os.path.join(SPECPATH, "companion_entry.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[],
    # PyInstaller cannot see these through the runtime lookups in the service,
    # so they are named explicitly.
    hiddenimports=[
        "pitrac_easy_connect.companion.service",
        "pitrac_easy_connect.companion.web",
        "pitrac_easy_connect.companion.page",
        "pitrac_easy_connect.companion.link_client",
        "pitrac_easy_connect.companion.simulator_session",
        "pitrac_easy_connect.companion.shotlog",
        "pitrac_easy_connect.companion.window",
        "pitrac_easy_connect.common.discovery",
        "pitrac_easy_connect.common.pairing_exchange",
        "pitrac_easy_connect.common.updates",
        "pitrac_easy_connect.common.versions",
        "pitrac_easy_connect.pi.pairing",
        "pitrac_easy_connect.pi.pitrac",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing here draws with a GUI toolkit; the interface is a web page in an
    # application window. Excluding these keeps the download small.
    excludes=["tkinter", "unittest", "pydoc", "test", "PIL", "numpy"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="PiTrac",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No console window: the interface is the app window.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON if os.path.exists(ICON) else None,
)

if MACOS:
    app = BUNDLE(
        executable,
        name="PiTrac.app",
        icon=ICON if os.path.exists(ICON) else None,
        bundle_identifier="com.pitrac.easyconnect",
        info_plist={
            "CFBundleName": "PiTrac",
            "CFBundleDisplayName": "PiTrac",
            "CFBundleShortVersionString": os.environ.get("PITRAC_VERSION", "0.2.0"),
            "CFBundleVersion": os.environ.get("PITRAC_VERSION", "0.2.0"),
            "NSHighResolutionCapable": True,
            # It talks to the enclosure over plain HTTP on the local network,
            # which macOS blocks by default without this.
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            "NSLocalNetworkUsageDescription":
                "PiTrac finds your launch monitor on your local network.",
            "LSMinimumSystemVersion": "11.0",
        },
    )

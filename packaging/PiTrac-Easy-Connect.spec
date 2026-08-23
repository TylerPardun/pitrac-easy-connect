# PyInstaller specification for the PiTrac app.
#
# Builds for whichever platform it runs on: a .exe on Windows, a .app on macOS,
# and a native ELF executable using WebKitGTK on Linux.
# PyInstaller bundles the interpreter of the machine it runs on, so a Windows
# build needs a Windows machine — there is no cross-compiling this.
#
#   python -m PyInstaller packaging/PiTrac-Easy-Connect.spec

import os
import sys

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")

# SPECPATH is injected by PyInstaller and is the directory holding this file.
# Paths are derived from it so the build works from any working directory.
ROOT = os.path.dirname(SPECPATH)

# The package is the one place a version is written. build-app.sh passes it in;
# this reads it directly when the spec is run on its own.
def _version():
    if os.environ.get("PITRAC_VERSION"):
        return os.environ["PITRAC_VERSION"]
    import re as _re
    source = open(os.path.join(ROOT, "src", "pitrac_easy_connect", "__init__.py")).read()
    return _re.search(r'__version__ = "([^"]+)"', source).group(1)

VERSION = _version()


def _require_licences():
    path = os.path.join(ROOT, "THIRD-PARTY-LICENCES.txt")
    if not os.path.exists(path):
        raise SystemExit(
            "THIRD-PARTY-LICENCES.txt is missing. The native builds bundle "
            "third-party code and must carry its licence texts.\n"
            "Run: python3 packaging/collect-licences.py"
        )
    return path
ICON = os.path.join(
    SPECPATH, "icon", "PiTrac.ico" if WINDOWS else ("PiTrac.icns" if MACOS else "icon.png")
)

# pywebview draws the window with the platform's own browser engine — WKWebView
# on macOS, WebView2 on Windows — which is what makes this a real app rather
# than a browser in disguise. Its platform backend is chosen at runtime, so
# PyInstaller cannot see it and it has to be named here.
WINDOW_IMPORTS = ["webview"]
if MACOS:
    WINDOW_IMPORTS += ["webview.platforms.cocoa"]
elif WINDOWS:
    WINDOW_IMPORTS += ["webview.platforms.edgechromium", "clr_loader", "pythonnet"]
elif LINUX:
    WINDOW_IMPORTS += ["webview.platforms.gtk", "gi", "gi.repository.Gtk", "gi.repository.WebKit2"]

analysis = Analysis(
    [os.path.join(SPECPATH, "app_entry.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    # The native builds bundle third-party code, so they carry its licences.
    # NOTICE.md says so; this is what makes that true.
    datas=[
        (os.path.join(ROOT, "LICENSE"), "."),
        (os.path.join(ROOT, "NOTICE.md"), "."),
        # Not optional. A bundled component without its licence text is a
        # compliance problem, so the build stops rather than shipping without.
        (_require_licences(), "."),
    ],
    # PyInstaller cannot see these through the runtime lookups in the service,
    # so they are named explicitly.
    hiddenimports=[
        "pitrac_easy_connect.companion.service",
        "pitrac_easy_connect.companion.web",
        "pitrac_easy_connect.companion.page",
        "pitrac_easy_connect.companion.link_client",
        "pitrac_easy_connect.companion.simulator_session",
        "pitrac_easy_connect.companion.shotlog",
        "pitrac_easy_connect.companion.flight",
        "pitrac_easy_connect.companion.rangeplay",
        "pitrac_easy_connect.companion.window",
        "pitrac_easy_connect.common.discovery",
        "pitrac_easy_connect.common.pairing_exchange",
        "pitrac_easy_connect.common.updates",
        "pitrac_easy_connect.common.versions",
        "pitrac_easy_connect.pi.pairing",
        "pitrac_easy_connect.pi.pitrac",
    ] + WINDOW_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing here draws with a GUI toolkit, and the window loads a URL from
    # our own loopback server rather than using pywebview's built-in one. That
    # optional server drags in a web framework, a template engine, an event
    # loop and a TLS stack, none of which this program ever calls.
    #
    # Cutting them is not only about size. Every bundled package is a licence
    # to honour in a binary that gets distributed, and `readline` in particular
    # is GPL-3: shipping it inside a proprietary or MIT binary is a problem
    # that does not need to exist, since a windowed app has no use for a
    # terminal line editor.
    excludes=[
        "tkinter", "unittest", "pydoc", "test", "PIL", "numpy",
        "readline", "curses", "_curses",
        "cryptography", "OpenSSL",
        # NOT bottle: pywebview imports it while loading even though this app
        # supplies its own loopback server.
        "tornado", "jinja2", "markupsafe",
        "uvloop", "colorama",
        # distutils is NOT excluded: PyInstaller's own pre-safe-import hook
        # raises if it has been, which broke every Windows build.
        "pdb", "doctest", "lib2to3",
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

if MACOS:
    # A onefile executable inside a .app launches a bootloader application and
    # then a second extracted application. macOS registers both; PyInstaller
    # explicitly warns that this layout is invalid. A normal onedir COLLECT is
    # the supported bundle shape and leaves one foreground application.
    executable = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name="PiTrac Easy-Connect",
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
        icon=ICON if os.path.exists(ICON) else None,
    )
    collected = COLLECT(
        executable,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        name="PiTrac Easy-Connect",
    )
    app = BUNDLE(
        collected,
        name="PiTrac Easy-Connect.app",
        icon=ICON if os.path.exists(ICON) else None,
        bundle_identifier="com.pitrac.easyconnect",
        info_plist={
            "CFBundleName": "PiTrac Easy-Connect",
            "CFBundleDisplayName": "PiTrac Easy-Connect",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            # It talks to the enclosure over plain HTTP on the local network,
            # which macOS blocks by default without this.
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            "NSLocalNetworkUsageDescription":
                "PiTrac Easy-Connect finds your launch monitor on your local network.",
            # Launch Services should route a second normal application launch
            # back to the existing process. The authenticated loopback
            # activation endpoint handles direct executable launches too.
            "LSMultipleInstancesProhibited": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
else:
    # Windows intentionally remains onefile. Linux retains its existing native
    # single executable as well; neither platform wraps that executable in a
    # second application bundle.
    executable = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name="PiTrac Easy-Connect",
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

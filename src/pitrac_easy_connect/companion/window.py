"""The application window.

Three ways of putting the interface on screen, tried in order:

1. **A native window** through pywebview — WKWebView on macOS, WebView2 on
   Windows. This is a real application: its own icon in the dock or taskbar, its
   own menu bar, and it closes like anything else. This is what a packaged build
   uses.
2. **A browser in application mode** (``--app=``), which looks close but is
   still the browser: it borrows the browser's dock icon and menu bar. Kept as a
   fallback for machines where the native backend will not load.
3. **An ordinary browser tab**, so the interface is never simply unreachable.

The native backend is an optional import. The Raspberry Pi service must never
depend on it, and a PC without it should degrade rather than fail.
"""

import os
import shutil
import subprocess
import sys
import webbrowser
from typing import List, Optional

#: Browsers that support application mode, in preference order. Edge first on
#: Windows because it is always present there.
_CANDIDATES = {
    "nt": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "msedge",
        "chrome",
    ],
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "posix": [
        "microsoft-edge", "microsoft-edge-stable",
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    ],
}


def native_available() -> bool:
    """Whether a real application window can be drawn on this machine."""

    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True


def run_native(url: str, title: str = "PiTrac Easy-Connect", width: int = 480, height: int = 900) -> bool:
    """Open a native window and block until the user closes it.

    Must be called on the main thread: the macOS and Windows toolkits both
    require it. Returns False if a native window could not be created, so the
    caller can fall back rather than leaving the user with nothing.
    """

    try:
        import webview
    except Exception:
        return False

    try:
        webview.create_window(title, url, width=width, height=height, min_size=(380, 560))
        webview.start()
        return True
    except Exception:
        return False


def _candidates() -> List[str]:
    if os.name == "nt":
        return _CANDIDATES["nt"]
    if sys.platform == "darwin":
        return _CANDIDATES["darwin"] + _CANDIDATES["posix"]
    return _CANDIDATES["posix"]


def find_browser() -> Optional[str]:
    for candidate in _candidates():
        if os.path.sep in candidate or (os.name == "nt" and ":" in candidate):
            if os.path.isfile(candidate):
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


def open_window(url: str, width: int = 480, height: int = 900) -> bool:
    """Open the interface in an application-mode browser window.

    Returns whether a chromeless window was opened, so the caller can say
    something useful when it could not be.
    """

    browser = find_browser()
    if browser is None:
        webbrowser.open(url)
        return False

    # A profile of its own keeps this out of the user's browsing session and
    # stops it inheriting or disturbing their tabs.
    profile = os.path.join(os.path.expanduser("~"), ".pitrac-easy-connect", "window-profile")
    try:
        os.makedirs(profile, exist_ok=True)
    except OSError:
        profile = ""

    command = [browser, "--app={}".format(url), "--window-size={},{}".format(width, height)]
    if profile:
        command.append("--user-data-dir={}".format(profile))

    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=(os.name != "nt"),
        )
        return True
    except OSError:
        webbrowser.open(url)
        return False

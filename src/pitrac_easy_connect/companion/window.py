"""Opening the Companion as a window rather than a browser tab.

Modern browsers can open a page as a standalone application window: no tabs, no
address bar, its own taskbar entry and icon. That is what ``--app=`` does, and it
gets us an app-shaped window without bundling a browser engine or adding a
dependency.

It is a stepping stone rather than the end state. A packaged release should use
a native window, but this is testable today on any machine and behaves the same
way from the user's point of view.
"""

import os
import shutil
import subprocess
import sys
import webbrowser
from typing import List, Optional

#: Browsers that support application mode, in the order we would rather use.
#: Edge first on Windows because it is always present there.
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


def open_window(url: str, width: int = 460, height: int = 820) -> bool:
    """Open ``url`` as an application window. Falls back to a normal tab.

    Returns whether an application window was opened, so the caller can say
    something useful when it could not be.
    """

    browser = find_browser()
    if browser is None:
        webbrowser.open(url)
        return False

    # A profile of its own keeps this window out of the user's browsing session
    # and stops it inheriting or disturbing their tabs.
    profile = os.path.join(
        os.path.expanduser("~"), ".pitrac-easy-connect", "window-profile"
    )
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

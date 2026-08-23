"""The application window.

Two ways of putting the interface on screen:

1. **A native window** through pywebview — WKWebView on macOS, WebView2 on
   Windows. This is a real application: its own icon in the dock or taskbar,
   its own menu bar, and it closes like anything else. This is what the
   packaged builds use, and what almost everybody will see.
2. **An ordinary browser tab**, when there is no native backend — which in
   practice means the portable ``.pyz``, since it bundles nothing.

There used to be a third way in between: a browser launched in application
mode with ``--app=``, given its own profile directory. It was written before
the native window worked and kept afterwards as a fallback, and all it
actually achieved was putting a second Chrome on screen wearing Chrome's icon
and Chrome's menu bar. Somebody looking at that reasonably asks why a desktop
application is opening a browser. It is gone.

The native backend is an optional import. The Raspberry Pi service must never
depend on it, and a computer without it should degrade rather than fail.
"""

import webbrowser
from typing import Optional

#: Why the last attempt at a native window did not happen. Read by the caller
#: so the fallback can say what went wrong instead of only that it went wrong.
#:
#: This exists because the silence hid a real bug for a whole release: the
#: packaged builds excluded a module pywebview imports, `import webview`
#: raised, every exception here was swallowed, and every packaged app quietly
#: opened a browser. Nothing anywhere said why.
last_failure: Optional[str] = None


def _describe(exc: BaseException) -> str:
    return "{}: {}".format(type(exc).__name__, exc)


def native_available() -> bool:
    """Whether a real application window can be drawn on this machine."""

    global last_failure
    try:
        import webview  # noqa: F401
    except Exception as exc:
        last_failure = "the window backend could not be loaded ({})".format(_describe(exc))
        return False
    last_failure = None
    return True


def run_native(url: str, title: str = "PiTrac Easy-Connect",
               width: int = 480, height: int = 900) -> bool:
    """Open the interface in a window of its own, and block until it closes.

    Must be called on the main thread: the macOS and Windows toolkits both
    require it. Returns False if no native backend could be started, so the
    caller can fall back rather than leaving the user with nothing -- and sets
    ``last_failure`` to the reason, so the fallback is explicable.
    """

    global last_failure
    try:
        import webview
    except Exception as exc:
        last_failure = "the window backend could not be loaded ({})".format(_describe(exc))
        return False
    try:
        webview.create_window(title, url, width=width, height=height,
                              min_size=(380, 560))
        webview.start()
        last_failure = None
        return True
    except Exception as exc:
        last_failure = "the window would not open ({})".format(_describe(exc))
        return False


def open_in_browser(url: str) -> bool:
    """Last resort: hand the interface to whatever browser is set up.

    Honest about what it is. No separate profile, no application mode, no
    pretending a browser tab is an application.
    """

    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False

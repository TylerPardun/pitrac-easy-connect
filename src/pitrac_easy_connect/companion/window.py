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


def native_available() -> bool:
    """Whether a real application window can be drawn on this machine."""

    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True


def run_native(url: str, title: str = "PiTrac Easy-Connect",
               width: int = 480, height: int = 900) -> bool:
    """Open the interface in a window of its own, and block until it closes.

    Must be called on the main thread: the macOS and Windows toolkits both
    require it. Returns False if no native backend could be started, so the
    caller can fall back rather than leaving the user with nothing.
    """

    try:
        import webview
    except Exception:
        return False
    try:
        webview.create_window(title, url, width=width, height=height,
                              min_size=(380, 560))
        webview.start()
        return True
    except Exception:
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

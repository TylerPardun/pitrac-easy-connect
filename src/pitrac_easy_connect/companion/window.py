"""The operating-system window used by every desktop launch."""

from typing import Callable, Optional


class NativeWindowError(RuntimeError):
    """The embedded window backend could not create or run a window."""


def _describe(exc: BaseException) -> str:
    return "{}: {}".format(type(exc).__name__, exc)


def run_native(
    url: str,
    title: str = "PiTrac Easy-Connect",
    width: int = 480,
    height: int = 900,
    on_created: Optional[Callable[[], None]] = None,
    on_activation_ready: Optional[Callable[[Callable[[], None]], None]] = None,
    on_close_ready: Optional[Callable[[Callable[[], None]], None]] = None,
    on_started: Optional[Callable[[], None]] = None,
) -> None:
    """Create the native window and block until the user closes it.

    pywebview must own the main thread on every supported platform. Its start
    callback runs only after the GUI loop has created the platform window; that
    is when callers may report the lifecycle as ``native``.
    """

    try:
        import webview
    except Exception as exc:
        raise NativeWindowError(
            "the native window backend could not be loaded ({})".format(_describe(exc))
        ) from exc

    try:
        # pywebview defaults target=_blank requests to the system browser.
        # Easy-Connect owns every desktop navigation itself, and this setting
        # makes the backend enforce that boundary even if future page markup
        # accidentally requests a new window.
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
        native_window = webview.create_window(
            title, url, width=width, height=height, min_size=(380, 560)
        )

        def shown() -> None:
            if on_created is not None:
                on_created()

        native_window.events.shown += shown

        def started() -> None:
            if on_activation_ready is not None:
                on_activation_ready(lambda: _bring_to_front(native_window))
            if on_close_ready is not None:
                on_close_ready(native_window.destroy)
            # On macOS, start the HTTP serving loop from pywebview's managed
            # worker after AppKit has initialized. Starting it before AppKit
            # enters its run loop leaves the listener bound but its Python
            # thread unable to run in an onedir bundle, producing a blank UI.
            if on_started is not None:
                on_started()

        webview.start(started)
    except Exception as exc:
        raise NativeWindowError(
            "the native window could not be created ({})".format(_describe(exc))
        ) from exc


def _bring_to_front(native_window) -> None:
    """Restore and activate the one window without opening a browser."""

    # ``restore`` handles a minimized window and ``show`` handles a hidden
    # one. Calling both is harmless for an already visible window and keeps the
    # implementation on pywebview's native backends on all three platforms.
    native_window.restore()
    native_window.show()

    # macOS may keep another application active even after its window has been
    # restored. pywebview already bundles PyObjC for WKWebView, so activate the
    # current application directly rather than shelling out to ``open`` (which
    # could create another application process).
    import sys

    if sys.platform == "darwin":
        from AppKit import NSApplication

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

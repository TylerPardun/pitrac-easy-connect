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
                on_close_ready(lambda: _close_native(native_window))
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


def _close_native(native_window) -> None:
    """Close without blocking a Windows request thread on WinForms.

    pywebview's Windows ``destroy`` wrapper uses synchronous ``Control.Invoke``.
    Calling that wrapper from the updater's timer can leave the form blank but
    keep both the WinForms process and the HTTP request alive. Posting the same
    ``WM_CLOSE`` message produced by Alt-F4 is asynchronous and lets the native
    UI thread own its normal shutdown sequence.
    """

    import sys

    if sys.platform == "win32":
        _post_windows_close(native_window)
        return
    native_window.destroy()


def _post_windows_close(native_window, post_message=None) -> None:
    instance = native_window.gui.BrowserView.instances.get(native_window.uid)
    if instance is None:
        return
    handle = int(instance.Handle.ToInt64())
    if post_message is None:
        from ctypes import windll

        post_message = windll.user32.PostMessageW
    if not post_message(handle, 0x0010, 0, 0):  # WM_CLOSE
        raise OSError("Windows refused the native close message")


def _bring_to_front(native_window) -> None:
    """Restore and activate the one window without opening a browser."""

    import sys

    if sys.platform.startswith("linux"):
        # pywebview's public Window methods wait on its ``shown`` event before
        # forwarding to GTK.  When they are called by our loopback HTTP worker
        # that wait can stall the activation response even though the GTK
        # window is already visible.  The GTK backend entry points are exactly
        # the thread-safe queue used by those methods (both dispatch through
        # GLib.idle_add), without the redundant cross-thread wait.
        native_window.gui.restore(native_window.uid)
        native_window.gui.show(native_window.uid)
        return

    # ``restore`` handles a minimized window and ``show`` handles a hidden
    # one. Calling both is harmless for an already visible window and keeps the
    # implementation on pywebview's native backends on all three platforms.
    native_window.restore()
    native_window.show()

    # macOS may keep another application active even after its window has been
    # restored. pywebview already bundles PyObjC for WKWebView, so activate the
    # current application directly rather than shelling out to ``open`` (which
    # could create another application process).
    if sys.platform == "darwin":
        from AppKit import NSApplication

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

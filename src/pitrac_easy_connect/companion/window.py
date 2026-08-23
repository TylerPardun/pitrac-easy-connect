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
        webview.create_window(title, url, width=width, height=height, min_size=(380, 560))
        webview.start(on_created)
    except Exception as exc:
        raise NativeWindowError(
            "the native window could not be created ({})".format(_describe(exc))
        ) from exc

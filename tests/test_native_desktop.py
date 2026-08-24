"""The installed desktop has one window path and explicit lifecycle states."""

from pathlib import Path
import threading

import pytest

from pitrac_easy_connect.companion import app, window
from pitrac_easy_connect.companion.service import CompanionService


def test_each_window_lifecycle_state_is_reported(tmp_path):
    service = CompanionService(config_path=tmp_path / "c.json", discovery_port=0)
    try:
        assert service.window_state() == {"state": "starting", "detail": None}
        for state in ("native", "headless"):
            service.set_window_state(state)
            assert service.window_state() == {"state": state, "detail": None}
        service.set_window_state("failed", "WebKit is missing")
        assert service.window_state() == {"state": "failed", "detail": "WebKit is missing"}
    finally:
        service.close()


def test_native_is_reported_only_after_the_creation_callback(tmp_path, monkeypatch):
    service = CompanionService(config_path=tmp_path / "c.json", discovery_port=0)
    seen = []
    focused = threading.Event()

    def create(_url, on_created, on_activation_ready, on_close_ready, on_started):
        seen.append(service.window_state()["state"])
        on_activation_ready(lambda: (seen.append("focused"), focused.set()))
        on_close_ready(lambda: seen.append("closed"))
        assert on_started is None
        on_created()
        seen.append(service.window_state()["state"])

    monkeypatch.setattr(window, "run_native", create)
    try:
        assert app._show_native(service, "http://127.0.0.1:1") == 0
        assert seen == ["starting", "native"]
        service.activate_window()
        assert focused.wait(1)
        assert seen[-1] == "focused"
        service.close_native_window()
        assert seen[-1] == "closed"
    finally:
        service.close()


def test_restart_acknowledgement_waits_until_native_window_is_shown(tmp_path, monkeypatch):
    service = CompanionService(config_path=tmp_path / "c.json", discovery_port=0)
    seen = []

    def create(_url, on_created, on_activation_ready, on_close_ready, on_started):
        seen.append("creating")
        on_created()
        seen.append("shown")

    monkeypatch.setattr(window, "run_native", create)
    try:
        assert app._show_native(
            service, "http://127.0.0.1:1", on_ready=lambda: seen.append("acknowledged")
        ) == 0
        assert seen == ["creating", "acknowledged", "shown"]
        assert service.window_state()["state"] == "native"
    finally:
        service.close()


def test_native_start_failure_is_visible_retained_and_unsuccessful(tmp_path, monkeypatch):
    service = CompanionService(config_path=tmp_path / "c.json", discovery_port=0)
    messages = []

    def fail(*_args, **_kwargs):
        raise window.NativeWindowError("GTK could not connect to the display")

    monkeypatch.setattr(window, "run_native", fail)
    monkeypatch.setattr(app, "_say_it_failed", messages.append)
    try:
        assert app._show_native(service, "http://127.0.0.1:1") == 1
        assert service.window_state() == {
            "state": "failed", "detail": "GTK could not connect to the display"
        }
        assert "GTK could not connect" in messages[0]
    finally:
        service.close()


def test_desktop_source_has_no_browser_launch_path():
    root = Path(__file__).resolve().parent.parent
    script = root / "packaging" / "check-native-only.py"
    namespace = {"__file__": str(script), "__name__": "native_check"}
    exec(compile(script.read_text(), str(script), "exec"), namespace)
    assert namespace["main"]() == 0


def test_pywebview_is_configured_never_to_open_external_links():
    source = Path(window.__file__).read_text()
    assert 'settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False' in source


def test_linux_activation_queues_directly_on_gtk(monkeypatch):
    calls = []

    class Gui:
        def restore(self, uid):
            calls.append(("restore", uid))

        def show(self, uid):
            calls.append(("show", uid))

    class Native:
        uid = "main-window"
        gui = Gui()

        def restore(self):
            raise AssertionError("the blocking pywebview wrapper was used")

        def show(self):
            raise AssertionError("the blocking pywebview wrapper was used")

    monkeypatch.setattr("sys.platform", "linux")
    window._bring_to_front(Native())

    assert calls == [("restore", "main-window"), ("show", "main-window")]


def test_windows_close_posts_the_normal_nonblocking_window_message():
    calls = []

    class Handle:
        def ToInt64(self):
            return 12345

    instance = type("Instance", (), {"Handle": Handle()})()
    browser_view = type("BrowserView", (), {"instances": {"main-window": instance}})
    gui = type("Gui", (), {"BrowserView": browser_view})()
    native = type("Native", (), {"uid": "main-window", "gui": gui})()

    window._post_windows_close(
        native, post_message=lambda handle, message, wparam, lparam: calls.append(
            (handle, message, wparam, lparam)
        ) or 1,
    )

    assert calls == [(12345, 0x0010, 0, 0)]


def test_removed_browser_options_are_rejected():
    parser = app.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--no-browser"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--window"])


# --- The shape of the window -----------------------------------------------
#
# The window opened at 480x900: a tall narrow strip, the shape of a phone. On a
# desktop it wastes most of the screen and forces every pane into one column,
# which is what pushed the range and the shot history behind a tab bar instead
# of being visible. The size is part of what the app is, so it is pinned here.

#: A 1280x800 laptop is the smallest screen this is expected to run on, and the
#: window has to fit inside it with room for the menu bar and the dock.
SMALLEST_SCREEN = (1280, 800)


def _geometry_used(**overrides):
    """The width, height and minimum the window is actually created with."""

    captured = {}

    class FakeWindow:
        uid = "main-window"
        events = type("Events", (), {"shown": type("Slot", (), {
            "__iadd__": lambda self, other: self,
        })()})()

    class FakeWebview:
        settings = {}

        @staticmethod
        def create_window(title, url, width, height, min_size):
            captured.update(title=title, url=url, width=width, height=height,
                            min_size=min_size)
            return FakeWindow()

        @staticmethod
        def start(*_args, **_kwargs):
            return None

    import sys as _sys

    saved = _sys.modules.get("webview")
    _sys.modules["webview"] = FakeWebview
    try:
        window.run_native("http://127.0.0.1:1", **overrides)
    finally:
        if saved is None:
            _sys.modules.pop("webview", None)
        else:
            _sys.modules["webview"] = saved
    return captured


def test_the_window_opens_in_a_desktop_shape_not_a_phone_shape():
    used = _geometry_used()
    assert used["width"] > used["height"], (
        "the window opens taller than it is wide ({}x{}), which is a phone, "
        "not a desktop application".format(used["width"], used["height"])
    )


def test_the_window_is_wide_enough_for_more_than_one_column():
    used = _geometry_used()
    assert used["width"] >= 1024, (
        "a {}px window cannot show a dashboard beside anything else"
        .format(used["width"])
    )


def test_the_window_still_fits_the_smallest_screen_it_supports():
    used = _geometry_used()
    screen_w, screen_h = SMALLEST_SCREEN
    assert used["width"] <= screen_w and used["height"] <= screen_h, (
        "a {}x{} window does not fit a {}x{} laptop"
        .format(used["width"], used["height"], screen_w, screen_h)
    )


def test_the_minimum_size_does_not_trap_a_small_screen():
    """A minimum larger than the screen makes the window unusable."""

    minimum = _geometry_used()["min_size"]
    screen_w, screen_h = SMALLEST_SCREEN
    assert minimum[0] <= screen_w and minimum[1] <= screen_h

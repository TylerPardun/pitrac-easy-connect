"""The installed desktop has one window path and explicit lifecycle states."""

from pathlib import Path

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

    def create(_url, on_created, on_activation_ready, on_close_ready, on_started):
        seen.append(service.window_state()["state"])
        on_activation_ready(lambda: seen.append("focused"))
        on_close_ready(lambda: seen.append("closed"))
        assert on_started is None
        on_created()
        seen.append(service.window_state()["state"])

    monkeypatch.setattr(window, "run_native", create)
    try:
        assert app._show_native(service, "http://127.0.0.1:1") == 0
        assert seen == ["starting", "native"]
        service.activate_window()
        assert seen[-1] == "focused"
        service.close_native_window()
        assert seen[-1] == "closed"
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


def test_removed_browser_options_are_rejected():
    parser = app.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--no-browser"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--window"])

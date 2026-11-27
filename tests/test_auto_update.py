"""Updates, in the one safe order.

This desktop goes first, to the latest release: it is fetched and verified as
soon as it is found, offered at the top of the startup page, and installed
when the person presses "Update now" -- installing restarts the app, so that
is their call. PiTrac then follows by itself, to exactly the version this
desktop runs; nobody has to touch the Pi. A failed attempt is left alone for
a while rather than retried on every step.
"""

import pytest

from pitrac_easy_connect.common.updates import DesktopUpdateState, UpdateStatus
from pitrac_easy_connect.companion.service import CompanionService

INSTALLED = "0.10.5"
NEWER = "0.10.6"


class Link:
    connected = True
    outdated_enclosure = None

    def status(self):
        return {"connected": self.connected}

    def stop(self):
        self.connected = False


@pytest.fixture
def app(tmp_path):
    service = CompanionService(
        tmp_path / "c.json", discovery_port=0, version=INSTALLED,
        startup_update_check=False, periodic_update_check_seconds=0,
        updates_published=True,
    )
    calls = []
    service.calls = calls
    # A packaged copy, which installs desktop releases (a source checkout
    # would pull with git instead, and has nothing to download).
    service.desktop_updates = object()
    service.prepare_update = lambda target: (calls.append(("prepare", target)) or {"prepared": True})
    service.download_desktop_update = lambda: calls.append(("download",)) or {"started": True}
    service.install_and_restart = lambda: calls.append(("install",)) or {"applied": True}
    service.apply_pi_update = lambda target: calls.append(("pi", target)) or {"started": True}
    yield service
    service.close()


def latest(service, version, enclosure=None):
    service._last_desktop_status = UpdateStatus(
        installed=service.version, kind="packaged", latest="v" + version,
        available=version != service.version,
    )
    if enclosure is not None:
        service._link = Link()
        service._pi_status = {"version": enclosure}


def test_a_newer_desktop_release_is_downloaded_without_asking(app):
    latest(app, NEWER, enclosure=INSTALLED)
    assert app.auto_update_step(now=1000.0) == "downloading"
    assert app.calls == [("prepare", NEWER), ("download",)]


def test_pitrac_is_never_sent_ahead_of_the_desktop(app):
    latest(app, NEWER, enclosure="0.10.4")
    app.auto_update_step(now=1000.0)
    assert not any(call[0] == "pi" for call in app.calls)


def test_a_ready_update_waits_for_update_now(app):
    latest(app, NEWER, enclosure=INSTALLED)
    app._desktop_update_state = DesktopUpdateState.READY_TO_RESTART
    assert app.auto_update_step(now=1000.0) == "ready-waiting-for-click"
    assert ("install",) not in app.calls


def test_update_now_installs_at_once_when_it_is_ready(app):
    latest(app, NEWER, enclosure=INSTALLED)
    app._desktop_update_state = DesktopUpdateState.READY_TO_RESTART
    app.update_now()
    assert app.calls == [("install",)]


def test_update_now_before_it_is_ready_fetches_it_and_installs_when_it_is(app):
    latest(app, NEWER, enclosure=INSTALLED)
    app.update_now()
    assert app.calls == [("prepare", NEWER), ("download",)]
    assert app._desktop_update_payload()["installWhenReady"] is True
    # The download finishing is what the next step sees.
    app._desktop_update_state = DesktopUpdateState.READY_TO_RESTART
    import time
    deadline = time.monotonic() + 5
    while ("install",) not in app.calls and time.monotonic() < deadline:
        time.sleep(0.05)
    assert ("install",) in app.calls


def test_nothing_interrupts_an_update_already_in_progress(app):
    latest(app, NEWER, enclosure=INSTALLED)
    app._desktop_update_state = DesktopUpdateState.DOWNLOADING
    assert app.auto_update_step(now=1000.0) == "busy"
    assert app.calls == []


def test_pitrac_follows_to_exactly_this_desktops_version(app):
    latest(app, INSTALLED, enclosure="0.10.4")
    assert app.auto_update_step(now=1000.0) == "updating-pitrac"
    assert app.calls == [("pi", INSTALLED)]


def test_pitrac_is_updated_only_while_it_is_connected(app):
    latest(app, INSTALLED, enclosure="0.10.4")
    app._link.connected = False
    assert app.auto_update_step(now=1000.0) in ("waiting-for-pitrac", "nothing-to-do")
    assert app.calls == []


def test_a_failed_attempt_is_retried_later_not_on_every_step(app):
    latest(app, INSTALLED, enclosure="0.10.4")
    app.apply_pi_update = lambda target: app.calls.append(("pi", target)) or {"started": False}
    assert app.auto_update_step(now=1000.0) == "pitrac-refused"
    assert app.auto_update_step(now=1000.0 + 60) == "waiting-to-retry"
    assert app.auto_update_step(now=1000.0 + app.AUTO_RETRY_SECONDS + 1) == "pitrac-refused"
    assert app.calls == [("pi", INSTALLED), ("pi", INSTALLED)]


def test_both_halves_on_the_same_version_is_left_alone(app):
    latest(app, INSTALLED, enclosure=INSTALLED)
    assert app.auto_update_step(now=1000.0) == "nothing-to-do"
    assert app.calls == []


def test_updates_turned_off_do_nothing(tmp_path):
    service = CompanionService(
        tmp_path / "c.json", discovery_port=0, startup_update_check=False,
        periodic_update_check_seconds=0, updates_published=False,
    )
    try:
        assert service.auto_update_step(now=1000.0) == "off"
    finally:
        service.close()


def test_the_app_installs_by_itself_only_when_asked_to(tmp_path, monkeypatch):
    """Constructing one -- as every test does -- must never start the autopilot."""

    started = []
    monkeypatch.setattr(CompanionService, "_auto_update_loop", lambda self: started.append(1))
    quiet = CompanionService(tmp_path / "a.json", discovery_port=0, startup_update_check=False,
                             periodic_update_check_seconds=0)
    on = CompanionService(tmp_path / "b.json", discovery_port=0, startup_update_check=False,
                          periodic_update_check_seconds=0, auto_update=True)
    try:
        import time
        time.sleep(0.2)
        assert started == [1]
    finally:
        quiet.close()
        on.close()

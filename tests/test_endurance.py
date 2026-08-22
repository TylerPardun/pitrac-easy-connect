"""The things that only go wrong after a while, or at the worst moment.

Everything here drives the real stack -- a simulated Raspberry Pi, the real
relay, the real paired link, the real companion, a stand-in simulator -- and
then does something unkind to it. What is being checked is not that nothing
goes wrong, but that what goes wrong is honest, bounded, and recoverable.
"""

import gc
import os
import threading
import time

import pytest

from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.service import PiService, ServicePaths
from pitrac_easy_connect.pi.simulated import home_network_pi
from test_companion import Rig, rig  # noqa: F401  (fixture)

SHOT = {
    "DeviceID": "PiTrac", "Units": "Yards", "ShotNumber": 1, "APIversion": "1",
    "BallData": {"Speed": 120.0, "SpinAxis": 3.0, "TotalSpin": 7100.0,
                 "BackSpin": 7097, "SideSpin": 300, "HLA": 1.2, "VLA": 16.3},
    "ShotDataOptions": {"ContainsBallData": True},
}


def descriptors() -> int:
    """Open file descriptors for this process, or 0 where that cannot be read."""

    try:
        return len(os.listdir("/dev/fd"))
    except OSError:
        return 0


# --- Soak ------------------------------------------------------------------


@pytest.mark.parametrize("shots", [400])
def test_a_long_session_does_not_leak(rig, shots):
    """Threads, descriptors and the shot history over a session far longer
    than anyone will actually hit.

    Four hundred rather than five thousand so the suite stays usable; the
    quantity that matters is the *slope*, and a leak shows in the first
    hundred as clearly as in the last.
    """

    rig.pair()
    assert rig.wait_linked() is True

    gc.collect()
    threads_before, fds_before = threading.active_count(), descriptors()

    for number in range(1, shots + 1):
        result = rig._forward(number) if hasattr(rig, "_forward") else \
            rig.companion._forward_shot(number, "gspro", dict(SHOT, ShotNumber=number))
        assert result.get("accepted") is True, "shot {} was refused".format(number)

    gc.collect()
    threads_after, fds_after = threading.active_count(), descriptors()

    assert threads_after - threads_before <= 2, \
        "threads grew from {} to {}".format(threads_before, threads_after)
    if fds_before:
        assert fds_after - fds_before <= 8, \
            "descriptors grew from {} to {}".format(fds_before, fds_after)

    # The histories are bounded, not unbounded lists that happen to be small.
    from pitrac_easy_connect.companion.shotlog import MAX_SHOTS
    assert len(rig.companion.shots.recent(10_000)) <= MAX_SHOTS
    assert rig.companion.range.status()["count"] <= 60


def test_the_range_stays_bounded_over_a_long_session(rig):
    rig.pair()
    assert rig.wait_linked() is True
    for number in range(200):
        rig.companion._forward_shot(number, "gspro", dict(SHOT, ShotNumber=number))
    status = rig.companion.range.status()
    assert status["count"] <= 60
    # And only a few shots carry their full trajectory.
    with_points = [s for s in status["shots"] if s["points"]]
    assert len(with_points) <= 12


# --- The simulator going away in the middle of a round ---------------------


def test_losing_the_simulator_reports_rather_than_hangs(rig):
    """A shot that cannot be delivered has to say so quickly. Hanging is worse
    than failing: the golfer is standing there."""

    rig.pair()
    assert rig.wait_linked() is True
    assert rig.companion._forward_shot(1, "gspro", SHOT)["accepted"] is True

    # A crashed simulator resets its connections. Merely closing the listening
    # socket leaves the established one open, which is not the failure being
    # tested here.
    rig.mock.drop_clients()
    rig.mock.stop()
    time.sleep(0.3)

    started = time.time()
    result = rig.companion._forward_shot(2, "gspro", dict(SHOT, ShotNumber=2))
    took = time.time() - started

    assert result.get("accepted") is not True, "it must not claim a delivery it did not make"
    assert took < 25, "reporting a lost shot took {:.0f}s".format(took)


def test_a_lost_shot_is_still_recorded_and_still_drawn(rig):
    """The golfer hit it. Losing the simulator does not mean losing the shot."""

    rig.pair()
    assert rig.wait_linked() is True
    rig.mock.drop_clients()
    rig.mock.stop()
    time.sleep(0.3)

    before = rig.companion.range.status()["count"]
    rig.companion._forward_shot(1, "gspro", SHOT)

    assert rig.companion.shots.recent(1), "it should be in the history"
    assert rig.companion.range.status()["count"] == before + 1, "and on the range"


def test_shots_are_never_replayed_when_the_simulator_returns(rig):
    """A golf shot that arrives twice is worse than one that never arrives."""

    rig.pair()
    assert rig.wait_linked() is True
    rig.mock.drop_clients()
    rig.mock.stop()
    time.sleep(0.3)
    for number in range(3):
        rig.companion._forward_shot(number, "gspro", dict(SHOT, ShotNumber=number))

    delivered_before = rig.companion.status()["shots"]["delivered"]
    time.sleep(1.0)
    assert rig.companion.status()["shots"]["delivered"] == delivered_before, \
        "nothing may be re-sent behind the golfer's back"


# --- Two computers, one enclosure -----------------------------------------


def test_a_second_computer_cannot_take_over_a_busy_enclosure(rig, tmp_path):
    """One enclosure serves one computer at a time, and says so plainly."""

    from pitrac_easy_connect.companion.service import CompanionService

    rig.pair()
    assert rig.wait_linked() is True

    intruder = CompanionService(
        config_path=tmp_path / "intruder.json",
        simulator_ports={Simulator.GSPRO: rig.mock.address[1]},
        discovery_port=rig.pi.discovery.port,
        computer_name="Someone else's laptop",
    )
    try:
        intruder.search(timeout=2.0)
        with pytest.raises(EasyConnectError) as caught:
            intruder.pair(rig.pi.identity.device_id, portal_port=rig.portal_port)
        assert caught.value.info.code == "PT-PAIR-001"
    finally:
        intruder.close()

    # And the first computer is untouched by the attempt.
    assert rig.companion.status()["link"]["connected"] is True
    assert rig.companion._forward_shot(1, "gspro", SHOT)["accepted"] is True


def test_the_owner_can_hand_the_enclosure_to_the_second_computer(rig, tmp_path):
    from pitrac_easy_connect.companion.service import CompanionService

    rig.pair()
    assert rig.wait_linked() is True
    rig.pi.pairings.open_window()

    second = CompanionService(
        config_path=tmp_path / "second.json",
        simulator_ports={Simulator.GSPRO: rig.mock.address[1]},
        discovery_port=rig.pi.discovery.port,
        computer_name="Kitchen laptop",
    )
    try:
        second.search(timeout=2.0)
        assert second.pair(rig.pi.identity.device_id,
                           portal_port=rig.portal_port)["deviceId"]
        assert rig.pi.pairings.count == 2
    finally:
        second.close()


# --- The card filling up ---------------------------------------------------


def test_a_nearly_full_card_is_reported_before_anything_breaks(tmp_path):
    backend = home_network_pi(country="US")
    backend.free_bytes = 200 * 1024**2          # 200 MB left
    service = PiService(
        backend,
        paths=ServicePaths(tmp_path / "state"),
        pitrac=PitracInstallation(tmp_path / "settings.json", tmp_path / "calibration.json"),
        relay_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
        link_port=0, discovery_port=0, manage_hostname=False, boot_grace=0.0,
    )
    try:
        service.start()
        report = service.selftest.run()
        storage = next(c for c in report.checks if c.key == "storage")
        assert storage.status != "pass"
        assert storage.error is not None and storage.error.code == "PT-PI-005"
        assert report.ready is False
    finally:
        service.stop()


# --- The clock being wrong -------------------------------------------------


def test_a_wrong_clock_is_named_rather_than_causing_a_confusing_failure(tmp_path):
    """A Pi with no battery-backed clock boots in 1970 until NTP catches up.
    Everything that checks a signature or a certificate fails strangely if
    nobody says why."""

    backend = home_network_pi(country="US")
    backend.clock_synchronized = False
    service = PiService(
        backend,
        paths=ServicePaths(tmp_path / "state"),
        pitrac=PitracInstallation(tmp_path / "settings.json", tmp_path / "calibration.json"),
        relay_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
        link_port=0, discovery_port=0, manage_hostname=False, boot_grace=0.0,
    )
    try:
        service.start()
        report = service.selftest.run()
        clock = next(c for c in report.checks if c.key == "clock")
        assert clock.status != "pass"
        assert clock.error is not None and clock.error.code == "PT-PI-008"
    finally:
        service.stop()


# --- The link dropping and coming back ------------------------------------


def test_the_link_survives_being_dropped_and_restored_repeatedly(rig):
    """A house network is not a lab. The link has to come back by itself,
    every time, without anyone pressing anything."""

    rig.pair()
    assert rig.wait_linked() is True

    for cycle in range(5):
        rig.companion.disconnect()
        assert rig.companion.status()["link"]["connected"] is False
        rig.companion.connect(rig.pi.identity.device_id)
        assert rig.wait_linked(timeout=10) is True, "cycle {} did not reconnect".format(cycle)
        assert rig.companion._forward_shot(cycle, "gspro", SHOT)["accepted"] is True


def test_an_idle_link_stays_up(rig):
    """Left alone against an idle enclosure, nothing should quietly die."""

    rig.pair()
    assert rig.wait_linked() is True
    threads_before = threading.active_count()

    time.sleep(6)          # several heartbeat intervals

    assert rig.companion.status()["link"]["connected"] is True
    assert threading.active_count() - threads_before <= 1
    assert rig.companion._forward_shot(1, "gspro", SHOT)["accepted"] is True

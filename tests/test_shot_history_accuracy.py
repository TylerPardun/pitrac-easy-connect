"""One swing is one entry, whatever the simulator's protocol looks like.

The relay has always known which message actually puts a ball in the air. The
history did not ask, so a GSPro heartbeat became a blank shot and one E6 swing
became four.
"""

from pitrac_easy_connect.models import Simulator
from test_companion import rig  # noqa: F401  (fixture)

GSPRO_SHOT = {
    "DeviceID": "PiTrac", "Units": "Yards", "ShotNumber": 1, "APIversion": "1",
    "BallData": {"Speed": 120.0, "SpinAxis": 3.0, "TotalSpin": 7100.0,
                 "BackSpin": 7097, "SideSpin": 300, "HLA": 1.2, "VLA": 16.3},
    "ShotDataOptions": {"ContainsBallData": True, "IsHeartBeat": False},
}
GSPRO_HEARTBEAT = {
    "DeviceID": "PiTrac", "Units": "Yards", "ShotNumber": 0, "APIversion": "1",
    "ShotDataOptions": {"ContainsBallData": False, "IsHeartBeat": True},
}
E6_SWING = [
    {"Type": "SetBallData",
     "BallData": {"BallSpeed": 118.0, "LaunchAngle": 17.2, "BackSpin": 6800,
                  "SideSpin": -250, "TotalSpin": 6805}},
    {"Type": "SetClubData", "ClubData": {"ClubHeadSpeed": 92.0}},
    {"Type": "SendShot"},
]


def test_a_gspro_heartbeat_is_not_a_shot(rig):
    rig.pair()
    assert rig.wait_linked() is True

    before = len(rig.companion.shots.recent(500))
    for _ in range(5):
        rig.companion._forward_shot(0, "gspro", GSPRO_HEARTBEAT)

    assert len(rig.companion.shots.recent(500)) == before, \
        "heartbeats were being written into the history as blank shots"
    assert rig.companion.range.status()["count"] == 0


def test_one_gspro_shot_is_one_entry(rig):
    rig.pair()
    assert rig.wait_linked() is True

    rig.companion._forward_shot(1, "gspro", GSPRO_SHOT)
    recent = rig.companion.shots.recent(10)
    assert len(recent) == 1
    assert recent[0]["speed"] == 120.0
    assert rig.companion.range.status()["count"] == 1


def test_one_e6_swing_is_one_entry_carrying_its_numbers(rig):
    """E6 needs three messages for one swing, and the numbers arrive before
    the instruction to hit."""

    rig.pair()
    assert rig.wait_linked() is True

    for message in E6_SWING:
        rig.companion._forward_shot(1, "e6", message)

    recent = rig.companion.shots.recent(10)
    assert len(recent) == 1, "one swing, one entry, got {}".format(len(recent))
    assert recent[0]["speed"] == 118.0, "the entry must carry the measurements"
    assert recent[0]["launch"] == 17.2
    assert rig.companion.range.status()["count"] == 1


def test_two_e6_swings_are_two_entries(rig):
    rig.pair()
    assert rig.wait_linked() is True

    for _ in range(2):
        for message in E6_SWING:
            rig.companion._forward_shot(1, "e6", message)

    assert len(rig.companion.shots.recent(10)) == 2
    assert rig.companion.range.status()["count"] == 2


def test_an_e6_swing_with_no_ball_data_is_not_invented(rig):
    """SendShot on its own carries nothing to record."""

    rig.pair()
    assert rig.wait_linked() is True
    rig.companion._forward_shot(1, "e6", {"Type": "SendShot"})

    recent = rig.companion.shots.recent(10)
    assert len(recent) == 1, "the swing happened, so it is recorded"
    assert recent[0].get("speed") in (None, 0), "but no numbers are invented for it"
    # Nothing flyable, so nothing is drawn on the range.
    assert rig.companion.range.status()["count"] == 0


def test_abandoned_e6_measurements_are_not_attached_to_a_later_swing(rig):
    """SetBallData without a SendShot is a swing that never completed. Holding
    it forever meant those numbers were handed to whatever came next."""

    rig.pair()
    assert rig.wait_linked() is True

    # Measurements arrive, then the swing is abandoned.
    rig.companion._forward_shot(1, "e6", E6_SWING[0])
    # The enclosure goes away and comes back.
    rig.companion.disconnect()
    rig.companion.connect(rig.pi.identity.device_id)
    assert rig.wait_linked(timeout=10) is True

    # A later, unrelated swing with no numbers of its own.
    rig.companion._forward_shot(2, "e6", {"Type": "SendShot"})

    recent = rig.companion.shots.recent(5)
    assert recent, "the swing is still recorded"
    assert recent[0].get("speed") in (None, 0), \
        "it must not carry measurements from the abandoned swing"


def test_changing_simulator_discards_half_gathered_measurements(rig):
    rig.pair()
    assert rig.wait_linked() is True

    rig.companion._forward_shot(1, "e6", E6_SWING[0])
    rig.companion.select_simulator("gspro")
    rig.companion.select_simulator("e6")
    rig.companion._forward_shot(2, "e6", {"Type": "SendShot"})

    recent = rig.companion.shots.recent(5)
    assert recent[0].get("speed") in (None, 0)


def test_measurements_that_wait_too_long_are_discarded(rig, monkeypatch):
    rig.pair()
    assert rig.wait_linked() is True

    rig.companion._forward_shot(1, "e6", E6_SWING[0])

    import time as _time

    later = _time.monotonic() + rig.companion.PENDING_BALL_SECONDS + 5
    monkeypatch.setattr(_time, "monotonic", lambda: later)
    rig.companion._forward_shot(2, "e6", {"Type": "SendShot"})

    recent = rig.companion.shots.recent(5)
    assert recent[0].get("speed") in (None, 0)

"""What happens when a real launch monitor is finally attached.

Everything so far has been built against the protocol and a stand-in. These
pin the assumptions that a real monitor could break, so that if it does, it
breaks loudly rather than quietly producing plausible nonsense.
"""

import pytest

from pitrac_easy_connect.companion import shotlog
from test_companion import rig  # noqa: F401  (fixture)

GSPRO = {
    "DeviceID": "PiTrac", "Units": "Yards", "ShotNumber": 1, "APIversion": "1",
    "BallData": {"Speed": 120.0, "SpinAxis": 3.0, "TotalSpin": 7100.0,
                 "BackSpin": 7097, "SideSpin": 300, "HLA": 1.2, "VLA": 16.3},
    "ShotDataOptions": {"ContainsBallData": True},
}


# --- Units -----------------------------------------------------------------


def test_the_expected_units_are_accepted_quietly():
    ball = shotlog.ball_from_shot(GSPRO)
    assert ball["unitsUnexpected"] is False


def test_units_we_have_never_seen_are_flagged_rather_than_guessed():
    """Silently converting would turn a wrong assumption into wrong numbers
    that look right. Saying so is the only honest option."""

    ball = shotlog.ball_from_shot(dict(GSPRO, Units="Meters"))
    assert ball["unitsUnexpected"] is True
    assert ball["units"] == "meters"


def test_a_message_with_no_units_is_not_treated_as_suspicious():
    payload = {k: v for k, v in GSPRO.items() if k != "Units"}
    assert shotlog.ball_from_shot(payload)["unitsUnexpected"] is False


# --- Field naming ----------------------------------------------------------


@pytest.mark.parametrize("alias,canonical", [
    ("BallSpeed", "Speed"), ("LaunchAngle", "VLA"), ("LaunchDirection", "HLA"),
])
def test_both_spellings_of_each_field_are_understood(alias, canonical):
    """GSPro and E6 name the same measurement differently, and PiTrac may use
    either."""

    ball = dict(GSPRO["BallData"])
    value = ball.pop(canonical)
    ball[alias] = value
    parsed = shotlog.ball_from_shot(dict(GSPRO, BallData=ball))
    assert parsed["speed"] is not None
    assert parsed["launch"] is not None
    assert parsed["direction"] is not None


def test_a_shot_missing_spin_still_parses():
    """A monitor that cannot measure spin should still produce a usable shot."""

    ball = {k: v for k, v in GSPRO["BallData"].items()
            if k not in ("BackSpin", "SideSpin", "TotalSpin")}
    parsed = shotlog.ball_from_shot(dict(GSPRO, BallData=ball))
    assert parsed["speed"] == 120.0
    assert parsed["backSpin"] is None


def test_unknown_extra_fields_are_ignored_not_fatal():
    ball = dict(GSPRO["BallData"], SomethingNew=1, Carry=210.5)
    assert shotlog.ball_from_shot(dict(GSPRO, BallData=ball))["speed"] == 120.0


# --- Keeping what actually arrived -----------------------------------------


def test_the_raw_message_is_kept_so_it_can_be_checked(rig):
    rig.pair()
    assert rig.wait_linked() is True

    rig.companion._forward_shot(1, "gspro", GSPRO)
    kept = rig.companion.raw_shots()

    assert kept["shots"], "the message should be kept exactly as it arrived"
    assert kept["shots"][-1]["message"] == GSPRO
    assert kept["unitsUnexpected"] is False


def test_odd_units_are_reported_by_the_diagnostic(rig):
    rig.pair()
    assert rig.wait_linked() is True

    rig.companion._forward_shot(1, "gspro", dict(GSPRO, Units="Meters"))
    kept = rig.companion.raw_shots()
    assert kept["unitsUnexpected"] is True
    assert "Meters" in kept["declaredUnits"]


def test_the_raw_window_does_not_grow_without_bound(rig):
    rig.pair()
    assert rig.wait_linked() is True
    for number in range(rig.companion.RAW_SHOTS + 15):
        rig.companion._forward_shot(number, "gspro", dict(GSPRO, ShotNumber=number))
    assert len(rig.companion.raw_shots()["shots"]) == rig.companion.RAW_SHOTS


def test_keeping_the_raw_message_never_costs_a_shot(rig, monkeypatch):
    def explode(*_a, **_k):
        raise RuntimeError("no")

    rig.pair()
    assert rig.wait_linked() is True
    monkeypatch.setattr(rig.companion, "_keep_raw", explode)
    result = rig.companion._forward_shot(1, "gspro", GSPRO)
    assert result.get("accepted") is True

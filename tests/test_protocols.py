"""The wire formats GSPro and E6 expect.

Sending and receiving is covered end to end in test_end_to_end_relay.py against
the mock simulators. These tests pin the shape of the messages themselves.
"""

import math

from pitrac_easy_connect.models import TEST_SHOT
from pitrac_easy_connect.protocols import e6_ball_message, e6_club_message, gspro_message


def test_gspro_message_contains_required_ball_data():
    message = gspro_message(TEST_SHOT, shot_number=7)
    assert message["ShotNumber"] == 7
    assert message["BallData"]["Speed"] == TEST_SHOT.speed_mph
    assert message["BallData"]["VLA"] == TEST_SHOT.vertical_launch_deg
    assert message["BallData"]["HLA"] == TEST_SHOT.horizontal_launch_deg
    expected_spin = math.hypot(TEST_SHOT.back_spin_rpm, TEST_SHOT.side_spin_rpm)
    assert message["BallData"]["TotalSpin"] == round(expected_spin, 1)
    assert message["ShotDataOptions"]["ContainsBallData"] is True


def test_gspro_spin_axis_carries_the_direction_of_curve():
    """A negative side spin has to read as a draw, not just a magnitude."""

    from dataclasses import replace

    left = gspro_message(replace(TEST_SHOT, side_spin_rpm=-500))
    right = gspro_message(replace(TEST_SHOT, side_spin_rpm=500))
    assert left["BallData"]["SpinAxis"] < 0 < right["BallData"]["SpinAxis"]


def test_e6_message_matches_pitrac_field_names():
    message = e6_ball_message(TEST_SHOT)
    assert message["Type"] == "SetBallData"
    assert message["BallData"] == {
        "BackSpin": TEST_SHOT.back_spin_rpm,
        "BallSpeed": TEST_SHOT.speed_mph,
        "LaunchAngle": TEST_SHOT.vertical_launch_deg,
        "LaunchDirection": TEST_SHOT.horizontal_launch_deg,
        "SideSpin": TEST_SHOT.side_spin_rpm,
    }


def test_e6_club_data_is_sent_even_when_empty():
    """E6 expects the club message in the sequence whether or not we measure it."""

    message = e6_club_message()
    assert message["Type"] == "SetClubData"
    assert "ClubData" in message


def test_an_impossible_shot_is_refused_before_it_reaches_a_simulator():
    from dataclasses import replace

    import pytest

    for bad in (replace(TEST_SHOT, speed_mph=0), replace(TEST_SHOT, vertical_launch_deg=120)):
        with pytest.raises(ValueError):
            gspro_message(bad)

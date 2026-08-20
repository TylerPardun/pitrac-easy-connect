"""The shot log, and the one thing this side knows that the enclosure does not.

PiTrac measures the ball. It has no idea which club was in your hands — the
simulator does, and it says so on the same connection it uses to acknowledge
shots, which already passes through the relay.
"""

import time

import pytest

from pitrac_easy_connect.companion.shotlog import (
    ShotLog,
    ball_from_shot,
    club_from_simulator_message,
    readable_club,
)


@pytest.fixture
def log(tmp_path):
    return ShotLog(tmp_path / "shots.json")


# --- Reading a club out of what the simulator says ------------------------


def test_a_gspro_player_message_carries_the_club():
    message = {
        "Code": 201,
        "Message": "GSPro Player Information",
        "Player": {"Handed": "RH", "Club": "DR", "DistanceToTarget": 100},
    }
    assert club_from_simulator_message(message) == "DR"


@pytest.mark.parametrize(
    "message",
    [
        {"Player": {"Club": "I7"}},
        {"Player": {"club": "I7"}},
        {"Player": {"ClubType": "I7"}},
        {"Club": "I7"},
        {"ClubType": "I7"},
        {"ClubData": {"Club": "I7"}},
    ],
)
def test_the_club_is_found_in_any_of_the_shapes_simulators_use(message):
    assert club_from_simulator_message(message) == "I7"


@pytest.mark.parametrize(
    "message",
    [
        {"Code": 200, "Message": "Shot received successfully"},
        {"Type": "ShotAccepted"},
        {"Player": {}},
        {"Player": "not a dict"},
        {},
        None,
        "a string",
        {"Club": ""},
    ],
)
def test_a_message_with_no_club_in_it_is_not_guessed_at(message):
    assert club_from_simulator_message(message) is None


def test_short_club_codes_become_something_readable():
    assert readable_club("DR") == "Driver"
    assert readable_club("I7") == "7 iron"
    assert readable_club("pw") == "Pitching wedge"


def test_a_club_we_do_not_recognise_is_kept_rather_than_dropped():
    assert readable_club("Chipper") == "Chipper"
    assert readable_club("  5w-custom ") == "5w-custom"


def test_no_club_is_empty_not_the_word_none():
    assert readable_club(None) == ""
    assert readable_club("") == ""


# --- Recording ------------------------------------------------------------


def test_a_club_change_is_picked_up_from_the_return_path(log):
    assert log.note_simulator_message({"Player": {"Club": "DR"}}) == "Driver"
    assert log.club == "Driver"


def test_the_same_club_twice_is_not_reported_as_a_change(log):
    log.note_simulator_message({"Player": {"Club": "DR"}})
    assert log.note_simulator_message({"Player": {"Club": "DR"}}) is None


def test_shots_are_recorded_against_the_club_in_hand(log):
    log.note_simulator_message({"Player": {"Club": "DR"}})
    log.record({"BallData": {"Speed": 148.3, "VLA": 12.9, "BackSpin": 2604}}, "gspro")
    log.note_simulator_message({"Player": {"Club": "I7"}})
    log.record({"BallData": {"Speed": 118.0, "VLA": 18.5, "BackSpin": 6800}}, "gspro")

    by_club = {row["club"]: row for row in log.by_club()}
    assert by_club["Driver"]["shots"] == 1
    assert by_club["Driver"]["speed"] == 148.3
    assert by_club["7 iron"]["shots"] == 1


def test_averages_are_averages(log):
    log.set_club("7 iron")
    for speed in (110.0, 120.0, 130.0):
        log.record({"BallData": {"Speed": speed, "VLA": 18.0}}, "gspro")
    assert log.by_club()[0]["speed"] == 120.0
    assert log.by_club()[0]["shots"] == 3


def test_e6_field_names_are_understood_too(log):
    log.record({"BallData": {"BallSpeed": 140.0, "LaunchAngle": 14.0, "BackSpin": 3000}}, "e6")
    shot = log.recent()[0]
    assert shot["speed"] == 140.0
    assert shot["launch"] == 14.0


def test_a_shot_that_never_reached_the_simulator_is_marked_and_excluded(log):
    log.set_club("Driver")
    log.record({"BallData": {"Speed": 150.0}}, "gspro", delivered=True)
    log.record({"BallData": {"Speed": 9999.0}}, "gspro", delivered=False)

    assert log.recent()[0]["delivered"] is False
    # A shot nobody received must not distort the averages.
    assert log.by_club()[0]["shots"] == 1
    assert log.by_club()[0]["speed"] == 150.0


def test_shots_with_no_ball_data_do_not_break_anything(log):
    log.record({"Type": "Handshake"}, "e6")
    log.record({}, "gspro")
    assert len(log.recent()) == 2
    assert log.by_club()[0]["speed"] is None


def test_the_most_recently_used_club_comes_first(log):
    log.set_club("Driver")
    log.record({"BallData": {"Speed": 150.0}}, "gspro")
    time.sleep(0.01)
    log.set_club("7 iron")
    log.record({"BallData": {"Speed": 118.0}}, "gspro")
    assert log.by_club()[0]["club"] == "7 iron"


def test_recent_shots_are_newest_first(log):
    for speed in (100.0, 110.0, 120.0):
        log.record({"BallData": {"Speed": speed}}, "gspro")
    assert [s["speed"] for s in log.recent()] == [120.0, 110.0, 100.0]


# --- Not growing forever, and surviving a restart -------------------------


def test_the_log_is_capped(tmp_path):
    log = ShotLog(tmp_path / "shots.json", limit=20)
    for index in range(200):
        log.record({"BallData": {"Speed": float(index)}}, "gspro")
    assert log.status()["total"] == 20


def test_shots_and_the_club_survive_closing_the_app(tmp_path):
    log = ShotLog(tmp_path / "shots.json")
    log.set_club("7 iron")
    log.record({"BallData": {"Speed": 118.0}}, "gspro")

    reopened = ShotLog(tmp_path / "shots.json")
    assert reopened.club == "7 iron"
    assert reopened.recent()[0]["speed"] == 118.0


def test_clearing_removes_the_shots(log):
    log.record({"BallData": {"Speed": 100.0}}, "gspro")
    log.clear()
    assert log.status()["total"] == 0


def test_ball_data_extraction_is_tolerant_of_rubbish():
    assert ball_from_shot({"BallData": {"Speed": "not a number"}})["speed"] is None
    assert ball_from_shot({"BallData": "not a dict"}) == {}
    assert ball_from_shot({}) == {}


# --- The numbers that make it worth keeping -------------------------------


def test_spread_shows_consistency_that_an_average_hides(log):
    """148/149/150 and 130/148/168 average the same and are not the same player."""

    log.set_club("Driver")
    for speed in (148.0, 149.0, 150.0):
        log.record({"BallData": {"Speed": speed}}, "gspro")
    tight = log.by_club()[0]

    log.clear()
    log.set_club("Driver")
    for speed in (130.0, 149.0, 168.0):
        log.record({"BallData": {"Speed": speed}}, "gspro")
    loose = log.by_club()[0]

    assert tight["speed"] == loose["speed"], "the averages are the same"
    assert tight["spread"] < loose["spread"], "but the spread tells them apart"
    assert tight["spread"] == 2.0
    assert loose["spread"] == 38.0


def test_best_and_worst_are_reported(log):
    log.set_club("7 iron")
    for speed in (110.0, 125.0, 118.0):
        log.record({"BallData": {"Speed": speed}}, "gspro")
    row = log.by_club()[0]
    assert row["bestSpeed"] == 125.0
    assert row["worstSpeed"] == 110.0


def test_a_single_shot_has_no_spread_rather_than_zero(log):
    """One shot says nothing about consistency, and should not claim to."""

    log.set_club("Driver")
    log.record({"BallData": {"Speed": 148.0}}, "gspro")
    assert log.by_club()[0]["spread"] is None


def test_direction_is_averaged_so_a_persistent_miss_shows_up(log):
    log.set_club("Driver")
    for direction in (3.8, 4.2, 4.0):
        log.record({"BallData": {"Speed": 148.0, "HLA": direction}}, "gspro")
    assert log.by_club()[0]["direction"] == 4.0

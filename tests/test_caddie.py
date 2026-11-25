"""Choosing a club from the distance, and never arguing with the player.

PiTrac cannot see the club. So this is a suggestion, made from how far away the
flag is and how far this player actually hits things, and the player's own
choice always stands.
"""

import pytest

from pitrac_easy_connect.companion import clubs
from pitrac_easy_connect.companion.service import CompanionService

from test_local_range import SHOT


@pytest.fixture
def app(tmp_path):
    built = CompanionService(tmp_path / "c.json", discovery_port=0, startup_update_check=False)
    yield built
    built.close()


def hit(app, club, speed=122.0, times=3):
    app.shots.set_club(club)
    for _ in range(times):
        app._forward_shot(1, "gspro", dict(SHOT, BallData=dict(SHOT["BallData"], Speed=speed)))


# --- The suggestion ---------------------------------------------------------


@pytest.mark.parametrize("yards, club", [
    (300, "Driver"), (225, "Driver"), (150, "6 iron"), (140, "7 iron"), (110, "Pitching wedge"),
    (60, "Lob wedge"), (20, "Lob wedge"),
])
def test_a_beginner_is_given_a_sensible_club(yards, club):
    assert clubs.suggest(yards, clubs.DEFAULT_BAG, clubs.carries({})) == club


def test_nothing_outside_the_bag_is_suggested():
    bag = ["Driver", "7 iron", "Putter"]
    for yards in range(20, 301, 5):
        assert clubs.suggest(yards, bag, clubs.carries({})) in ("Driver", "7 iron")


def test_the_putter_is_never_chosen_for_anybody():
    """It changes how PiTrac measures, so only the player does that."""

    for yards in range(20, 301):
        assert clubs.suggest(yards, clubs.CLUBS, clubs.carries({})) != "Putter"


def test_a_players_own_distances_are_used_once_there_are_enough():
    shots = [{"club": "7 iron", "carry": carry} for carry in (160, 168, 20)]
    assert clubs.known_carries(shots[:2]) == {}
    assert clubs.known_carries(shots) == {"7 iron": 160}, "one topped ball is not an average"


def test_one_club_says_how_long_a_hitter_they_are():
    distances = clubs.carries({"7 iron": 171.0})
    assert distances["7 iron"] == 171.0
    assert distances["6 iron"] > 175, "somebody who hits a 7 iron 171 does not hit a 6 iron 152"
    assert clubs.suggest(150, clubs.DEFAULT_BAG, distances) in ("8 iron", "9 iron")


@pytest.mark.parametrize("rubbish", [None, [], ["Niblick"], "Driver"])
def test_a_bag_is_never_empty(rubbish):
    assert clubs.clean_bag(rubbish) == clubs.DEFAULT_BAG


# --- In the app -------------------------------------------------------------


def test_auto_is_on_and_has_a_club_ready(app):
    status = app.range_status()
    assert status["autoClub"] is True
    assert status["club"] == status["suggested"] == "6 iron"


def test_moving_the_flag_changes_the_club(app):
    assert app.set_range_target(100)["club"] in ("Gap wedge", "Pitching wedge")
    assert app.set_range_target(240)["club"] == "Driver"


def test_choosing_a_club_turns_auto_off_and_it_stays_chosen(app):
    assert app.choose_range_club("5 iron")["autoClub"] is False
    assert app.set_range_target(60)["club"] == "5 iron"


def test_turning_auto_back_on_chooses_again(app):
    app.choose_range_club("Driver")
    assert app.set_auto_club(True)["club"] == "6 iron"


def test_auto_learns_but_does_not_swap_the_club_in_your_hands(app):
    hit(app, "6 iron", speed=130.0)
    status = app.range_status()
    assert status["club"] == "6 iron"
    assert status["suggested"] != "6 iron", "and it says what it would pick now"
    assert app.set_auto_club(True)["club"] == status["suggested"]


def test_shots_before_this_release_do_not_break_the_distances(app):
    app.shots.record(SHOT, "local", delivered=None)
    assert "carry" not in app.shots.recent()[0]
    assert app.range_status()["clubs"]


def test_how_far_you_hit_each_club_survives_a_restart(tmp_path):
    first = CompanionService(tmp_path / "c.json", discovery_port=0, startup_update_check=False)
    hit(first, "7 iron")
    carry = next(c for c in first.range_status()["clubs"] if c["club"] == "7 iron")
    first.set_range_target(180)
    first.close()
    second = CompanionService(tmp_path / "c.json", discovery_port=0, startup_update_check=False)
    try:
        status = second.range_status()
        assert next(c for c in status["clubs"] if c["club"] == "7 iron") == carry
        assert carry["measured"] is True
        assert status["target"] == 180
    finally:
        second.close()


def test_the_bag_can_be_changed_and_auto_obeys_it(app):
    app.set_bag(["Driver", "7 iron", "Putter"])
    assert app.set_range_target(150)["club"] == "7 iron"
    assert [c["club"] for c in app.range_status()["clubs"] if c["inBag"]] == [
        "Driver", "7 iron", "Putter"]


def test_gspro_decides_the_club_while_it_is_being_played(app):
    app.select_simulator("gspro")
    app.shots.set_club("5 iron")
    status = app.set_range_target(60)
    assert status["club"] == "5 iron"
    assert (status["autoClub"], status["clubIsOurs"]) == (False, False)


def test_a_made_up_club_is_refused(app):
    with pytest.raises(ValueError):
        app.choose_range_club("Niblick")


# --- Whether there is a ball to hit -----------------------------------------


def test_the_app_knows_when_there_is_a_ball(app):
    assert app.range_status()["ballDetected"] is None
    options = dict(SHOT["ShotDataOptions"], ContainsBallData=False, IsHeartBeat=True)
    app._forward_shot(1, "gspro", dict(SHOT, ShotDataOptions=options))
    assert app.range_status()["ballDetected"] is True
    app._forward_shot(2, "gspro", SHOT)
    assert app.range_status()["ballDetected"] is False, "it has just been hit"


# --- Filling the screen -----------------------------------------------------


def test_full_screen_asks_the_window_and_works_without_one(app):
    import threading

    assert app.set_fullscreen(True) == {"fullscreen": False}
    asked, done = [], threading.Event()
    app.register_fullscreen(lambda on: (asked.append(on), done.set()))
    assert app.set_fullscreen(True) == {"fullscreen": True}
    assert done.wait(2) and asked == [True]


def test_full_screen_is_not_toggled_the_wrong_way():
    from pitrac_easy_connect.companion.window import _fullscreen_switch

    class Window:
        toggles = 0

        def toggle_fullscreen(self):
            self.toggles += 1

    window = Window()
    switch = _fullscreen_switch(window)
    for on in (True, True, False, False, True):
        switch(on)
    assert window.toggles == 3

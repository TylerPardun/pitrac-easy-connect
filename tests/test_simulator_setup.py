"""Choosing how to play, and connecting GSPro, has a place of its own.

The picker used to live inside a collapsed Advanced section on the Play pane,
and the only guidance for getting a simulator listening appeared inside the
first-run guide. Anyone who finished that guide, or skipped it, had nowhere to
go and nothing telling them what to do.

Deliberately not a wizard: the steps are all shown at once and tick off as they
come true, nothing is gated on anything else, and the pane is safe to open at
any time -- including with no enclosure, because this connection is between the
computer and the simulator running on it.
"""

import pathlib

from pitrac_easy_connect.companion.page import PAGE


def render_source():
    return PAGE.split("function renderSimulator(data){")[1].split("\nfunction ")[0]


def test_the_simulator_has_a_destination_of_its_own():
    assert 'id="pane-simulator"' in PAGE
    assert 'data-pane="simulator"' in PAGE, "no tab leads to it"


def test_it_is_offered_on_the_board():
    board = PAGE.split("function boardCards(data){")[1].split("\nfunction ")[0]
    assert 'pane:"simulator"' in board, "the board does not offer the simulator"


def test_gspro_is_described_with_the_screen_that_starts_listening():
    """The step people miss: the port only opens on a particular screen."""

    where = PAGE.split("const SIM_WHERE = {")[1].split("};")[0]
    assert "Open Connect" in where, "GSPro's listening screen is not named"
    assert "921" in where, "the port is not stated"


def test_the_local_range_is_offered_wherever_gspro_is():
    assert PAGE.count('data-sim="local"') == PAGE.count('data-sim="gspro"') == 1


def test_gspros_connection_buttons_are_not_shown_for_the_local_range():
    assert '$("simButtons").classList.toggle("hidden", local)' in render_source()


def test_connection_addresses_are_in_the_developer_console():
    assert "127.0.0.1:" not in render_source()
    details = PAGE.split("function renderDetails(data){")[1].split("\nfunction ")[0]
    assert "sim.endpoint" in details
    console = PAGE.split('<dialog id="devConsole"')[1].split("</dialog>")[0]
    assert 'id="kv"' in console and 'id="rawShots"' in console
    assert 'id="cameras"' in console


def test_the_steps_tick_off_rather_than_being_a_wall_of_text():
    source = render_source()
    assert "done:" in source and "sim.connected" in source and "sim.ready" in source, (
        "the steps do not reflect the live connection state"
    )


def test_it_is_reachable_without_an_enclosure():
    """This connection does not involve PiTrac, so it must not require one."""

    render = PAGE.split("function render(data){")[1].split("function doAction(")[0]
    assert "if(!linkedNow" in render, "the pane-bounce rule is no longer where this test looks"
    guarded = render.split("if(!linkedNow")[1].split("showPane(")[0]
    assert 'pane!=="simulator"' in guarded, (
        "the simulator pane is sent back to Play when PiTrac is not connected, "
        "even though that connection needs no enclosure"
    )


def test_a_test_shot_is_not_offered_without_an_enclosure():
    """There is nothing to hit a shot with; offering it would be a dead button."""

    assert '$("simTest").disabled = !linked' in render_source()


def test_the_check_and_test_buttons_reuse_the_existing_actions():
    """Not a second code path for the same two things."""

    assert '$("simCheck").addEventListener' in PAGE
    assert 'doAction("check"' in PAGE and 'doAction("test"' in PAGE

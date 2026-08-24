"""The landing pane says where to go, not just where you are.

The complaint this pins: "the user has to click through a few things to find
what they are looking for", and the practice range could not be found at all.
Phase 3 brought the tab bar back; a tab bar still asks you to know which tab
you want. This is the board of destinations under the status, each carrying
the state of the place it leads to.

The rule worth keeping is the last test here: every pane reachable from the
tab bar is reachable from the board. A pane that exists but appears in
neither is a pane nobody finds.
"""

import re
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
PAGE = (SOURCE / "companion" / "page.py").read_text()


def board_source():
    return PAGE.split("function boardCards(")[1].split("function renderBoard(")[0]


def board_panes():
    return re.findall(r'\{pane:"([a-z]+)"', board_source())


def tab_panes():
    nav = PAGE.split('<nav class="tabs', 1)[1].split("</nav>", 1)[0]
    return re.findall(r'data-pane="([a-z]+)"', nav)


def test_the_board_exists_and_is_rendered():
    assert 'id="board"' in PAGE, "no board in the markup"
    assert "renderBoard(data, guiding)" in PAGE, "the board is never rendered"


def test_the_board_is_hidden_while_the_guide_runs():
    """During setup the guide is the whole point; the board would compete."""

    render = PAGE.split("function renderBoard(")[1].split("\nfunction ")[0]
    assert 'classList.toggle("hidden", guiding)' in render
    assert 'board.innerHTML=""' in render, (
        "hiding the board without clearing it leaves stale cards behind for "
        "anything that measures or reads the page"
    )


def test_cards_that_need_the_enclosure_say_so_when_it_is_not_connected():
    """A card leading to an empty frame is worse than a card that explains."""

    source = board_source()
    assert "needsLink:true" in source
    assert "disabled: !!card.needsLink && !linked" in source, (
        "cards that need a live link are not disabled without one"
    )


def test_the_board_is_wired_to_something():
    """A card whose click nothing handles is a card that does nothing."""

    assert '#board button[data-pane]' in PAGE, "no handler targets the board"
    assert "if(card && !card.disabled) showPane(card.dataset.pane)" in PAGE, (
        "board clicks do not navigate, or navigate even when disabled"
    )


@pytest.mark.parametrize("pane", ["range", "shots", "pitrac", "setup"])
def test_every_destination_on_the_board_is_a_real_pane(pane):
    assert pane in board_panes(), "{} is not on the board".format(pane)
    assert 'id="pane-{}"'.format(pane) in PAGE, (
        "the board offers {} but there is no such pane".format(pane)
    )


def test_every_tab_except_the_landing_one_is_on_the_board():
    """The board is the answer to "where do I go"; a gap in it is a gap there."""

    missing = [p for p in tab_panes() if p != "play" and p not in board_panes()]
    assert not missing, (
        "these panes are reachable from the tab bar but not from the board, so "
        "anyone using the board to decide would never see them: {}".format(missing)
    )

"""What the range opens on, and what it offers once it is open.

Three changes are pinned here:

* the range opens down the line, because that is where the golfer stands.
  It used to open from behind and off to one side, which reads as a
  broadcast replay rather than the view you would have over the ball;
* the three camera angles sit behind one "Change view" button instead of
  spending three slots in the bar on a setting most people set once;
* the demo shot disappears once the enclosure reports it can measure. It
  exists so the range can be seen before there is a launch monitor to fill
  it; after that it is a way to put a shot in the history nobody hit.
"""

import re
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
PAGE = (SOURCE / "companion" / "page.py").read_text()


def markup_default_view():
    menu = PAGE.split('id="viewMenu"', 1)[1].split("</div>", 1)[0]
    found = re.search(r'class="viewbtn on"\s+data-view="([a-z]+)"', menu)
    return found.group(1) if found else None


def script_default_view():
    found = re.search(r'let view="([a-z]+)", orbit=Object\.assign\(\{\}, VIEWS\.([a-z]+)\)', PAGE)
    return (found.group(1), found.group(2)) if found else (None, None)


def test_the_range_opens_down_the_line():
    """A first-person simulator should open where the player stands."""

    view, orbit = script_default_view()
    assert view == "down", "the range opens on {}, not down the line".format(view)
    assert orbit == "down", "the starting camera does not match the starting view"


def test_the_marked_button_matches_the_view_the_range_actually_opens_on():
    """Otherwise the range opens on a camera no button claims."""

    assert markup_default_view() == script_default_view()[0], (
        "the menu marks {} but the range opens on {}"
        .format(markup_default_view(), script_default_view()[0])
    )


def test_the_angles_are_behind_one_button():
    assert 'id="viewToggle"' in PAGE, "no Change view button"
    assert 'id="viewMenu"' in PAGE, "no menu for the angles"
    menu = PAGE.split('id="viewMenu"', 1)[1].split("</div>", 1)[0]
    assert menu.count("data-view=") == 3, (
        "expected all three angles inside the menu, found {}".format(menu.count("data-view="))
    )
    # And none left loose in the bar beside the toggle.
    bar = PAGE.split('<div class="rangebar">', 1)[1].split('id="viewMenu"', 1)[0]
    assert "data-view=" not in bar, "an angle is still sitting loose in the bar"


def test_choosing_an_angle_puts_the_menu_away():
    """A menu that stays open covers the thing it was opened to look at."""

    assert "function closeViewMenu(" in PAGE
    chooser = PAGE.split('.viewbtn[data-view]").forEach', 1)[1].split("});", 1)[0]
    assert "closeViewMenu()" in chooser, "the menu stays open after a choice"


def test_the_menu_is_closed_by_clicking_away_and_by_escape():
    assert 'event.target.closest(".views")' in PAGE, "clicking away does not close it"
    assert 'event.key==="Escape"' in PAGE, "Escape does not close it"


def test_the_demo_shot_retires_once_the_enclosure_can_measure():
    """Cameras attached and calibrated means real shots are coming."""

    render = PAGE.split("function render(data){")[1].split("function doAction(")[0]
    assert 'find(s=>s.key==="pitrac")' in render, (
        "nothing consults the enclosure's own account of whether it can measure"
    )
    assert '$("rangeDemo").classList.toggle("hidden"' in render, (
        "the demo shot is offered whether or not there is a launch monitor"
    )


def test_clearing_the_range_is_never_hidden():
    """Real shots need clearing more than demo ones did."""

    render = PAGE.split("function render(data){")[1].split("function doAction(")[0]
    assert '$("rangeClear").classList.toggle("hidden"' not in render


@pytest.mark.parametrize("angle", ["down", "behind", "top"])
def test_every_offered_angle_is_one_the_camera_understands(angle):
    """A button for a camera that does not exist moves nothing when pressed."""

    assert 'data-view="{}"'.format(angle) in PAGE
    views = PAGE.split("const VIEWS = {", 1)[1].split("};", 1)[0]
    handled_specially = 'view==="{}"'.format(angle) in PAGE
    assert "{}:".format(angle) in views or handled_specially, (
        "{} is offered but the camera has no case for it".format(angle)
    )

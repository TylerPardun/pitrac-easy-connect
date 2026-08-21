"""The controls a page draws must actually be wired to something.

Three defects found in real use motivated this file, and each is pinned below:

* the app asked for a six-digit code without saying where to find it;
* changing Wi-Fi only existed inside ``Advanced``, so an enclosure already on a
  network looked unchangeable;
* the pairing code was shown during first setup and never again, which left no
  way at all to pair a second computer.

The first two tests are the general form of the same mistake: a button whose id
nothing handles, or a handler for an element that is not on the page.
"""

import re
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
COMPANION = (SOURCE / "companion" / "page.py").read_text()
PORTAL = (SOURCE / "pi" / "portal_page.py").read_text()

PAGES = [("companion", COMPANION), ("portal", PORTAL)]


@pytest.mark.parametrize("name,page", PAGES, ids=[case[0] for case in PAGES])
def test_every_element_the_script_reaches_for_exists(name, page):
    """``$("x")`` with no ``id="x"`` in the markup throws on the user's screen."""

    markup = page.split("<script>")[0]
    present = set(re.findall(r'id="([A-Za-z0-9_-]+)"', markup))
    # Elements the script creates itself, rather than finding in the markup.
    created = set(re.findall(r'\bid\s*=\s*"([A-Za-z0-9_-]+)"', page.split("<script>")[-1]))

    wanted = set(re.findall(r'\$\(\s*"([A-Za-z0-9_-]+)"\s*\)', page))
    missing = wanted - present - created
    assert not missing, "{} page reaches for elements that do not exist: {}".format(
        name, sorted(missing)
    )


def test_every_action_the_portal_offers_is_handled():
    """An action id with no branch in ``act()`` is a button that does nothing."""

    offered = set(re.findall(r'\bid:\s*"([A-Za-z0-9_-]+)"', PORTAL))
    handled = set(re.findall(r'id\s*===\s*"([A-Za-z0-9_-]+)"', PORTAL))
    assert not offered - handled, "portal offers unhandled actions: {}".format(
        sorted(offered - handled)
    )


def test_pairing_asks_for_nothing():
    """The app used to show a code and then ask for it back.

    It could only do that because it had already reached the enclosure, which
    is the only thing typing the code proved. Nothing about the code survives.
    """

    for page in (COMPANION, PORTAL):
        assert "pairing-code" not in page
        assert "six-digit" not in page
        assert "six digit" not in page
    assert 'id="code"' not in COMPANION and "doPair" not in COMPANION

    # Choosing an enclosure pairs with it; there is no step in between.
    handler = COMPANION.split('host.querySelectorAll(".device")')[1].split("\n  }catch")[0]
    assert '"/api/pair"' in handler


def test_changing_wifi_is_offered_without_opening_advanced():
    """An enclosure already on a network must still look changeable."""

    done_state = PORTAL.split('head:"PiTrac is set up"')[1].split("};")[0]
    assert "changeWifi" in done_state, "the done state should offer to change network"
    assert 'id="changeWifi"' not in PORTAL.split("<script>")[0], "should be an action, not buried"


def test_choosing_a_network_can_be_abandoned():
    """Reaching the network list by mistake must not strand the page there."""

    view = PORTAL.split("function networkView()")[1].split("\n}")[0]
    assert "keepWifi" in view, "there should be a way back to the current network"


def test_a_second_computer_needs_the_owner_to_open_a_window():
    """Without this the enclosure would take any computer that asked, forever."""

    assert 'id="pairAnother"' in PORTAL
    assert 'view==="pairing"' in PORTAL
    # Pressing it is what opens the window; the view alone must not.
    press = PORTAL.split('$("pairAnother").addEventListener')[1].split("}));")[0]
    assert '"/api/pair-open"' in press


def test_the_network_list_survives_a_refresh():
    """A re-render must not restart the scan.

    The page redraws every few seconds. A repeat Wi-Fi scan on the Pi takes
    about eight seconds — longer than that interval — so when the redraw reset
    the list to "Looking…" and started a new scan, no scan ever finished and
    the list stayed empty forever. Whoever wanted to change network saw nothing
    to pick.
    """

    view = PORTAL.split("function networkView()")[1].split("\n}")[0]
    assert "networkRows(networks)" in view, "the list should redraw from the last scan"

    scan = PORTAL.split("async function loadNetworks()")[1].split("\n}")[0]
    assert "if(scanning) return" in scan, "a scan already running must not be started again"
    # The element is looked up after the request finishes, because a redraw
    # during the scan replaces the one that was there when it started.
    assert scan.index("await api") < scan.index('$("netList")')


def test_losing_the_link_brings_the_window_back_to_something_usable():
    """The tabs are hidden when there is no link.

    Anyone sitting on Shots, PiTrac or Setup when that happens was left looking
    at an empty window with no tabs and no buttons — no way back at all.
    """

    render = COMPANION.split("function render(")[1].split("\n}")[0]
    assert 'showPane("play")' in render, "the window must return to a pane that works"

    # `pane` has to exist before render() runs, and `let` is not hoisted.
    assert COMPANION.index("let pane=") < COMPANION.index("function render(")


@pytest.mark.parametrize("name,page", PAGES, ids=[case[0] for case in PAGES])
def test_no_style_is_left_behind_with_nothing_using_it(name, page):
    """Rules for elements that no longer exist quietly rot.

    Removing the pairing code left a 2.6rem digit style and a whole compact
    display mode behind, both unreachable.
    """

    style = page.split("<style>")[1].split("</style>")[0]
    rest = page.replace(style, "")
    classes = set(re.findall(r"\.([a-z][a-z0-9-]{2,})\s*[,{ ]", style))
    # Class names are built every way a template literal allows — ternaries,
    # concatenation, className assignment — so rather than trying to parse
    # that, take every quoted string outside the stylesheet as a possible name.
    # It errs towards saying a class is used, which is the right way to err.
    quoted = re.findall(r"\"([^\"\n]*)\"", rest) + re.findall(r"'([^'\n]*)'", rest)
    names = {word for value in quoted for word in value.replace("+", " ").split()}
    # Nested quotes inside template literals defeat the pairing above, so pick
    # up any single quoted word on its own as well.
    names |= set(re.findall(r"[\"']([a-z][a-z0-9-]{2,})[\"']", rest))

    orphans = {c for c in classes if c not in names}
    assert not orphans, "{} page styles nothing uses: {}".format(name, sorted(orphans))


def test_the_network_list_puts_known_networks_first():
    """Otherwise the network you want is buried among the neighbours'."""

    rows = PORTAL.split("function networkRows(")[1].split("\n}")[0]
    assert "Known networks" in rows and "Other networks" in rows
    # The connected one leads the known group.
    assert "n.inUse||n.known" in rows
    assert "(b.inUse?1:0)-(a.inUse?1:0)" in rows
    # With nothing known, no headings — a first-run list is all strangers.
    assert "if(!known.length) return rest.map(netRow).join" in rows

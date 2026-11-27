"""The controls a page draws must actually be wired to something.

Three defects found in real use motivated this file, and each is pinned below:

* the app asked for a six-digit code without saying where to find it;
* changing Wi-Fi only existed inside ``Advanced``, so an enclosure already on a
  network looked unchangeable;
* setup was shown during first run and never again, which left no
  way at all to pair a second computer.

The first two tests are the general form of the same mistake: a button whose id
nothing handles, or a handler for an element that is not on the page.
"""

import re
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
from pitrac_easy_connect.companion.page import PAGE as COMPANION
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


def test_a_rejected_additional_pairing_stays_inside_easy_connect():
    """The owner's setup action belongs in the app, not an external browser."""

    rejected = COMPANION.split("function showAsk(enclosure){", 1)[1].split(
        "function closeAsk()", 1
    )[0]
    assert '$("askBox").classList.remove("hidden")' in rejected
    assert "window.open" not in rejected
    # Its own panel, not the enclosure's page in a frame: that page's Pair
    # another computer sends no owner proof, so from a new computer it was a
    # button that could only ever fail.
    assert "askFrame" not in COMPANION


def test_a_new_computer_can_open_pairing_mode_with_the_owner_card():
    """Both ways into pairing mode are offered, and the password is sent."""

    panel = COMPANION.split('id="askBox"', 1)[1].split("</div>\n\n", 1)[0]
    assert 'type="password"' in panel
    assert 'id="askRetry"' in panel
    script = COMPANION.split("async function pairAsked(", 1)[1]
    assert "ownerCardPassword:password" in script
    assert '"/api/pair"' in script.split("\n}\n", 1)[0]
    # The password is cleared when the panel goes away.
    close = COMPANION.split("function closeAsk(){", 1)[1].split("}", 1)[0]
    assert '$("askCard").value=""' in close


def test_another_computer_holding_pitrac_offers_connect_here():
    view = COMPANION.split("function linkView(data){", 1)[1].split("\nfunction present(", 1)[0]
    assert 'id:"connectHere"' in view
    # An enclosure too old to update itself is told to be reinstalled, with no
    # button that could only ever fail.
    assert "one-time reinstall" in view
    assert "updateOld" not in COMPANION
    action = COMPANION.split('if(id==="connectHere")', 1)[1].split("\n", 1)[0]
    assert "takeOver:true" in action


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


def test_only_pair_not_accepting_opens_the_pairing_panel():
    """Rate limiting, an expired exchange, a device-id mismatch, a network
    problem -- none of them mean "go press Pair another computer on the Pi."
    Only PAIR_NOT_ACCEPTING (PT-PAIR-001) does; every other failure gets the
    generic error panel and its own next step instead."""

    from pitrac_easy_connect.common.errors import PAIR_NOT_ACCEPTING
    from pitrac_easy_connect.companion.page import PAGE as RESOLVED

    handler = RESOLVED.split('host.querySelectorAll(".device")')[1].split("\n    }));")[0]
    catch = handler.split("catch(error){", 1)[1]
    assert "showAsk(" in catch
    assert catch.count("showAsk(") == 1
    # showAsk is reached only through a check against this exact code, not
    # unconditionally in the catch block.
    before_call = catch.split("showAsk(")[0]
    assert 'code==="{}"'.format(PAIR_NOT_ACCEPTING.code) in before_call
    assert before_call.rstrip().endswith(")")


def test_discovery_success_clears_a_stale_no_pitrac_found_message():
    """The result and the error must come from the same completed search --
    finding a Pi this time must not leave an earlier "No PiTrac was found"
    sitting next to the device it just found."""

    search = COMPANION.split("async function findDevices()")[1].split("\nfunction renderKnownPis")[0]
    # showError(null) must appear after the not-found branch's own `return`,
    # so it only runs when this search actually found something.
    not_found = search.split("if(!data.enclosures.length){")[1].split("\n    }")[0]
    after = search.split("if(!data.enclosures.length){")[1].split("\n    }", 1)[1]
    assert "return" in not_found
    assert "showError(null)" in after


def test_the_setup_frame_is_given_an_owner_token():
    """Without this, the enclosure's own setup page has no way to prove it is
    being shown for an already-trusted computer, and its sensitive buttons
    would need someone to type the owner-card password by hand."""

    opener = COMPANION.split("async function openSetupFrame()")[1].split("\nfunction loadFrames")[0]
    assert "ensureOwnerToken()" in opener
    assert "ownerToken=" in opener


def test_the_portal_page_sends_its_owner_token_on_every_post():
    api = PORTAL.split("async function api(path, body)")[1].split("\nfunction esc")[0]
    assert "OWNER_TOKEN" in api
    assert "ownerToken:OWNER_TOKEN" in api


def test_discovery_problem_is_shown_in_the_desktop_ui():
    search = COMPANION.split("async function findDevices()")[1].split("\n}")[0]
    assert "data.problem" in search
    assert "problem.message" in search
    assert "problem.nextStep" in search
    assert "No PiTrac was found" in search


def test_the_window_asks_nobody_to_update_anything():
    """Updates install themselves; the window only says one is happening.

    The order -- this desktop first, then PiTrac to exactly its version -- is
    the autopilot's job now, and is tested there (test_auto_update.py).
    """

    for action in ('"/api/update/download"', '"/api/update/apply"', '"/api/update/pi"',
                   '"/api/update/prepare"', '"/api/update/check"', 'command:"applyUpdate"'):
        assert action not in COMPANION, action
    for gone in ("checkPiUpdate", "updateNow", "remindLater", "restartNow", "retryUpdate",
                 "syncPi", "doPiUpdate"):
        assert gone not in COMPANION, gone
    # The single exception: an update this computer could not install itself,
    # where the verified package is kept and can be shown.
    render = COMPANION.split("function renderUpdate(update){", 1)[1].split("\nfunction ", 1)[0]
    assert "DESKTOP_UPDATE_STUCK_STATES.has(state)" in render
    assert "savedPackagePath" in render


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

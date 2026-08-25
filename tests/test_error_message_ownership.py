"""A message must not be taken down by something that did not put it up.

The bug this pins, seen with two computers and one enclosure: the second
computer showed "Another computer is already connected to that PiTrac", which
then vanished and came back, on a loop.

The cycle was fifteen seconds long. While unconnected the page re-searches when
its last search is stale; the search cleared the error box so that a stale "No
PiTrac was found" could not sit beside a device list contradicting it; that
clear also wiped the connect refusal, which was still perfectly true; the next
three-second poll put it back.

So messages now record which part of the app owns them. A search clears its own
and leaves a link error alone, and render both raises and clears link errors --
which it did not do before, so simply stopping the search from clearing would
have left the message up forever once the link finally succeeded.
"""

import re
from pathlib import Path

import pytest

PAGE = (Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
        / "companion" / "page.py").read_text()


def render_source():
    return PAGE.split("function render(data){")[1].split("function doAction(")[0]


def find_devices_source():
    return PAGE.split("async function findDevices(")[1].split("\nasync function ")[0]


def test_messages_record_who_put_them_up():
    assert 'dataset.from = source || "action"' in PAGE, (
        "showError does not record an owner, so nothing can tell a search "
        "message from a connect refusal"
    )
    assert '$("err").dataset.from=""' in PAGE, "clearing does not clear the owner"


def test_a_search_leaves_a_connect_refusal_alone():
    """This is the line that produced the flicker."""

    source = find_devices_source()
    assert '$("err").dataset.from!=="link"' in source, (
        "a search still clears the error box unconditionally, so a live "
        "connect refusal is wiped every time one runs"
    )


def test_the_messages_a_search_raises_are_marked_as_its_own():
    """Otherwise the next search cannot clear them either."""

    source = find_devices_source()
    assert source.count('"search"') >= 2, (
        "the search's own messages are not tagged, so they would outlive the "
        "condition that caused them"
    )


def test_render_takes_a_link_error_down_as_well_as_putting_it_up():
    """Without this the message would survive a successful reconnect.

    Before, nothing in render cleared it -- the search happened to, which is
    exactly the coupling that caused the flicker. Removing that clear without
    adding this one would have traded a flickering message for a stuck one.
    """

    source = render_source()
    assert 'showError({info:linkError}' in source, "render no longer raises link errors"
    assert re.search(r'else if\(!linkError.*?\$\("err"\)\.dataset\.from==="link"\)', source), (
        "render never clears a link error, so one would stay up after the "
        "connection it described had succeeded"
    )


def test_the_refusal_panel_still_keeps_its_explanation():
    """An older rule that must survive this change."""

    assert "if(!asking())" in PAGE, (
        "clearing while the refusal panel is up would leave that panel with "
        "no explanation of why it appeared"
    )

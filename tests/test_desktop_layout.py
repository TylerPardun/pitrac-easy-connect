"""The window is a desktop window, so the page has to use it.

The defect this pins: the app opened at 480x900 -- a phone shape -- and every
container inside was capped near 440px, so on a real desktop window the content
sat in a narrow strip with most of the window empty. Widening the window alone
does not fix that; the caps have to move too, which is why these live beside
the window-geometry tests rather than inside them.

The opposite mistake is pinned as well. Buttons are width:100% of their
container, which is right in a narrow column and wrong in a wide one: the first
attempt at this stretched the primary action across 820px, where it read as a
banner rather than something to press.
"""

import re
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
PAGE = (SOURCE / "companion" / "page.py").read_text()
WINDOW = (SOURCE / "companion" / "window.py").read_text()

#: Anything narrower than this is a phone column, not a desktop layout.
DESKTOP_MINIMUM = 700


def declared_width(selector):
    """The px cap in a `selector{...width:min(Npx,...)}` rule."""

    pattern = re.escape(selector) + r"\s*\{[^}]*?width:\s*min\((\d+)px"
    found = re.search(pattern, PAGE)
    assert found, "no width:min(...) rule for {}".format(selector)
    return int(found.group(1))


def test_the_settled_layout_is_wider_than_the_first_run_guide():
    """The guide is one question at a time; everything after it is work."""

    guide = declared_width("body.guiding main")
    settled = declared_width("main")
    assert settled > guide, (
        "the settled column ({}px) is not wider than the guide's ({}px), so "
        "finishing setup leaves the window just as empty".format(settled, guide)
    )


@pytest.mark.parametrize("selector", ["main", ".shots"])
def test_content_containers_are_not_capped_at_a_phone_width(selector):
    """The whole point of the wider window is that content uses it."""

    width = declared_width(selector)
    assert width >= DESKTOP_MINIMUM, (
        "{} is capped at {}px, which leaves a desktop window mostly empty"
        .format(selector, width)
    )


@pytest.mark.parametrize("selector", ["main", ".shots", "body.guiding main"])
def test_every_content_container_yields_to_a_narrow_window(selector):
    """What keeps content inside the window is the percentage term, not the cap.

    The first version of this test compared the px cap against the window's
    minimum width and failed .shots, which is capped at 1040px in a window that
    can be 900px wide. That comparison was measuring the wrong thing: the rule
    is min(1040px, calc(100% - 64px)), so at 900px the second term wins and the
    container is 836px, which is what it measures in a real window. A cap wider
    than the window is fine; a rule with nothing but a cap is not.
    """

    pattern = re.escape(selector) + r"\s*\{[^}]*?width:\s*min\(\s*\d+px\s*,\s*([^)]*\))"
    found = re.search(pattern, PAGE)
    assert found, "no width:min(cap, fallback) rule for {}".format(selector)
    fallback = found.group(1)
    assert "100%" in fallback, (
        "{} is sized by a fixed cap with no percentage term ({}), so a window "
        "narrower than the cap would clip it".format(selector, fallback)
    )


def test_the_guiding_class_is_actually_applied():
    """A rule keyed on a class nothing sets is a rule that never runs."""

    assert 'classList.toggle("guiding"' in PAGE, (
        "body.guiding is styled but never set, so the guide would get the "
        "wide layout meant for the settled app"
    )


def test_the_primary_action_is_capped_so_it_stays_a_button():
    """Stretched across the full column it reads as a banner."""

    found = re.search(r"body:not\(\.guiding\)\s+\.do\s*\{[^}]*max-width:\s*(\d+)px", PAGE)
    assert found, "the action column has no max-width in the settled layout"
    assert int(found.group(1)) <= 480, (
        "the action column is capped at {}px, wide enough that a button still "
        "reads as a banner".format(found.group(1))
    )

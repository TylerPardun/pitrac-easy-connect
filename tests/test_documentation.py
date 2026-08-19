"""Keep the guides honest.

A guide that quotes a timeout or an error code the software no longer uses is
worse than no guide, because the reader trusts it. These tests fail when the
documentation and the code drift apart.
"""

import re
from pathlib import Path

import pytest

from pitrac_easy_connect import __version__
from pitrac_easy_connect.common.errors import catalogue
from pitrac_easy_connect.common.identity import HOTSPOT_SETUP_URL
from pitrac_easy_connect.pi.pairing import (
    CODE_LIFETIME_SECONDS,
    FAILURE_WINDOW_SECONDS,
    MAX_FAILURES,
)
from pitrac_easy_connect.pi.relay import DEFAULT_RELAY_PORTS
from pitrac_easy_connect.pi.wifi import CONFIRMATION_SECONDS
from pitrac_easy_connect.models import Simulator

DOCS = Path(__file__).resolve().parent.parent / "docs"
README = Path(__file__).resolve().parent.parent / "README.md"

GUIDES = [DOCS / "beginner-guide.md", DOCS / "beginner-guide.html"]
ALL_DOCS = GUIDES + [DOCS / "operator-guide.md", DOCS / "architecture.md", README]


def read(path):
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ALL_DOCS, ids=lambda p: p.name)
def test_every_error_code_quoted_in_the_docs_exists(path):
    known = set(catalogue())
    quoted = set(re.findall(r"PT-[A-Z]+-\d{3}", read(path)))
    assert quoted <= known, "documented codes that no longer exist: {}".format(quoted - known)


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.name)
def test_the_guides_print_the_address_the_hotspot_really_uses(path):
    assert HOTSPOT_SETUP_URL in read(path)


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.name)
def test_the_guides_describe_the_real_pairing_limits(path):
    text = read(path)
    assert CODE_LIFETIME_SECONDS == 300.0 and "five minutes" in text
    assert MAX_FAILURES == 5 and "five" in text
    assert FAILURE_WINDOW_SECONDS == 600.0 and "ten minutes" in text


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.name)
def test_the_guides_describe_the_real_rollback_window(path):
    assert CONFIRMATION_SECONDS == 150.0
    assert "two and a half minutes" in read(path)


def test_the_operator_guide_names_the_real_relay_ports():
    text = read(DOCS / "operator-guide.md")
    for simulator, port in DEFAULT_RELAY_PORTS.items():
        assert str(port) in text, "{} port {} is not documented".format(simulator.value, port)


def test_the_operator_guide_names_the_real_config_keys():
    from pitrac_easy_connect.pi.pitrac import SIMULATOR_KEYS

    text = read(DOCS / "operator-guide.md")
    for address_key, port_key in SIMULATOR_KEYS.values():
        assert address_key.rsplit(".", 1)[-1] in text
        assert port_key.rsplit(".", 1)[-1] in text


def test_the_docs_quote_the_current_version():
    assert __version__ in read(README)


def test_the_illustrated_guide_is_self_contained():
    """A strict content policy blocks anything but the one permitted font host."""

    text = read(DOCS / "beginner-guide.html")
    # Only things the page actually fetches count. Addresses printed as text for
    # the reader to type are not resource references.
    references = re.findall(r'(?:href|src)\s*=\s*"([^"]+)"', text)
    references += re.findall(r'url\(\s*[\'"]?([^)\'"]+)', text)
    allowed = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
    external = [
        reference
        for reference in references
        if "//" in reference and not reference.startswith(allowed)
    ]
    assert not external, "the guide would fail to load: {}".format(external)
    assert "<img" not in text, "images must be inline SVG, not external files"


def test_the_illustrated_guide_defines_both_themes():
    text = read(DOCS / "beginner-guide.html")
    assert ':root:not([data-theme="light"])' in text, "system dark mode is unhandled"
    assert ':root[data-theme="dark"]' in text, "an explicit dark choice is unhandled"
    assert "background:var(--paper)" in text, "the body must paint its own ground"

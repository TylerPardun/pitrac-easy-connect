"""Text from the network must not be able to become markup.

Both pages build HTML with template strings and pass untrusted values through
an ``esc()`` helper. That helper set ``textContent`` and read ``innerHTML``
back, which escapes ``&``, ``<`` and ``>`` -- and leaves quotes alone. Every
use inside a quoted attribute was therefore an injection point:

    data-ssid="${esc(n.ssid)}"        <- a Wi-Fi name, from anyone in radio range
    data-id="${esc(e.deviceId)}"      <- a discovery reply, from anyone on the LAN

A device id of ``x" autofocus onfocus="...`` was confirmed to produce a button
carrying real ``autofocus`` and ``onfocus`` attributes in the running app, from
an unauthenticated UDP reply. The desktop page sets no CSP, and its own origin
can drive /api/enclosure, which forwards commands to the paired enclosure.

These tests pin the escaper, every attribute that interpolates, and the
validation at the discovery boundary.
"""

import pathlib
import re

import pytest

from pitrac_easy_connect.common import discovery

PAGES = {
    "portal": pathlib.Path("src/pitrac_easy_connect/pi/portal_page.py"),
    "desktop": pathlib.Path("src/pitrac_easy_connect/companion/page.py"),
}

#: Interpolations that cannot carry anything from the network: a ternary
#: between two literals, or a module constant defined in the page itself.
SAFE_WITHOUT_ESCAPING = re.compile(
    r"^\s*(?:[A-Za-z_$][\w$]*\s*(?:<=|===|==|<)\s*[\w$.]+\s*\?\s*\"[^\"]*\"\s*:\s*"
    r"(?:\"[^\"]*\"|\([^)]*\))|[A-Z_]+|klass|[\w$.]+\s*\?\s*\"[^\"]*\"\s*:\s*\"[^\"]*\")\s*$"
)


def source(name):
    return PAGES[name].read_text(encoding="utf-8")


@pytest.mark.parametrize("page", sorted(PAGES))
def test_the_escaper_escapes_quotes(page):
    """Without this, every attribute below is an injection point."""

    text = source(page)
    start = text.find("function esc(")
    assert start != -1, "no esc() in {}".format(page)
    # To the closing brace of the function, which sits at the start of a line.
    end = text.find("\n}", start)
    body = text[start:end if end != -1 else start + 600]
    assert '"' in body and ("&quot;" in body or "&#34;" in body), (
        "esc() in {} does not turn a double quote into an entity, so a value "
        "containing one escapes its attribute: {!r}".format(page, body[:160])
    )


@pytest.mark.parametrize("page", sorted(PAGES))
def test_every_attribute_interpolation_is_escaped_or_provably_constant(page):
    """A value dropped into an attribute must not be able to close it."""

    text = source(page)
    offenders = []
    for attribute, expression in re.findall(r'([a-zA-Z-]+)="\$\{([^}]{0,80})\}"', text):
        if expression.strip().startswith("esc("):
            continue
        if SAFE_WITHOUT_ESCAPING.match(expression):
            continue
        offenders.append("{}=\"${{{}}}\"".format(attribute, expression))
    assert not offenders, (
        "{}: these attributes interpolate without escaping: {}".format(page, offenders)
    )


def test_a_discovery_reply_cannot_claim_a_device_id_containing_markup():
    """The id is used as an element attribute and as a dictionary key."""

    hostile = 'x" autofocus onfocus="window.pwned=true'
    payload = (
        '{"deviceId":' + '"' + hostile.replace('"', '\\"') + '"'
        + ',"linkPort":9999,"portalPort":80}'
    ).encode()
    assert discovery._parse(payload, "10.0.0.9") is None, (
        "a reply claiming a device id with markup in it was accepted"
    )


def test_a_real_device_id_is_still_accepted():
    payload = b'{"deviceId":"59MN8H7P","linkPort":39877,"portalPort":80}'
    found = discovery._parse(payload, "10.0.0.201")
    assert found is not None and found.device_id == "59MN8H7P"


# --- The second lock on the same defect ------------------------------------


def test_the_desktop_window_sends_a_content_security_policy():
    """The enclosure's portal has had one from the start; this window had none.

    It cannot stop an injected inline handler -- the page is inline script, so
    script-src has to allow inline, and escaping is what stops that. What it
    does stop is the step after: script that got in cannot load more script
    from anywhere, and cannot post what it found to another host.
    """

    from pitrac_easy_connect.companion.web import CONTENT_SECURITY_POLICY

    policy = CONTENT_SECURITY_POLICY
    assert "default-src 'none'" in policy
    assert "connect-src 'self'" in policy, (
        "without this, injected script can post whatever it reads to any host"
    )
    assert "frame-ancestors 'none'" in policy
    assert "base-uri 'none'" in policy
    # Verified in a running window: an external script and an external fetch
    # were both refused, while an image and a frame from the enclosure loaded.
    assert "img-src" in policy and "http:" in policy, (
        "the enclosure's address is whatever the router gave it, so its images "
        "and frames cannot be named here -- but they must still load"
    )


def test_the_policy_actually_reaches_the_browser():
    """A policy that is never sent is a policy that never applies."""

    from pitrac_easy_connect.companion import web

    source = pathlib.Path(web.__file__).read_text()
    assert 'send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)' in source

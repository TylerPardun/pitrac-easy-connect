"""Deeply nested JSON must be refused, not allowed to unwind the interpreter.

Python's json module recurses per nesting level, so a payload a few thousand
levels deep raises RecursionError. RecursionError is not a ValueError, so every
boundary that guarded itself with `except ValueError` let it through.

Where that lands, and who can send it:

* the enclosure's HTTP portal parses the body before its handler guard runs, so
  an unhandled RecursionError escaped the request entirely -- the caller got a
  dropped connection and the log got a traceback. Any device on the residence
  Wi-Fi can do this: the guard header is a cross-origin defence, not a secret.
* discovery parses UDP replies from anything that answers, so a crafted reply
  breaks "find my PiTrac" for as long as it keeps arriving.
* link frames are decoded during authentication, before the peer has proved
  anything at all.

None of these is remote code execution. All of them are an unauthenticated
device on the same network making the enclosure fail.
"""

import json
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from conftest import start_serving
from pitrac_easy_connect.common import discovery, link
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.portal import PortalServer
from pitrac_easy_connect.pi.service import PiService, ServicePaths
from pitrac_easy_connect.pi.simulated import home_network_pi

#: Measured, not guessed: CPython parses 9997 levels and fails at 9998, which
#: costs an attacker about 20 KB. Every boundary below accepts far more than
#: that, except discovery -- see the test at the end.
TOO_DEEP = 12000


def nested(depth):
    return "[" * depth + "]" * depth


@pytest.fixture
def portal(tmp_path):
    service = PiService(
        home_network_pi(country="US"),
        paths=ServicePaths(tmp_path / "state"),
        pitrac=PitracInstallation(tmp_path / "u.json", tmp_path / "c.json"),
        relay_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
        link_port=0, discovery_port=0, manage_hostname=False, boot_grace=0.0,
    )
    service.start()
    server = PortalServer(("127.0.0.1", 0), service)
    stop = start_serving(server)
    yield "http://127.0.0.1:{}".format(server.server_port)
    stop()
    service.stop()


def test_the_portal_answers_deeply_nested_json_instead_of_dropping_the_call(portal):
    """The caller must get a refusal, not a closed socket."""

    import urllib.error
    import urllib.request

    body = ('{"file":' + nested(TOO_DEEP) + "}").encode()
    request = urllib.request.Request(
        portal + "/api/backup/inspect", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-PiTrac-Portal": "1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
        error.read()
    assert status == 400, "expected a refusal, got {}".format(status)


def test_a_reasonable_backup_is_still_accepted(portal):
    """The limit must not refuse the nesting a real payload has."""

    import urllib.error
    import urllib.request

    body = json.dumps({"file": {"a": {"b": {"c": {"d": [1, 2, {"e": True}]}}}}}).encode()
    request = urllib.request.Request(
        portal + "/api/backup/inspect", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-PiTrac-Portal": "1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
        error.read()
    # 400 because it is not a backup, which is the handler talking, not a crash.
    assert status in (200, 400)


def test_discovery_cannot_be_sent_a_payload_deep_enough_to_break_it():
    """Discovery is safe because of its size cap, so the cap is what is pinned.

    A datagram is read at most MAX_REPLY_BYTES, and two bytes buy one level of
    nesting, so the deepest reply anyone can deliver is far short of the depth
    that unwinds the parser. This test exists so that raising the cap without
    thinking is caught here rather than in the field.
    """

    deepest_deliverable = discovery.MAX_REPLY_BYTES // 2
    assert deepest_deliverable < 9998, (
        "MAX_REPLY_BYTES is now {} bytes, which lets a reply nest {} deep -- "
        "past the point the JSON parser gives up"
        .format(discovery.MAX_REPLY_BYTES, deepest_deliverable)
    )

    # And the deepest that does fit still parses rather than raising.
    filler = nested(deepest_deliverable - 60)
    payload = ('{"deviceId":"AAAA1111","linkPort":1,"portalPort":80,"x":'
               + filler + "}").encode()
    assert len(payload) <= discovery.MAX_REPLY_BYTES
    discovery._parse(payload, "10.0.0.5")   # must not raise


def test_a_link_frame_that_is_too_deep_is_a_link_error_not_a_crash():
    """Frames are decoded before the peer has authenticated."""

    with pytest.raises(link.LinkError):
        link._decode(('{"type":"shot","data":' + nested(TOO_DEEP) + "}").encode())


def test_the_desktop_app_also_answers_a_deeply_nested_body(tmp_path):
    """Loopback only, so lower severity -- but the same defect."""

    import urllib.error
    import urllib.request

    from pitrac_easy_connect.companion.service import CompanionService
    from pitrac_easy_connect.companion.web import CompanionHTTPServer

    service = CompanionService(config_path=tmp_path / "companion.json",
                               discovery_port=0, search_seconds=0.05,
                               research_seconds=0.05)
    server = CompanionHTTPServer(("127.0.0.1", 0), service)
    stop = start_serving(server)
    try:
        body = ('{"club":' + nested(TOO_DEEP) + "}").encode()
        request = urllib.request.Request(
            "http://127.0.0.1:{}/api/club".format(server.server_port),
            data=body, method="POST",
            headers={"Content-Type": "application/json", "X-PiTrac-App": "1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
            error.read()
        assert status == 400, "expected a refusal, got {}".format(status)
    finally:
        stop()
        service.close()


def test_a_normal_link_frame_still_decodes():
    frame = link._decode(b'{"type":"shot","data":{"speed":120.0}}')
    assert frame["type"] == "shot"

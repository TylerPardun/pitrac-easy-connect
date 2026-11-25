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
import pathlib
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from conftest import start_serving
from pitrac_easy_connect.common import discovery, link
from pitrac_easy_connect.models import Simulator
from pitrac_fixture import make_pitrac
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
        pitrac=make_pitrac(tmp_path),
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


def test_discovery_refuses_a_reply_that_is_nested_too_deeply():
    """This test was wrong first, and CI is what said so.

    It originally asserted that discovery was safe *by arithmetic*: a reply is
    read at most MAX_REPLY_BYTES, two bytes buy one level, so the deepest
    deliverable reply could not reach the depth that unwinds the parser. That
    held on Python 3.12 on macOS, where the parser manages about 9998 levels.
    It does not hold on Python 3.9, or on Windows, where the limit is lower --
    and the version of this test that asserted "the deepest deliverable reply
    still parses" duly raised RecursionError on all four of those runners.

    The arithmetic was the mistake: how deep the parser can go is not a
    constant of the language. Discovery goes through the same bounded parser
    as every other boundary now, and this asserts the same thing they do.
    """

    payload = ('{"deviceId":"AAAA1111","linkPort":1,"portalPort":80,"x":'
               + nested(TOO_DEEP) + "}").encode()
    assert discovery._parse(payload, "10.0.0.5") is None


def test_a_reply_nested_within_reason_is_still_accepted():
    payload = b'{"deviceId":"AAAA1111","linkPort":39877,"portalPort":80,"x":{"y":[1,2]}}'
    found = discovery._parse(payload, "10.0.0.201")
    assert found is not None and found.device_id == "AAAA1111"


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


def test_every_json_parsed_off_the_network_goes_through_the_bounded_parser():
    """The rule, so the next boundary does not have to be reasoned about.

    Working out case by case whether a given parse site can be reached with
    enough nesting is what produced the mistake above. Anything reading JSON
    that came off a socket uses jsontext; the plain parser is for files this
    program wrote itself.
    """

    import re

    root = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
    reads_network = re.compile(r"json\.loads\(\s*(?:response|error|data|line)\b")
    offenders = []
    for path in root.rglob("*.py"):
        for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if reads_network.search(text):
                offenders.append("{}:{}".format(path.relative_to(root).as_posix(), number))
    assert not offenders, (
        "these parse network JSON with the unbounded parser: {}".format(offenders)
    )

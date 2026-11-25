"""Every route, given everything it does not expect.

A route that raises where it should refuse turns a bad request into a 500 and,
worse, into a traceback in a log the owner will never read. These drive real
HTTP against real servers rather than calling the handlers, so the framing,
the guards and the error shape are all exercised.

Destructive routes are named and skipped: this suite must not reboot the
machine it is running on.
"""

import json
import threading

from conftest import start_serving
import urllib.error
import urllib.request
from http import HTTPStatus

import pytest

from pitrac_easy_connect.companion.service import CompanionService
from pitrac_easy_connect.companion.web import CompanionHTTPServer
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.portal import PortalServer
from pitrac_easy_connect.pi.service import PiService, ServicePaths
from pitrac_easy_connect.pi.simulated import home_network_pi
from pitrac_fixture import make_pitrac

#: Routes that stop the machine, wipe it, or hand out a file. Exercised
#: elsewhere; hammering them here would end the test run.
DESTRUCTIVE = {
    "/api/reboot", "/api/shutdown", "/api/new-owner", "/api/quit",
    "/api/reset-network", "/api/restart-pitrac", "/api/backup",
    "/api/install-models", "/api/enclosure",
}

#: Bodies no caller should ever send.
RUBBISH = [
    ("empty", b""),
    ("not json", b"this is not json at all"),
    ("truncated", b'{"deviceId": "abc"'),
    ("a list", b"[1, 2, 3]"),
    ("a bare string", b'"hello"'),
    ("null", b"null"),
    ("a number", b"42"),
    ("wrong types", b'{"deviceId": {"nested": true}, "code": [1,2]}'),
    ("null values", b'{"deviceId": null, "simulator": null}'),
    ("unicode", ('{"deviceId": "☃ ￿"}').encode("utf-8")),
    ("deeply nested", b'{"a":' * 40 + b"1" + b"}" * 40),
    ("huge", b'{"deviceId": "' + b"x" * (2 * 1024 * 1024) + b'"}'),
]


def request(url, body=None, method=None, header=True, timeout=20):
    headers = {}
    if header:
        headers["X-PiTrac-App"] = "1"
        headers["X-PiTrac-Portal"] = "1"
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=body, headers=headers,
        method=method or ("POST" if body is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        return None, str(error).encode()


# --- Fixtures --------------------------------------------------------------


@pytest.fixture
def companion(tmp_path):
    service = CompanionService(
        config_path=tmp_path / "companion.json",
        simulator_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
        discovery_port=0,
        computer_name="Robustness",
        # Nothing is broadcasting on this port, so every search here waits out
        # its full timeout. At the real values that is five seconds a call on
        # the pairing routes, which this module exercises hundreds of times.
        search_seconds=0.05,
        research_seconds=0.05,
    )
    server = CompanionHTTPServer(("127.0.0.1", 0), service)
    stop = start_serving(server)
    yield "http://127.0.0.1:{}".format(server.server_port)
    stop()
    service.close()


@pytest.fixture
def portal(tmp_path):
    pitrac = make_pitrac(tmp_path)
    service = PiService(
        home_network_pi(country="US"),
        paths=ServicePaths(tmp_path / "state"),
        pitrac=pitrac,
        relay_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
        link_port=0, discovery_port=0, manage_hostname=False, boot_grace=0.0,
    )
    service.start()
    server = PortalServer(("127.0.0.1", 0), service)
    stop = start_serving(server)
    yield "http://127.0.0.1:{}".format(server.server_port)
    stop()
    service.stop()


def routes_of(module_path, kind):
    import pathlib as _p
    import re

    text = _p.Path(module_path).read_text()
    if kind == "GET":
        found = re.findall(r'path == "(/api/[a-z-]+)"', text)
    else:
        found = re.findall(r'"(/api/[a-z-]+)": lambda', text)
    return sorted(set(found) - DESTRUCTIVE)


COMPANION_POST = routes_of("src/pitrac_easy_connect/companion/web.py", "POST")
PORTAL_POST = routes_of("src/pitrac_easy_connect/pi/portal.py", "POST")
COMPANION_GET = routes_of("src/pitrac_easy_connect/companion/web.py", "GET")
PORTAL_GET = routes_of("src/pitrac_easy_connect/pi/portal.py", "GET")


def check(status, body, route, what):
    """A route may refuse, but it may not fall over."""

    assert status is not None, "{} closed the connection on {}".format(route, what)
    assert status != HTTPStatus.INTERNAL_SERVER_ERROR, \
        "{} returned 500 on {}: {}".format(route, what, body[:200])
    if body:
        text = body.decode("utf-8", "replace")
        assert "Traceback" not in text, "{} leaked a traceback on {}".format(route, what)


# --- The bodies nobody should send ----------------------------------------


@pytest.mark.parametrize("route", COMPANION_POST)
@pytest.mark.parametrize("name,body", RUBBISH, ids=[r[0] for r in RUBBISH])
def test_companion_routes_refuse_rubbish_without_falling_over(companion, route, name, body):
    status, answer = request(companion + route, body)
    check(status, answer, route, name)


@pytest.mark.parametrize("route", PORTAL_POST)
@pytest.mark.parametrize("name,body", RUBBISH, ids=[r[0] for r in RUBBISH])
def test_portal_routes_refuse_rubbish_without_falling_over(portal, route, name, body):
    status, answer = request(portal + route, body)
    check(status, answer, route, name)


# --- Wrong method ----------------------------------------------------------


@pytest.mark.parametrize("route", COMPANION_POST)
def test_a_post_route_called_as_get_is_refused_not_crashed(companion, route):
    status, answer = request(companion + route, None, method="GET")
    check(status, answer, route, "GET on a POST route")
    assert status in (HTTPStatus.NOT_FOUND, HTTPStatus.METHOD_NOT_ALLOWED,
                      HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN)


@pytest.mark.parametrize("route", COMPANION_GET + COMPANION_POST)
def test_exotic_methods_do_not_crash_the_companion(companion, route):
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"):
        status, answer = request(companion + route, None, method=method)
        check(status, answer, route, method)


@pytest.mark.parametrize("route", PORTAL_GET + PORTAL_POST)
def test_exotic_methods_do_not_crash_the_portal(portal, route):
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
        status, answer = request(portal + route, None, method=method)
        check(status, answer, route, method)


# --- The guard -------------------------------------------------------------


@pytest.mark.parametrize("route", COMPANION_POST)
def test_state_changing_routes_need_the_header(companion, route):
    status, _answer = request(companion + route, b"{}", header=False)
    assert status == HTTPStatus.FORBIDDEN, \
        "{} accepted a request without the app header".format(route)


@pytest.mark.parametrize("route", PORTAL_POST)
def test_portal_state_changing_routes_need_the_header(portal, route):
    status, _answer = request(portal + route, b"{}", header=False)
    assert status == HTTPStatus.FORBIDDEN, \
        "{} accepted a request without the page header".format(route)


# --- Paths that do not exist ----------------------------------------------


@pytest.mark.parametrize("path", [
    "/api/nope", "/api/", "/../../etc/passwd", "/api/status/../../secret",
    "/api/status%00", "/" + "a" * 4000,
])
def test_unknown_paths_are_refused_cleanly(companion, path):
    status, answer = request(companion + path)
    check(status, answer, path, "unknown path")
    assert status in (HTTPStatus.NOT_FOUND, HTTPStatus.BAD_REQUEST,
                      HTTPStatus.FORBIDDEN, HTTPStatus.REQUEST_URI_TOO_LONG)


# --- Many at once ----------------------------------------------------------


def test_the_companion_survives_concurrent_callers(companion):
    """The service holds a lock; the page polls while the user presses things."""

    problems = []

    def hammer(route, body):
        for _ in range(12):
            status, answer = request(companion + route, body, timeout=25)
            if status is None or status == HTTPStatus.INTERNAL_SERVER_ERROR:
                problems.append((route, status, answer[:120]))

    threads = [
        threading.Thread(target=hammer, args=("/api/status", None)),
        threading.Thread(target=hammer, args=("/api/range", None)),
        threading.Thread(target=hammer, args=("/api/range-demo", b"{}")),
        threading.Thread(target=hammer, args=("/api/range-clear", b"{}")),
        threading.Thread(target=hammer, args=('/api/simulator', b'{"simulator":"e6"}')),
        threading.Thread(target=hammer, args=("/api/finish-setup", b'{"done":true}')),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=90)
    assert not problems, problems


def test_the_status_stays_valid_json_under_load(companion):
    for _ in range(30):
        status, body = request(companion + "/api/status")
        assert status == HTTPStatus.OK
        json.loads(body)


# --- A refusal has to be readable ------------------------------------------
#
# A handler that answers without reading the request body leaves that body in
# the socket. Closing then resets the connection instead of finishing it, and
# the caller gets a dropped connection rather than the reason. Linux usually
# hides this because the kernel has already buffered the body; Windows does
# not, and reported WinError 10053 in place of the 403.


#: Big enough to outrun the socket buffer, so the reset happens everywhere
#: rather than only on Windows: at half a megabyte macOS still quietly
#: buffers the whole body and the bug stays invisible. Under the drain limit,
#: because past that the connection is closed deliberately.
UNREAD_BODY_SIZES = [1024, 512 * 1024, 1024 * 1024]


@pytest.mark.parametrize("size", UNREAD_BODY_SIZES)
def test_a_refused_portal_post_still_answers_with_its_reason(portal, size):
    body = b'{"padding": "' + b"x" * size + b'"}'
    status, payload = request(portal + "/api/country", body=body, header=False)

    assert status == HTTPStatus.FORBIDDEN, "expected the refusal, got {}".format(status)
    assert b"setup page" in payload, "the caller could not read why"


@pytest.mark.parametrize("size", UNREAD_BODY_SIZES)
def test_a_refused_companion_post_still_answers_with_its_reason(companion, size):
    body = b'{"padding": "' + b"x" * size + b'"}'
    status, payload = request(companion + "/api/club", body=body, header=False)

    assert status == HTTPStatus.FORBIDDEN
    assert b"Easy-Connect" in payload


def test_an_unknown_route_with_a_body_answers_rather_than_resetting(portal):
    body = b'{"padding": "' + b"x" * (1024 * 1024) + b'"}'
    status, payload = request(portal + "/api/no-such-thing", body=body)

    assert status == HTTPStatus.NOT_FOUND
    assert b"does not exist" in payload


def test_a_wrong_host_with_a_body_answers_rather_than_resetting(portal):
    import urllib.request as _request

    body = b'{"padding": "' + b"x" * (1024 * 1024) + b'"}'
    req = _request.Request(
        portal + "/api/country", data=body,
        headers={"Host": "somebody-elses-name.example", "Content-Type": "application/json",
                 "X-PiTrac-Portal": "1"},
        method="POST",
    )
    try:
        with _request.urlopen(req, timeout=20) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
        assert b"does not answer" in error.read()
    assert status == HTTPStatus.MISDIRECTED_REQUEST

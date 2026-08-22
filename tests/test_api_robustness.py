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
from pitrac_easy_connect.pi.pitrac import PitracInstallation

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
    )
    server = CompanionHTTPServer(("127.0.0.1", 0), service)
    stop = start_serving(server)
    yield "http://127.0.0.1:{}".format(server.server_port)
    stop()
    service.close()


@pytest.fixture
def portal(tmp_path):
    pitrac = PitracInstallation(
        tmp_path / "user_settings.json", tmp_path / "calibration_data.json"
    )
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

"""What the desktop app does when its port will not open.

The packaged Windows build has no console. An exception on the way up is
therefore completely invisible: the icon is double-clicked and nothing at all
appears. Every path out of a failed bind has to end somewhere the user can see.
"""

import errno
import json
import socket
import threading
from unittest import mock

import pytest

from pitrac_easy_connect.companion import app as app_module
from pitrac_easy_connect.companion.service import CompanionService
from pitrac_easy_connect.companion.web import CompanionHTTPServer
from pitrac_easy_connect.models import Simulator
from conftest import start_serving


@pytest.fixture
def running_copy(tmp_path):
    """A real Easy-Connect answering on a real port, as a second launch sees."""

    service = CompanionService(
        config_path=tmp_path / "first.json",
        simulator_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
        discovery_port=0,
        computer_name="The first copy",
        search_seconds=0.05,
        research_seconds=0.05,
    )
    server = CompanionHTTPServer(("127.0.0.1", 0), service)
    stop = start_serving(server)
    yield server.server_port
    stop()
    service.close()


def test_a_second_launch_shows_the_copy_that_is_already_running(running_copy, tmp_path):
    shown = []
    argv = ["--port", str(running_copy), "--config", str(tmp_path / "second.json"),
            "--discovery-port", "0"]

    with mock.patch.object(app_module, "_show", lambda args, url: shown.append(url)):
        code = app_module.main(argv)

    assert code == 0, "a second launch must not exit as a failure"
    assert shown == ["http://127.0.0.1:{}".format(running_copy)]


def test_a_port_held_by_something_else_does_not_stop_the_app(tmp_path):
    """Another program on 8787 must not make double-clicking do nothing."""

    squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    squatter.bind(("127.0.0.1", 0))
    squatter.listen(1)
    port = squatter.getsockname()[1]

    started = {}

    def capture(args, service, server):
        started["port"] = server.server_port
        server.server_close()
        service.close()
        return 0

    argv = ["--port", str(port), "--config", str(tmp_path / "c.json"),
            "--discovery-port", "0", "--no-browser"]
    try:
        with mock.patch.object(app_module, "_run", capture):
            code = app_module.main(argv)
    finally:
        squatter.close()

    assert code == 0
    assert started["port"] not in (0, port), "it should have moved to a free port"


def test_a_failure_that_is_not_a_busy_port_is_reported_to_the_user(tmp_path):
    """No console means an unreported failure is an invisible one."""

    said = []
    boom = OSError("the network stack is on fire")
    boom.errno = errno.EPERM

    with mock.patch.object(app_module, "CompanionHTTPServer", side_effect=boom), \
         mock.patch.object(app_module, "_say_it_failed", lambda message: said.append(message)):
        code = app_module.main(["--config", str(tmp_path / "c.json"), "--discovery-port", "0"])

    assert code == 1
    assert said and "on fire" in said[0]


def test_something_else_answering_on_the_port_is_not_mistaken_for_us(tmp_path):
    """A 200 from an unrelated server must not be read as our own copy."""

    import http.server

    class Impostor(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"hello": "I am not Easy-Connect"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Impostor)
    stop = start_serving(server)
    try:
        assert app_module._already_running(server.server_port) is False
    finally:
        stop()


def test_our_own_copy_is_recognised(running_copy):
    assert app_module._already_running(running_copy) is True


def test_nothing_listening_is_not_a_running_copy():
    spare = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    spare.bind(("127.0.0.1", 0))
    port = spare.getsockname()[1]
    spare.close()
    assert app_module._already_running(port) is False

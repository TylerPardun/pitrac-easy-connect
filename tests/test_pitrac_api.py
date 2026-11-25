"""What Easy-Connect makes of the ways PiTrac's web server can answer."""

import http.server
import json
import socket

import pytest

from conftest import start_serving

from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.pitrac_api import (
    PitracApi,
    PitracRefused,
    PitracUnreachable,
    PitracUnsupported,
)

SIM = {"id": "a", "type": "gspro", "on": True, "settings": {}, "status": "off"}
SETUP = {
    "strobe": {"safe": True},
    "cameras": {
        name: {"lens_calibrated": True, "position_calibrated": True}
        for name in ("camera1", "camera2")
    },
}


@pytest.fixture
def server():
    answers = {}
    asked = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append(self.path)
            status, body = answers.get(self.path, (404, {"detail": "Not Found"}))
            payload = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    running = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    stop = start_serving(running)
    running.answers, running.asked = answers, asked
    running.api = PitracApi("http://127.0.0.1:{}".format(running.server_port), timeout=2)
    yield running
    stop()


def test_nothing_listening_is_unreachable():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(PitracUnreachable):
        PitracApi("http://127.0.0.1:{}".format(port), timeout=1).sims()


def test_a_server_that_accepts_and_says_nothing_does_not_hang():
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        with pytest.raises(PitracUnreachable):
            PitracApi("http://127.0.0.1:{}".format(silent.getsockname()[1]), timeout=0.3).sims()


def test_an_older_pitrac_without_the_route_is_unsupported(server):
    with pytest.raises(PitracUnsupported):
        server.api.sims()


@pytest.mark.parametrize("body", [
    b"<html>PiTrac</html>", b"[" * 5000, {"sims": []}, [{"id": 1}], [dict(SIM, on="yes")], None,
])
def test_an_unrecognised_answer_is_unsupported_not_guessed_at(server, body):
    server.answers["/api/sims"] = (200, body)
    with pytest.raises(PitracUnsupported):
        server.api.sims()


@pytest.mark.parametrize("body", [
    {}, dict(SETUP, strobe={}), dict(SETUP, cameras={"camera1": {}}),
    dict(SETUP, strobe={"safe": "true"}),
])
def test_a_readiness_answer_missing_anything_is_not_read_as_ready(server, body):
    server.answers["/api/setup/status"] = (200, body)
    with pytest.raises(PitracUnsupported):
        server.api.setup_status()


def test_a_server_error_is_reported_with_what_pitrac_said(server):
    server.answers["/api/sims"] = (500, {"error": "database is locked"})
    with pytest.raises(PitracRefused, match="database is locked"):
        server.api.sims()


def test_one_look_answers_several_questions(server, tmp_path):
    server.answers["/api/sims"] = (200, [SIM])
    server.answers["/api/setup/status"] = (200, SETUP)
    pitrac = PitracInstallation(server.api, config_dir=tmp_path)
    for _ in range(5):
        assert pitrac.snapshot().calibrated is True
    assert len(server.asked) == 2

    pitrac.invalidate()
    pitrac.snapshot()
    assert len(server.asked) == 4


def test_a_proxy_setting_does_not_send_this_elsewhere(server, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    server.answers["/api/sims"] = (200, [SIM])
    assert PitracApi(server.api.url).sims() == [SIM]


def test_the_readme_names_the_tested_pitrac_revision():
    """The one place an owner is told which PiTrac to install."""

    from pathlib import Path

    from pitrac_easy_connect.pi.pitrac_api import TESTED_COMMIT

    readme = Path(__file__).resolve().parent.parent / "README.md"
    assert TESTED_COMMIT in readme.read_text(encoding="utf-8")

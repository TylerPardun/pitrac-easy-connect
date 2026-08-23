"""The shipped desktop page, not a test-only HTTP helper, owns the API header."""

import json
import re
import urllib.error
import urllib.request
from http import HTTPStatus

import pytest

from conftest import start_serving
from pitrac_easy_connect.companion.page import PAGE
from pitrac_easy_connect.companion.service import CompanionService
from pitrac_easy_connect.companion.web import CompanionHTTPServer, GUARD_HEADER
from pitrac_easy_connect.models import Simulator


@pytest.fixture
def desktop(tmp_path):
    service = CompanionService(
        config_path=tmp_path / "companion.json",
        simulator_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
        discovery_port=0,
        discovery_targets=["127.0.0.1"],
        search_seconds=0.05,
        research_seconds=0.05,
    )
    server = CompanionHTTPServer(("127.0.0.1", 0), service)
    stop = start_serving(server)
    yield "http://127.0.0.1:{}".format(server.server_port), server
    stop()
    service.close()


def request(base, path, body=None, headers=None):
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    supplied = dict(headers or {})
    if payload is not None:
        supplied["Content-Type"] = "application/json"
    call = urllib.request.Request(
        base + path,
        data=payload,
        headers=supplied,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(call, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def api_helper_source():
    return PAGE.split("function apiOptions(body){", 1)[1].split("async function api(", 1)[0]


def test_the_rendered_page_puts_the_guard_header_on_get_and_post_options():
    helper = api_helper_source()
    assert 'headers:{"X-PiTrac-App":"1"}' in helper
    assert 'body===undefined?"GET":"POST"' in helper
    assert 'if(body!==undefined)' in helper


def test_requests_with_the_page_header_are_accepted_for_get_and_search(desktop):
    base, _server = desktop
    headers = {GUARD_HEADER: "1"}

    get_status, _ = request(base, "/api/status", headers=headers)
    search_status, search = request(base, "/api/search", {}, headers=headers)

    assert get_status == HTTPStatus.OK
    assert search_status == HTTPStatus.OK
    assert "enclosures" in search


@pytest.mark.parametrize(
    "path,body", [("/api/status", None), ("/api/search", {})], ids=["GET", "POST"]
)
def test_an_unrelated_caller_without_the_page_header_is_rejected(desktop, path, body):
    base, _server = desktop
    status, answer = request(base, path, body)
    assert status == HTTPStatus.FORBIDDEN
    assert "did not come from Easy-Connect" in answer["error"]["failed"]


@pytest.mark.parametrize(
    "path,body", [("/api/status", None), ("/api/search", {})], ids=["GET", "POST"]
)
def test_a_cross_origin_request_remains_rejected(desktop, path, body):
    base, _server = desktop
    status, answer = request(
        base,
        path,
        body,
        headers={GUARD_HEADER: "1", "Origin": "https://not-pitrac.example"},
    )
    assert status == HTTPStatus.FORBIDDEN
    assert "another website" in answer["error"]["failed"]


def test_the_packaged_page_smoke_uses_real_get_search_and_state_change_routes():
    smoke = PAGE.split("async function runPageSmoke(){", 1)[1].split("\n}", 1)[0]
    assert 'api("/api/status")' in smoke
    assert 'api("/api/search",{})' in smoke
    assert 'api("/api/finish-setup",{done:false})' in smoke


def test_guarded_downloads_use_fetch_instead_of_unguarded_navigation():
    assert "async function apiDownload(path)" in PAGE
    assert 'await apiDownload("/api/backup")' in PAGE
    assert 'await apiDownload("/api/backup?identity=1&pairings=1")' in PAGE
    assert re.search(r'window\.location\.href\s*=\s*"/api/', PAGE) is None


def test_the_server_records_the_routes_release_smoke_must_observe(desktop):
    base, server = desktop
    headers = {GUARD_HEADER: "1"}
    request(base, "/api/status", headers=headers)
    request(base, "/api/search", {}, headers=headers)
    request(base, "/api/finish-setup", {"done": False}, headers=headers)

    counts = server.request_counts()
    assert counts["GET /api/status"] == 1
    assert counts["POST /api/search"] == 1
    assert counts["POST /api/finish-setup"] == 1

"""The enclosure handing out the software its owner's PC needs.

A new owner has a box, a card with a Wi-Fi password, and a Windows PC. Their PC
joins the enclosure's own signal to set up Wi-Fi anyway, so that is the moment to
give them the PC software too. It also works in a garage with no internet, which
is exactly where Direct Mode is supposed to be the answer.
"""

import threading

from conftest import start_serving
import urllib.error
import urllib.request

import pytest

from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.downloads import CompanionDownloads
from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.portal import PortalServer
from pitrac_easy_connect.pi.service import PiService, ServicePaths
from pitrac_easy_connect.pi.simulated import home_network_pi


@pytest.fixture
def served(tmp_path):
    service = PiService(
        home_network_pi(country="US"),
        paths=ServicePaths(tmp_path / "state"),
        pitrac=PitracInstallation(tmp_path / "s.json", tmp_path / "c.json"),
        relay_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
        link_port=0, discovery_port=0, manage_hostname=False, boot_grace=0.0)
    service.start()
    directory = service.paths.downloads
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "PiTracCompanion.exe").write_bytes(b"MZ" + b"\0" * 4096)
    (directory / "PiTracCompanion.pyz").write_bytes(b"PK" + b"\0" * 2048)
    (directory / "readme.txt").write_text("not a download")

    server = PortalServer(("127.0.0.1", 0), service)
    stop = start_serving(server)
    yield service, server, "http://127.0.0.1:{}".format(server.server_port), directory
    stop()
    service.stop()


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


# --- What is offered ------------------------------------------------------


def test_only_real_builds_are_offered(served):
    _service, _server, base, _directory = served
    status, body, _headers = fetch(base + "/api/downloads", {"X-PiTrac-Portal": "1"})
    assert status == 200
    names = [item["name"] for item in __import__("json").loads(body)["downloads"]]
    assert "PiTracCompanion.exe" in names
    assert "PiTracCompanion.pyz" in names
    assert "readme.txt" not in names, "arbitrary files must not be handed to a PC"


def test_windows_is_offered_first(served):
    _service, _server, base, _directory = served
    _status, body, _headers = fetch(base + "/api/downloads", {"X-PiTrac-Portal": "1"})
    downloads = __import__("json").loads(body)["downloads"]
    assert downloads[0]["name"].endswith(".exe"), "the simulator PC runs Windows"


def test_the_download_page_lists_what_is_available(served):
    _service, _server, base, _directory = served
    status, body, headers = fetch(base + "/companion")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    text = body.decode("utf-8")
    assert "PiTracCompanion.exe" in text
    assert "Run anyway" in text, "the SmartScreen warning has to be pre-empted"


def test_the_page_says_so_when_the_enclosure_carries_nothing(tmp_path, served):
    service, _server, base, directory = served
    for item in directory.iterdir():
        item.unlink()
    status, body, _headers = fetch(base + "/companion")
    assert status == 200
    text = body.decode("utf-8")
    assert "Nothing stored here" in text
    assert "Ask whoever set it up" in text, "it should say what to do about it"


def test_a_build_can_actually_be_downloaded(served):
    _service, _server, base, _directory = served
    status, body, headers = fetch(base + "/companion/PiTracCompanion.pyz")
    assert status == 200
    assert body.startswith(b"PK")
    assert "attachment" in headers["Content-Disposition"]
    assert "PiTracCompanion.pyz" in headers["Content-Disposition"]


# --- Refusing everything else ---------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "readme.txt",
        "..%2F..%2F..%2Fetc%2Fpasswd",
        "../../../etc/passwd",
        "%2e%2e%2fdevice.json",
        "does-not-exist.exe",
        ".hidden.exe",
    ],
)
def test_nothing_outside_the_downloads_directory_can_be_fetched(served, name):
    _service, _server, base, _directory = served
    status, _body, _headers = fetch(base + "/companion/" + name)
    assert status in (404, 421), "served something it should not have: {}".format(name)


def test_the_bare_directory_shows_the_page_rather_than_a_file(served):
    _service, _server, base, _directory = served
    status, body, headers = fetch(base + "/companion/")
    assert status == 200
    assert "text/html" in headers["Content-Type"]


def test_a_symlink_out_of_the_directory_is_refused(tmp_path, served):
    _service, _server, base, directory = served
    secret = tmp_path / "secret.exe"
    secret.write_bytes(b"should never be served")
    try:
        (directory / "sneaky.exe").symlink_to(secret)
    except OSError:
        pytest.skip("symlinks are not available here")
    status, _body, _headers = fetch(base + "/companion/sneaky.exe")
    assert status == 404


def test_resolution_is_refused_for_unsafe_names(tmp_path):
    downloads = CompanionDownloads(tmp_path)
    (tmp_path / "ok.exe").write_bytes(b"x")
    for name in ("../ok.exe", "sub/ok.exe", "ok.exe/", "-", "", "a" * 200 + ".exe"):
        assert downloads.resolve(name) is None, name
    assert downloads.resolve("ok.exe") is not None


# --- The build that ships -------------------------------------------------


def test_the_zipapp_actually_runs(tmp_path):
    """The .pyz is a real program, not just a zip with the right name."""

    import subprocess
    import sys
    import zipapp
    from pathlib import Path

    stage = tmp_path / "stage"
    stage.mkdir()
    source = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
    import shutil

    shutil.copytree(source, stage / "pitrac_easy_connect",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (stage / "__main__.py").write_text(
        "from pitrac_easy_connect.companion.app import main\nraise SystemExit(main())\n"
    )
    built = tmp_path / "Companion.pyz"
    zipapp.create_archive(stage, built)

    result = subprocess.run(
        [sys.executable, str(built), "--version"], capture_output=True, text=True, timeout=60
    )
    from pitrac_easy_connect import __version__

    assert result.returncode == 0, result.stderr
    assert __version__ in (result.stdout + result.stderr)

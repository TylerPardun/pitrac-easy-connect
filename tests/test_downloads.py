"""The enclosure handing out the software its owner's PC needs.

A new owner has a box, a card with a Wi-Fi password, and a Windows PC. Their PC
joins the enclosure's own signal to set up Wi-Fi anyway, so that is the moment
to give them the PC software too. It also works in a garage with no internet,
which is exactly where Direct Mode is supposed to be the answer.

Only the three real desktop assets are ever offered here. The published
`.pyz` is this project's own Pi-service update payload, and
`PiTrac-Easy-Connect-windows.zip` is the desktop app's own internal
self-update payload -- neither has ever been something a new owner should
run by hand, and this suite exists partly to prove that stays true even when
one is sitting right there in the downloads directory.
"""

import hashlib
import json
import threading

from conftest import start_serving
import base64
import urllib.error
import urllib.request

import pytest

import manifest_fixture
from pitrac_easy_connect.common import release_manifest
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.downloads import CompanionDownloads
from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.portal import PortalServer
from pitrac_easy_connect.pi.service import PiService, ServicePaths
from pitrac_easy_connect.pi.simulated import home_network_pi


MAC_ARM = "PiTrac-Easy-Connect-macos-apple-silicon.zip"
MAC_INTEL = "PiTrac-Easy-Connect-macos-intel.zip"
WINDOWS_INSTALLER = "PiTrac-Easy-Connect-windows-setup.exe"
#: The desktop's own internal self-update payload -- never offered here.
WINDOWS_UPDATE_PAYLOAD = "PiTrac-Easy-Connect-windows.zip"
#: The Pi service's own update payload -- never offered here either.
PI_SERVICE_PAYLOAD = "PiTrac-Easy-Connect-0.7.0.pyz"


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
    (directory / WINDOWS_INSTALLER).write_bytes(b"MZ" + b"\0" * 4096)
    (directory / MAC_INTEL).write_bytes(b"PK" + b"\0" * 2048)
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


def names_from(base):
    _status, body, _headers = fetch(base + "/api/downloads", {"X-PiTrac-Portal": "1"})
    return [item["name"] for item in json.loads(body)["downloads"]]


# --- What is offered ------------------------------------------------------


def test_only_real_desktop_builds_are_offered(served):
    _service, _server, base, _directory = served
    names = names_from(base)
    assert WINDOWS_INSTALLER in names
    assert MAC_INTEL in names
    assert "readme.txt" not in names, "arbitrary files must not be handed to a PC"


def test_windows_is_offered_first(served):
    _service, _server, base, _directory = served
    status, body, _headers = fetch(base + "/api/downloads", {"X-PiTrac-Portal": "1"})
    downloads = json.loads(body)["downloads"]
    assert downloads[0]["name"] == WINDOWS_INSTALLER, "the simulator PC runs Windows"


def test_the_download_page_lists_what_is_available(served):
    _service, _server, base, _directory = served
    status, body, headers = fetch(base + "/companion")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    text = body.decode("utf-8")
    assert WINDOWS_INSTALLER in text
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
    status, body, headers = fetch(base + "/companion/" + MAC_INTEL)
    assert status == 200
    assert body.startswith(b"PK")
    assert "attachment" in headers["Content-Disposition"]
    assert MAC_INTEL in headers["Content-Disposition"]


# --- What is never offered, no matter what is sitting there ---------------


def test_the_pi_services_own_pyz_is_never_offered_to_a_desktop_user(served):
    """Replaces a test that offered the enclosure's own update payload as a
    generic "Any computer with Python" desktop download -- that confusion,
    not a missing feature, is the bug this rewrite fixes."""

    _service, _server, base, directory = served
    (directory / PI_SERVICE_PAYLOAD).write_bytes(b"PK" + b"\0" * 4096)

    assert PI_SERVICE_PAYLOAD not in names_from(base)
    status, _body, _headers = fetch(base + "/companion/" + PI_SERVICE_PAYLOAD)
    assert status == 404


def test_the_desktops_own_update_payload_is_never_offered_as_the_windows_install(
    served,
):
    """The zip the desktop app's self-updater fetches, not what a new owner
    should run -- offering it here is exactly what item 3's public-download
    fix was about, from the other direction."""

    _service, _server, base, directory = served
    (directory / WINDOWS_UPDATE_PAYLOAD).write_bytes(b"PK" + b"\0" * 4096)

    assert WINDOWS_UPDATE_PAYLOAD not in names_from(base)
    status, _body, _headers = fetch(base + "/companion/" + WINDOWS_UPDATE_PAYLOAD)
    assert status == 404


@pytest.mark.parametrize("name", [
    "PiTrac-Easy-Connect-linux-x86_64.zip",
    "PiTracCompanion.pyz",
    "PiTracCompanion.exe",
    "installer.msi",
    "PiTrac-Easy-Connect-macos-apple-silicon.ZIP",
])
def test_nothing_but_the_three_exact_supported_names_is_recognized(served, name):
    _service, _server, base, directory = served
    (directory / name).write_bytes(b"x" * 64)

    assert name not in names_from(base)
    status, _body, _headers = fetch(base + "/companion/" + name)
    assert status == 404


# --- Verifying against a signed manifest, when one is present -------------


@pytest.fixture(autouse=True)
def pinned(monkeypatch):
    manifest_fixture.pin(monkeypatch)


def _write_manifest(directory, assets):
    manifest = manifest_fixture.manifest_for(assets, version="0.9.0", pi_asset="")
    payload, signature = manifest_fixture.signed(manifest)
    (directory / release_manifest.MANIFEST_ASSET).write_bytes(payload)
    (directory / release_manifest.SIGNATURE_ASSET).write_bytes(signature)


def test_a_file_matching_a_present_signed_manifest_is_offered(served):
    _service, _server, base, directory = served
    payload = b"a real build" + b"\0" * 4096
    (directory / MAC_ARM).write_bytes(payload)
    _write_manifest(directory, {MAC_ARM: payload, WINDOWS_INSTALLER: b"MZ" + b"\0" * 4096})

    assert MAC_ARM in names_from(base)
    status, body, _headers = fetch(base + "/companion/" + MAC_ARM)
    assert status == 200
    assert body == payload


@pytest.mark.parametrize("tamper", [
    lambda real: real + b"tampered",              # size and digest both change
    lambda real: b"X" + real[1:],                 # same size, digest only
])
def test_a_file_that_does_not_match_a_present_signed_manifest_is_refused(served, tamper):
    """A stored copy that was swapped or corrupted must not be handed out."""

    _service, _server, base, directory = served
    real = b"a real build" + b"\0" * 4096
    (directory / MAC_ARM).write_bytes(real)
    _write_manifest(directory, {MAC_ARM: real, WINDOWS_INSTALLER: b"MZ" + b"\0" * 4096})

    # Now tamper with the stored file after the manifest was written.
    (directory / MAC_ARM).write_bytes(tamper(real))

    assert MAC_ARM not in names_from(base)
    status, _body, _headers = fetch(base + "/companion/" + MAC_ARM)
    assert status == 404


def test_an_unsigned_manifest_pair_is_not_trusted(served):
    """A manifest file sitting there proves nothing by itself."""

    _service, _server, base, directory = served
    real = b"a real build" + b"\0" * 4096
    (directory / MAC_ARM).write_bytes(real)
    manifest = manifest_fixture.manifest_for(
        {MAC_ARM: real, WINDOWS_INSTALLER: b"MZ" + b"\0" * 4096},
        version="0.9.0", pi_asset="",
    )
    payload, _real_signature = manifest_fixture.signed(manifest)
    (directory / release_manifest.MANIFEST_ASSET).write_bytes(payload)
    (directory / release_manifest.SIGNATURE_ASSET).write_bytes(
        base64.b64encode(bytes(64))
    )

    # Falls back to offering it unverified rather than refusing outright --
    # this is best-effort verification, not a hard requirement (see
    # downloads.py's docstring), so a bad signature must not be worse than
    # having none.
    assert MAC_ARM in names_from(base)


def test_the_manifest_files_themselves_are_never_offered_as_downloads(served):
    _service, _server, base, directory = served
    real = b"a real build" + b"\0" * 4096
    (directory / MAC_ARM).write_bytes(real)
    _write_manifest(directory, {MAC_ARM: real, WINDOWS_INSTALLER: b"MZ" + b"\0" * 4096})

    names = names_from(base)
    assert release_manifest.MANIFEST_ASSET not in names
    assert release_manifest.SIGNATURE_ASSET not in names


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
        (directory / WINDOWS_INSTALLER).unlink()
        (directory / WINDOWS_INSTALLER).symlink_to(secret)
    except OSError:
        pytest.skip("symlinks are not available here")
    status, _body, _headers = fetch(base + "/companion/" + WINDOWS_INSTALLER)
    assert status == 404


def test_resolution_is_refused_for_unsafe_or_unrecognized_names(tmp_path):
    downloads = CompanionDownloads(tmp_path)
    (tmp_path / WINDOWS_INSTALLER).write_bytes(b"x")
    for name in (
        "../" + WINDOWS_INSTALLER, "sub/" + WINDOWS_INSTALLER, WINDOWS_INSTALLER + "/",
        "-", "", "a" * 200 + ".exe", "not-a-real-asset.exe",
    ):
        assert downloads.resolve(name) is None, name
    assert downloads.resolve(WINDOWS_INSTALLER) is not None


# --- The build that ships -------------------------------------------------


def test_the_pi_services_zipapp_is_a_real_program_not_just_a_named_zip():
    """The .pyz packaging/build-pi-archive.sh builds -- the enclosure's own
    update payload, never a desktop download (see test_downloads.py above)."""

    import shutil
    import subprocess
    import sys
    import zipapp
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        tmp_path = Path(raw)
        stage = tmp_path / "stage"
        stage.mkdir()
        source = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
        shutil.copytree(source, stage / "pitrac_easy_connect",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (stage / "__main__.py").write_text(
            "from pitrac_easy_connect.pi.app import main\nraise SystemExit(main())\n"
        )
        built = tmp_path / "PiTrac-Easy-Connect.pyz"
        zipapp.create_archive(stage, built)

        result = subprocess.run(
            [sys.executable, str(built), "--version"],
            capture_output=True, text=True, timeout=60,
        )
    from pitrac_easy_connect import __version__

    assert result.returncode == 0, result.stderr
    assert __version__ in (result.stdout + result.stderr)

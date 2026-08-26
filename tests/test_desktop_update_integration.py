"""The whole desktop self-update lifecycle, end to end, against a real local
HTTP server standing in for GitHub -- the same pattern test_pi_updates.py
uses for the enclosure's own archive updater. Nothing here touches the real
GitHub API, and nothing here spawns a real second process: the helper
handoff itself (a real subprocess, tested in isolation in
test_self_update.py) is monkeypatched at the one boundary where it would
otherwise try to run a binary that does not exist in a test environment.
"""

import hashlib
import json
import os
import stat
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import start_serving
from pitrac_easy_connect.common.updates import DesktopUpdateState
from pitrac_easy_connect.companion import self_update
from pitrac_easy_connect.companion import service as service_module
from pitrac_easy_connect.companion.service import CompanionService


def _make_windows_package_zip(path, version_ok=True, version="0.4.5"):
    """The archive shape a real Windows release publishes.

    make_service() below constructs DesktopReleaseUpdater for
    system="Windows", which is what actually gets checked against
    PLATFORM_ASSET_NAMES -- unlike _make_current_install, this fixture
    stands in for a real published desktop asset, so it has to agree with
    self_update.executable_path/helper_path/package_manifest for that exact
    system, ".exe" suffix included, or stage_update's own structural
    validation (exercised for real here, not mocked) rejects it.
    """

    root = "PiTrac Easy-Connect/"
    padding = b"x" * (300 * 1024)
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo(root + "PiTrac Easy-Connect.exe")
        info.external_attr = (0o755 | 0o100000) << 16  # regular file, executable
        archive.writestr(info, b"not a real binary, probed via a fake --version\n" + padding)
        helper = zipfile.ZipInfo(root + "PiTrac Updater.exe")
        helper.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(helper, b"helper")
        archive.writestr(root + "pitrac-install.json", json.dumps(
            self_update.package_manifest(version, system="Windows", machine="x86_64")
        ))
        for legal in ("LICENSE", "NOTICE.md", "THIRD-PARTY-LICENCES.txt"):
            archive.writestr(root + legal, legal)
    return path.read_bytes()


def _make_current_install(tmp_path, version="0.4.4"):
    # Must agree with _make_windows_package_zip and make_service() on the
    # platform: this is the already-installed side of the same Windows
    # desktop the candidate is a build for. prepare_transaction validates
    # both the old and new install roots' declared platform, so a mismatch
    # here fails as "the install manifest has the wrong platform" -- not
    # because anything about the update is actually broken.
    root = tmp_path / "installed" / self_update.APP_NAME
    executable = self_update.executable_path(root, system="Windows")
    helper = self_update.helper_path(root, system="Windows")
    executable.parent.mkdir(parents=True)
    executable.write_text("old")
    # A helper that can actually run. Preparing a transaction now starts this
    # copy and requires it to answer, because the application shuts itself
    # down in favour of it -- a file with the executable bit set and nothing
    # behind it was never a helper, it just looked like one to a stat() call.
    helper.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pitrac_easy_connect.companion.self_update import run_helper_cli\n"
        "raise SystemExit(run_helper_cli(sys.argv[1:]))\n"
    )
    executable.chmod(0o755)
    helper.chmod(0o755)
    self_update.write_package_manifest(root, version, system="Windows", machine="x86_64")
    for legal in ("LICENSE", "NOTICE.md", "THIRD-PARTY-LICENCES.txt"):
        (root / legal).write_text(legal)
    return root


class _Upstream:
    """A tiny stand-in for api.github.com plus the asset download host."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.release = {"tag_name": "v0.4.4"}  # nothing published yet
        self.package_bytes = b""
        self.documents = {}
        self._lock = threading.Lock()

        upstream_self = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with upstream_self._lock:
                    if self.path.endswith("/releases/latest"):
                        body = json.dumps(upstream_self.release).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    if self.path == "/download/package.zip":
                        body = upstream_self.package_bytes
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    documents = upstream_self.documents
                    if self.path in documents:
                        body = documents[self.path]
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                self.send_response(404)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.stop = start_serving(self.server)
        self.base = "http://127.0.0.1:{}".format(self.server.server_port)

    def publish(self, version, package_bytes):
        digest = hashlib.sha256(package_bytes).hexdigest()
        with self._lock:
            self.package_bytes = package_bytes
            self.release = {
                "tag_name": "v" + version,
                "html_url": self.base + "/releases/v" + version,
                "assets": [
                    {
                        "name": "PiTrac-Easy-Connect-windows.zip",
                        "browser_download_url": self.base + "/download/package.zip",
                        "digest": "sha256:" + digest,
                    }
                ],
            }

    def publish_signed(self, version, package_bytes, *, manifest=None):
        """Publish a release the way it will actually look from 0.9.0 on:
        the archive plus a signed manifest describing exactly it."""

        import manifest_fixture

        # The real DESKTOP_PLATFORMS entry for Windows names this exact
        # filename, which manifest_fixture.manifest_for matches automatically.
        asset_name = "PiTrac-Easy-Connect-windows.zip"
        described = manifest or manifest_fixture.manifest_for(
            {asset_name: package_bytes}, version=version, pi_asset="",
        )
        assert described.get("desktop", {}).get("platforms"), (
            "no desktop platform matched {}; DESKTOP_PLATFORMS or this "
            "fixture's asset name has drifted".format(asset_name)
        )
        payload, signature = manifest_fixture.signed(described)
        with self._lock:
            self.package_bytes = package_bytes
            self.documents = {"/manifest": payload, "/manifest.sig": signature}
            from pitrac_easy_connect.common import release_manifest as rm
            self.release = {
                "tag_name": "v" + version,
                "html_url": self.base + "/releases/v" + version,
                "assets": [
                    {"name": asset_name,
                     "browser_download_url": self.base + "/download/package.zip"},
                    {"name": rm.MANIFEST_ASSET,
                     "browser_download_url": self.base + "/manifest"},
                    {"name": rm.SIGNATURE_ASSET,
                     "browser_download_url": self.base + "/manifest.sig"},
                ],
            }

    def close(self):
        self.stop()


@pytest.fixture
def upstream(tmp_path):
    built = _Upstream(tmp_path)
    yield built
    built.close()


def _wait_for(predicate, message, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(message)


def make_service(tmp_path, upstream, *, installed="0.4.4"):
    service = CompanionService(
        config_path=tmp_path / "companion.json", computer_name="PC",
        version=installed, periodic_update_check_seconds=0, startup_update_check=False,
    )
    # A packaged Windows build, talking to the fake upstream instead of GitHub.
    from pitrac_easy_connect.common.updates import DesktopReleaseUpdater

    service.desktop_updates = DesktopReleaseUpdater(
        installed, api_base=upstream.base, system="Windows", machine="x86_64",
    )
    service._uses_git_updater = False
    return service


def test_packaged_service_selects_assets_for_its_manifest_architecture(tmp_path, monkeypatch):
    from pitrac_easy_connect.common.updates import PACKAGED

    monkeypatch.setattr(service_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(service_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(service_module.Updater, "kind", lambda _self: PACKAGED)
    monkeypatch.setattr(
        self_update, "packaged_architecture", lambda **_arguments: "x86_64"
    )
    service = CompanionService(
        config_path=tmp_path / "companion.json",
        version="0.4.6",
        periodic_update_check_seconds=0,
        startup_update_check=False,
    )
    try:
        assert service.desktop_updates.machine == "x86_64"
        assert service.desktop_updates.asset_name() == "PiTrac-Easy-Connect-windows.zip"
    finally:
        service.close()


def test_v044_finds_nothing_then_detects_v045_once_published(tmp_path, upstream):
    service = make_service(tmp_path, upstream)
    try:
        service.check_for_updates()
        _wait_for(lambda: not service._update_check_in_progress, "first check did not finish")
        status = service.status()["update"]
        assert status["available"] is False

        package = tmp_path / "package.zip"
        payload = _make_windows_package_zip(package)
        upstream.publish("0.4.5", payload)

        service.check_for_updates()  # forced, asynchronous
        _wait_for(lambda: not service._update_check_in_progress, "forced check did not finish")
        status = service.status()["update"]
        assert status["available"] is True
        assert status["latest"] == "v0.4.5"
        assert status["desktop"]["state"] == "available"
        assert status["desktop"]["availableVersion"] == "v0.4.5"
    finally:
        service.close()


def test_the_full_download_verify_stage_sequence_reaches_ready_to_restart(
    tmp_path, upstream, monkeypatch
):
    package = tmp_path / "package.zip"
    payload = _make_windows_package_zip(package)
    upstream.publish("0.4.5", payload)

    service = make_service(tmp_path, upstream)
    try:
        service.check_for_updates()

        monkeypatch.setattr(self_update, "_probe_version", lambda _exe, timeout=15.0: "0.4.5")
        # The staging directory used by the download must not be the real
        # per-user one during a test.
        monkeypatch.setattr(self_update, "staging_dir", lambda base=None: tmp_path / "staging")
        current = _make_current_install(tmp_path)
        monkeypatch.setattr(self_update, "current_install_root", lambda **_kwargs: current)

        result = service.download_desktop_update()
        assert result["started"] is True

        _wait_for(
            lambda: service.status()["update"]["desktop"]["state"]
            in ("ready-to-restart", "download-failed", "verify-failed", "install-failed"),
            "the download/verify/stage sequence never finished",
        )

        desktop = service.status()["update"]["desktop"]
        assert desktop["state"] == "ready-to-restart", desktop
        assert desktop["stagedReady"] is True
        assert desktop["stagedTargetVersion"] == "0.4.5"
    finally:
        service.close()


def test_a_checksum_mismatch_fails_verification_not_installation(tmp_path, upstream, monkeypatch):
    package = tmp_path / "package.zip"
    real_payload = _make_windows_package_zip(package)
    upstream.publish("0.4.5", real_payload)
    # Corrupt what is actually served after the checksum was already
    # published, the way a truncated or tampered download would arrive.
    upstream.package_bytes = real_payload + b"corruption"

    service = make_service(tmp_path, upstream)
    try:
        service.check_for_updates()
        monkeypatch.setattr(self_update, "staging_dir", lambda base=None: tmp_path / "staging")
        current = _make_current_install(tmp_path)
        monkeypatch.setattr(self_update, "current_install_root", lambda **_kwargs: current)

        service.download_desktop_update()
        _wait_for(
            lambda: service.status()["update"]["desktop"]["state"] != "downloading",
            "verification never completed",
        )
        desktop = service.status()["update"]["desktop"]
        assert desktop["state"] == "verify-failed"
        assert "checksum" in desktop["detail"]
    finally:
        service.close()


def test_install_and_restart_spawns_the_helper_and_then_exits(tmp_path, upstream, monkeypatch):
    """The desktop-before-Pi rule and the restart handoff meet here: once
    staged, confirming the install must hand off to the helper (never touch
    the running files itself) and report a state meaning "about to exit.\""""

    package = tmp_path / "package.zip"
    payload = _make_windows_package_zip(package)
    upstream.publish("0.4.5", payload)

    service = make_service(tmp_path, upstream)
    try:
        service.check_for_updates()
        monkeypatch.setattr(self_update, "_probe_version", lambda _exe, timeout=15.0: "0.4.5")
        monkeypatch.setattr(self_update, "staging_dir", lambda base=None: tmp_path / "staging")
        current = _make_current_install(tmp_path)
        monkeypatch.setattr(self_update, "current_install_root", lambda **_kwargs: current)

        service.download_desktop_update()
        _wait_for(
            lambda: service.status()["update"]["desktop"]["state"] == "ready-to-restart",
            "staging never completed",
        )

        spawned = {}

        def fake_spawn(journal_path, *, wait_pid=None):
            spawned["journal_path"] = journal_path
            spawned["wait_pid"] = wait_pid

        monkeypatch.setattr(self_update, "spawn_helper", fake_spawn)
        # The window-close call this triggers has nothing to close in a
        # headless test service; make it a no-op rather than erroring.
        monkeypatch.setattr(service, "close_native_window", lambda: None)

        result = service.install_and_restart()
        assert result["applied"] is True
        assert result["needsRestart"] is True
        assert spawned["wait_pid"] is not None
        assert spawned["journal_path"] is not None
    finally:
        service.close()


def test_a_signed_release_reaches_ready_to_restart(tmp_path, upstream, monkeypatch):
    """From 0.9.0 on, this is the real shape: an archive plus a manifest."""

    import manifest_fixture
    manifest_fixture.pin(monkeypatch)

    package = tmp_path / "package.zip"
    payload = _make_windows_package_zip(package, version="0.9.0")
    upstream.publish_signed("0.9.0", payload)

    service = make_service(tmp_path, upstream, installed="0.8.9")
    try:
        service.check_for_updates()
        monkeypatch.setattr(self_update, "_probe_version", lambda _exe, timeout=15.0: "0.9.0")
        monkeypatch.setattr(self_update, "staging_dir", lambda base=None: tmp_path / "staging")
        current = _make_current_install(tmp_path, version="0.8.9")
        monkeypatch.setattr(self_update, "current_install_root", lambda **_kwargs: current)

        assert service.download_desktop_update()["started"] is True
        _wait_for(
            lambda: service.status()["update"]["desktop"]["state"]
            in ("ready-to-restart", "download-failed", "verify-failed", "install-failed"),
            "the signed download/verify/stage sequence never finished",
        )
        desktop = service.status()["update"]["desktop"]
        assert desktop["state"] == "ready-to-restart", desktop
    finally:
        service.close()


def test_a_release_with_no_manifest_is_refused_not_installed_unsigned(
    tmp_path, upstream, monkeypatch
):
    """The unsigned digest fallback is for releases that predate manifests.

    0.9.0 is not one of them, so a release claiming to be 0.9.0 with no
    manifest at all must be refused -- not silently trusted the old way.
    """

    import manifest_fixture
    manifest_fixture.pin(monkeypatch)

    package = tmp_path / "package.zip"
    payload = _make_windows_package_zip(package, version="0.9.0")
    upstream.publish("0.9.0", payload)  # the old, unsigned publish() path

    service = make_service(tmp_path, upstream, installed="0.8.9")
    try:
        service.check_for_updates()
        monkeypatch.setattr(self_update, "_probe_version", lambda _exe, timeout=15.0: "0.9.0")
        monkeypatch.setattr(self_update, "staging_dir", lambda base=None: tmp_path / "staging")
        current = _make_current_install(tmp_path, version="0.8.9")
        monkeypatch.setattr(self_update, "current_install_root", lambda **_kwargs: current)

        assert service.download_desktop_update()["started"] is True
        _wait_for(
            lambda: service.status()["update"]["desktop"]["state"]
            in ("ready-to-restart", "download-failed", "verify-failed", "install-failed"),
            "the unsigned 0.9.0 release was never settled one way or the other",
        )
        desktop = service.status()["update"]["desktop"]
        assert desktop["state"] == "verify-failed", desktop
        assert "no signed manifest" in desktop["detail"]
    finally:
        service.close()


def test_a_manifest_signed_for_a_different_release_is_refused(
    tmp_path, upstream, monkeypatch
):
    """A genuine signature over the wrong release is a downgrade attack, not proof."""

    import manifest_fixture
    manifest_fixture.pin(monkeypatch)

    package = tmp_path / "package.zip"
    payload = _make_windows_package_zip(package, version="0.9.0")
    stale_manifest = manifest_fixture.manifest_for(
        {"PiTrac-Easy-Connect-windows.zip": b"an old build entirely"},
        version="0.9.0-old-content",
    )
    upstream.publish_signed("0.9.0", payload, manifest=stale_manifest)

    service = make_service(tmp_path, upstream, installed="0.8.9")
    try:
        service.check_for_updates()
        monkeypatch.setattr(self_update, "_probe_version", lambda _exe, timeout=15.0: "0.9.0")
        monkeypatch.setattr(self_update, "staging_dir", lambda base=None: tmp_path / "staging")
        current = _make_current_install(tmp_path, version="0.8.9")
        monkeypatch.setattr(self_update, "current_install_root", lambda **_kwargs: current)

        assert service.download_desktop_update()["started"] is True
        _wait_for(
            lambda: service.status()["update"]["desktop"]["state"]
            in ("ready-to-restart", "download-failed", "verify-failed", "install-failed"),
            "the mismatched manifest was never settled",
        )
        assert service.status()["update"]["desktop"]["state"] == "verify-failed"
    finally:
        service.close()

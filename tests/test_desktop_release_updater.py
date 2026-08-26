"""Asset selection, checking, downloading, and verifying the desktop's own
packaged release.

A v0.4.4 desktop left running never noticed v0.4.5 was published: a check
made before the release existed was cached for six hours regardless of
outcome, and nothing re-checked in between. These tests pin the fix (a
two-tier cache that retries failures sooner and refreshes successes within
the requested 10-30 minute window) and the new packaged-install groundwork
(platform asset selection, checksum verification, download limits) that
never existed for the desktop before.
"""

import json
import threading
import time

import pytest

from conftest import start_serving
from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.common.updates import (
    RECHECK_SECONDS_FAILED,
    RECHECK_SECONDS_OK,
    DesktopReleaseUpdater,
    normalize_arch,
    select_desktop_asset,
)


class FakeClock:
    def __init__(self):
        self.now = 1_700_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# --- Asset selection --------------------------------------------------------


@pytest.mark.parametrize(
    "system,machine,expected",
    [
        ("Darwin", "arm64", "PiTrac-Easy-Connect-macos-apple-silicon.zip"),
        ("Darwin", "aarch64", "PiTrac-Easy-Connect-macos-apple-silicon.zip"),
        ("Darwin", "x86_64", "PiTrac-Easy-Connect-macos-intel.zip"),
        ("Windows", "AMD64", "PiTrac-Easy-Connect-windows.zip"),
        ("Windows", "x86_64", "PiTrac-Easy-Connect-windows.zip"),
    ],
)
def test_the_right_asset_is_selected_for_each_platform(system, machine, expected):
    assert select_desktop_asset(system, machine) == expected


def test_arm64_is_never_offered_the_intel_package_or_vice_versa():
    assert select_desktop_asset("Darwin", "arm64") != select_desktop_asset("Darwin", "x86_64")


@pytest.mark.parametrize(
    "system,machine",
    [
        ("Darwin", "armv7l"), ("Windows", "arm64"), ("Linux", "arm64"), ("FreeBSD", "x86_64"),
        # Linux desktop distribution was removed (docs/distribution.md); this
        # used to be a supported combination, resolving to a filename no
        # release has published in years. It has to refuse cleanly now, the
        # same as any other platform nothing is built for.
        ("Linux", "x86_64"),
    ],
)
def test_an_unsupported_platform_or_architecture_is_refused_not_defaulted(system, machine):
    with pytest.raises(EasyConnectError) as caught:
        select_desktop_asset(system, machine)
    assert caught.value.info.code == "PT-UPD-001"


def test_arch_aliases_normalize_to_the_same_family():
    assert normalize_arch("aarch64") == normalize_arch("arm64") == "arm64"
    assert normalize_arch("amd64") == normalize_arch("AMD64") == normalize_arch("x86_64") == "x86_64"


# --- Detecting a new release -------------------------------------------------


def fake_release(tag, assets=None, **extra):
    payload = {"tag_name": tag, "html_url": "https://example.invalid/releases/" + tag, **extra}
    if assets is not None:
        payload["assets"] = assets
    return lambda _url: payload


def _asset(name, digest=None):
    entry = {"name": name, "browser_download_url": "https://example.invalid/dl/" + name}
    if digest:
        entry["digest"] = "sha256:" + digest
    return entry


def test_v044_detects_v045():
    updater = DesktopReleaseUpdater(
        "0.4.4", system="Windows", machine="x86_64",
        fetch_json=fake_release(
            "v0.4.5", assets=[_asset("PiTrac-Easy-Connect-windows.zip", "a" * 64)]
        ),
    )
    status = updater.check()
    assert status.available is True
    assert status.latest == "v0.4.5"


def test_a_check_made_before_publication_detects_it_after_the_cache_window(monkeypatch):
    clock = FakeClock()
    responses = [{"tag_name": "v0.4.4"}, {"tag_name": "v0.4.5"}]

    def fetch(_url):
        return responses[0] if len(responses) == 1 else responses.pop(0)

    updater = DesktopReleaseUpdater(
        "0.4.4", system="Windows", machine="x86_64", fetch_json=fetch, clock=clock
    )
    first = updater.check()
    assert first.available is False

    # Still within the successful-check window: the stale "up to date"
    # answer must not be treated as current forever, but it is reused here.
    clock.advance(RECHECK_SECONDS_OK - 1)
    assert updater.check().available is False

    # The window elapses -- exactly the periodic re-check the app needs.
    clock.advance(2)
    second = updater.check()
    assert second.available is True
    assert second.latest == "v0.4.5"


def test_a_forced_check_bypasses_the_cache_immediately():
    calls = []

    def counting(_url):
        calls.append(1)
        return {"tag_name": "v0.4.4"}

    updater = DesktopReleaseUpdater("0.4.4", system="Windows", machine="x86_64", fetch_json=counting)
    updater.check()
    updater.check()  # cached, no new call
    assert len(calls) == 1
    updater.check(force=True)
    assert len(calls) == 2


def test_a_failed_check_retries_sooner_than_a_successful_one(monkeypatch):
    clock = FakeClock()
    calls = []

    def explode(_url):
        calls.append(1)
        raise OSError("no network")

    updater = DesktopReleaseUpdater(
        "0.4.4", system="Windows", machine="x86_64", fetch_json=explode, clock=clock
    )
    status = updater.check()
    assert "Could not check" in status.detail

    clock.advance(RECHECK_SECONDS_FAILED - 1)
    updater.check()
    assert len(calls) == 1, "retried before its own shorter window elapsed"

    clock.advance(2)
    updater.check()
    assert len(calls) == 2, "did not retry a failed check sooner than a successful one"

    # The failed-check window is much shorter than six hours (the old
    # blanket cache) and than the successful-check window.
    assert RECHECK_SECONDS_FAILED < RECHECK_SECONDS_OK


def test_two_concurrent_checks_make_exactly_one_network_call():
    calls = []
    started = threading.Event()
    release_call = threading.Event()

    def slow(_url):
        calls.append(1)
        started.set()
        release_call.wait(timeout=5)
        return {"tag_name": "v0.4.5"}

    updater = DesktopReleaseUpdater("0.4.4", system="Windows", machine="x86_64", fetch_json=slow)

    results = []

    def call_check():
        results.append(updater.check(force=True))

    first = threading.Thread(target=call_check)
    first.start()
    started.wait(timeout=5)
    second = threading.Thread(target=call_check)
    second.start()
    time.sleep(0.1)  # give the second thread a chance to arrive and block
    release_call.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert len(calls) == 1, "a concurrent second check made its own network request"
    assert len(results) == 2
    assert results[0].latest == results[1].latest == "v0.4.5"


def test_cached_status_does_not_wait_for_a_network_check():
    started = threading.Event()
    release_call = threading.Event()

    def slow(_url):
        started.set()
        release_call.wait(timeout=5)
        return {"tag_name": "v0.4.5"}

    updater = DesktopReleaseUpdater(
        "0.4.4", system="Windows", machine="x86_64", fetch_json=slow
    )
    checker = threading.Thread(target=updater.check)
    checker.start()
    assert started.wait(timeout=2)

    returned = threading.Event()
    reader = threading.Thread(target=lambda: (updater.cached_status(), returned.set()))
    reader.start()
    assert returned.wait(timeout=1), "cached status blocked behind network I/O"

    release_call.set()
    checker.join(timeout=5)
    reader.join(timeout=5)


def test_draft_and_prerelease_are_ignored_by_default():
    updater = DesktopReleaseUpdater(
        "0.4.4", system="Windows", machine="x86_64",
        fetch_json=fake_release("v0.5.0", draft=True),
    )
    assert updater.check().available is False


def test_prerelease_is_ignored_by_default_too():
    updater = DesktopReleaseUpdater(
        "0.4.4", system="Windows", machine="x86_64",
        fetch_json=fake_release("v0.5.0", prerelease=True),
    )
    assert updater.check().available is False


def test_a_dev_setting_can_opt_into_prereleases():
    updater = DesktopReleaseUpdater(
        "0.4.4", system="Windows", machine="x86_64", allow_prerelease=True,
        fetch_json=fake_release("v0.5.0", prerelease=True, assets=[
            _asset("PiTrac-Easy-Connect-windows.zip", "a" * 64)
        ]),
    )
    assert updater.check().available is True


def test_a_downgrade_is_never_offered():
    updater = DesktopReleaseUpdater(
        "0.9.0", system="Windows", machine="x86_64", fetch_json=fake_release("v0.4.5")
    )
    assert updater.check().available is False


@pytest.mark.parametrize("payload", [{}, {"tag_name": ""}, {"tag_name": "not-a-version"}, {"other": 1}])
def test_malformed_release_metadata_does_not_produce_an_update(payload):
    updater = DesktopReleaseUpdater(
        "0.4.4", system="Windows", machine="x86_64", fetch_json=lambda _url, p=payload: p
    )
    assert updater.check().available is False


def test_a_release_with_no_matching_asset_is_available_but_cannot_apply():
    updater = DesktopReleaseUpdater(
        "0.4.4", system="Windows", machine="x86_64",
        # A real asset name, but for a different platform than the one
        # being checked -- so it must not resolve for Windows.
        fetch_json=fake_release(
            "v0.5.0", assets=[_asset("PiTrac-Easy-Connect-macos-intel.zip", "a" * 64)]
        ),
    )
    status = updater.check()
    assert status.available is True
    assert status.can_apply is False
    assert "no" in status.detail and "package" in status.detail


# --- Checksums ----------------------------------------------------------


def test_the_digest_field_is_preferred_when_present():
    updater = DesktopReleaseUpdater("0.4.4", system="Windows", machine="x86_64")
    release = fake_release(
        "v0.4.5", assets=[_asset("PiTrac-Easy-Connect-windows.zip", "b" * 64)]
    )("ignored")
    assert updater.expected_sha256(release, "PiTrac-Easy-Connect-windows.zip") == "b" * 64


def test_sha256sums_is_used_when_no_digest_field_is_published():
    sums_text = "{}  PiTrac-Easy-Connect-windows.zip\n{}  other-file.zip\n".format(
        "c" * 64, "d" * 64
    )
    updater = DesktopReleaseUpdater("0.4.4", system="Windows", machine="x86_64")
    release = {
        "tag_name": "v0.4.5",
        "assets": [
            {"name": "PiTrac-Easy-Connect-windows.zip"},  # no digest field
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://example.invalid/SHA256SUMS.txt"},
        ],
    }
    updater._fetch_text = lambda _url: sums_text
    assert updater.expected_sha256(release, "PiTrac-Easy-Connect-windows.zip") == "c" * 64


def test_no_checksum_anywhere_is_reported_as_missing_not_guessed():
    updater = DesktopReleaseUpdater("0.4.4", system="Windows", machine="x86_64")
    release = {"tag_name": "v0.4.5", "assets": [{"name": "PiTrac-Easy-Connect-windows.zip"}]}
    assert updater.expected_sha256(release, "PiTrac-Easy-Connect-windows.zip") is None


def test_verify_detects_a_checksum_mismatch(tmp_path):
    updater = DesktopReleaseUpdater("0.4.4", system="Windows", machine="x86_64")
    path = tmp_path / "package.zip"
    path.write_bytes(b"real bytes")
    assert updater.verify(path, "0" * 64) is False
    import hashlib

    real = hashlib.sha256(b"real bytes").hexdigest()
    assert updater.verify(path, real) is True


# --- Download limits and cleanup --------------------------------------------


def _serve_bytes(payload: bytes, *, content_length: "int|None" = None):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            length = content_length if content_length is not None else len(payload)
            self.send_header("Content-Length", str(length))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    stop = start_serving(server)
    return "http://127.0.0.1:{}/download".format(server.server_port), stop


def test_a_download_within_limits_is_kept(tmp_path):
    payload = b"x" * (250 * 1024)
    url, stop = _serve_bytes(payload)
    try:
        updater = DesktopReleaseUpdater("0.4.4", system="Windows", machine="x86_64")
        path = updater.download(url, tmp_path)
        assert path.read_bytes() == payload
    finally:
        stop()


def test_a_download_too_small_to_be_real_is_refused_and_cleaned_up(tmp_path):
    payload = b"tiny"
    url, stop = _serve_bytes(payload)
    try:
        updater = DesktopReleaseUpdater("0.4.4", system="Windows", machine="x86_64")
        with pytest.raises(ValueError):
            updater.download(url, tmp_path)
        assert not (tmp_path / "download.part").exists()
    finally:
        stop()


def test_an_oversized_download_is_rejected_and_cleaned_up(tmp_path):
    payload = b"y" * (300 * 1024)
    url, stop = _serve_bytes(payload)
    try:
        updater = DesktopReleaseUpdater("0.4.4", system="Windows", machine="x86_64")
        with pytest.raises(ValueError):
            updater.download(url, tmp_path, max_bytes=100 * 1024)
        assert not (tmp_path / "download.part").exists()
    finally:
        stop()


def test_cancelling_a_download_cleans_up_the_partial_file(tmp_path):
    payload = b"z" * (500 * 1024)
    url, stop = _serve_bytes(payload)
    try:
        updater = DesktopReleaseUpdater("0.4.4", system="Windows", machine="x86_64")
        cancel = threading.Event()
        cancel.set()  # cancelled before the first chunk is even read
        with pytest.raises(InterruptedError):
            updater.download(url, tmp_path, cancel_event=cancel)
        assert not (tmp_path / "download.part").exists()
    finally:
        stop()

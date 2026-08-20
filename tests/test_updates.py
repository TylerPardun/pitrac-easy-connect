"""Version comparison and update checking.

An updater that gets version comparison wrong tells people to upgrade forever,
and one that blocks startup stops them playing golf. Both are tested here.
"""

import subprocess
import time

import pytest

from pitrac_easy_connect.common.updates import (
    DEVELOPMENT,
    PACKAGED,
    SOURCE,
    UNKNOWN,
    Updater,
)
from pitrac_easy_connect.common.versions import compare, is_newer, parse


# --- Version comparison ---------------------------------------------------


@pytest.mark.parametrize(
    "candidate,current,expected",
    [
        ("0.10.0", "0.9.0", True),      # the classic string-compare trap
        ("0.9.0", "0.10.0", False),
        ("1.0.0", "0.2.0", True),
        ("v1.0.0", "0.2.0", True),      # a tag with a v prefix
        ("0.2.0", "0.2.0", False),      # same version is not an update
        ("0.2.1", "0.2.0", True),
        ("2.0", "1.9.9", True),         # a two-part version
        ("1.0.0", "1.0.0-rc1", True),   # a release beats its own pre-release
        ("1.0.0-rc1", "1.0.0", False),
        ("1.0.0-rc2", "1.0.0-rc1", True),
    ],
)
def test_version_ordering(candidate, current, expected):
    assert is_newer(candidate, current) is expected


@pytest.mark.parametrize("bad", ["", "garbage", "latest", None, "v", "..", "1.2.3.4.5-"])
def test_an_unreadable_version_is_never_offered_as_an_update(bad):
    """Refusing to guess is safer than offering a bogus update."""

    assert is_newer(bad, "0.2.0") is False
    assert is_newer("0.3.0", bad) is False


def test_parse_keeps_the_pre_release_label():
    assert parse("v1.2.3-beta.4") == (1, 2, 3, "beta.4")
    assert parse("1.2.3") == (1, 2, 3, "")


def test_compare_reports_unknown_rather_than_guessing():
    assert compare("garbage", "1.0.0") is None
    assert compare("1.0.0", "1.0.0") == 0


# --- Which kind of install is this ---------------------------------------


def git_repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    (root / "file.txt").write_text("one\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=root, check=True)
    return root


def test_a_directory_with_no_repository_counts_as_packaged(tmp_path):
    assert Updater("0.2.0", root=tmp_path).kind() == PACKAGED


def test_a_working_copy_with_local_changes_is_left_alone(tmp_path):
    root = git_repo(tmp_path)
    (root / "file.txt").write_text("changed while working\n")
    updater = Updater("0.2.0", root=root)
    assert updater.kind() == DEVELOPMENT

    status = updater.check()
    assert status.available is False
    assert "development copy" in status.detail
    assert status.can_apply is False


def test_a_development_copy_is_never_pulled_over(tmp_path):
    root = git_repo(tmp_path)
    (root / "file.txt").write_text("work in progress\n")
    result = Updater("0.2.0", root=root).apply()
    assert result["applied"] is False
    assert (root / "file.txt").read_text() == "work in progress\n", "local work was destroyed"


# --- Checking a packaged build against published releases -----------------


def fake_release(tag, url="https://example.invalid/releases/tag"):
    return lambda _url: {"tag_name": tag, "html_url": url}


def test_a_newer_release_is_offered(tmp_path):
    updater = Updater("0.2.0", root=tmp_path, fetch=fake_release("v0.3.0"))
    status = updater.check()
    assert status.kind == PACKAGED
    assert status.available is True
    assert status.latest == "v0.3.0"
    assert "0.3.0" in status.detail
    assert status.download_url


def test_the_same_release_is_not_offered(tmp_path):
    status = Updater("0.2.0", root=tmp_path, fetch=fake_release("v0.2.0")).check()
    assert status.available is False
    assert status.detail == "Up to date."


def test_an_older_release_is_not_offered(tmp_path):
    status = Updater("0.9.0", root=tmp_path, fetch=fake_release("v0.3.0")).check()
    assert status.available is False


def test_a_packaged_build_does_not_claim_it_can_update_itself(tmp_path):
    updater = Updater("0.2.0", root=tmp_path, fetch=fake_release("v0.3.0"))
    assert updater.check().can_apply is False
    result = updater.apply()
    assert result["applied"] is False
    assert result["downloadUrl"]


# --- Failure must never get in the way ------------------------------------


def test_a_network_failure_is_reported_quietly_not_raised(tmp_path):
    def explode(_url):
        raise OSError("no network")

    status = Updater("0.2.0", root=tmp_path, fetch=explode).check()
    assert status.available is False
    assert "Could not check" in status.detail


def test_a_nonsense_response_does_not_produce_an_update(tmp_path):
    for payload in ({}, {"tag_name": ""}, {"tag_name": "not-a-version"}, {"other": 1}):
        status = Updater("0.2.0", root=tmp_path, fetch=lambda _u, p=payload: p).check()
        assert status.available is False, payload


def test_checking_in_the_background_never_raises(tmp_path):
    def explode(_url):
        raise RuntimeError("boom")

    seen = []
    updater = Updater("0.2.0", root=tmp_path, fetch=explode)
    updater.check_in_background(done=seen.append)
    time.sleep(0.4)
    # Whether or not the callback ran, nothing propagated and nothing hung.
    assert all(item.available is False for item in seen)


def test_a_callback_that_raises_does_not_take_the_thread_down(tmp_path):
    def bad_callback(_status):
        raise ValueError("callback is broken")

    updater = Updater("0.2.0", root=tmp_path, fetch=fake_release("v9.9.9"))
    updater.check_in_background(done=bad_callback)
    time.sleep(0.4)


# --- Not hammering the API ------------------------------------------------


def test_the_result_is_reused_rather_than_asking_again(tmp_path):
    calls = []

    def counting(_url):
        calls.append(1)
        return {"tag_name": "v0.3.0"}

    updater = Updater("0.2.0", root=tmp_path, fetch=counting)
    for _ in range(5):
        updater.check()
    assert len(calls) == 1, "checked {} times instead of caching".format(len(calls))


def test_forcing_a_check_asks_again(tmp_path):
    calls = []

    def counting(_url):
        calls.append(1)
        return {"tag_name": "v0.3.0"}

    updater = Updater("0.2.0", root=tmp_path, fetch=counting)
    updater.check()
    updater.check(force=True)
    assert len(calls) == 2


# --- What the app shows ---------------------------------------------------


def test_the_companion_reports_update_state_without_being_asked(tmp_path):
    from pitrac_easy_connect.companion.service import CompanionService

    service = CompanionService(config_path=tmp_path / "c.json", computer_name="PC")
    service.updates = Updater("0.2.0", root=tmp_path, fetch=fake_release("v0.4.0"))
    try:
        update = service.status()["update"]
        assert update["available"] is True
        assert update["latest"] == "v0.4.0"
        assert update["installed"] == "0.2.0"
    finally:
        service.close()


def test_a_failed_check_still_produces_a_usable_status(tmp_path):
    from pitrac_easy_connect.companion.service import CompanionService

    def explode(_url):
        raise OSError("offline")

    service = CompanionService(config_path=tmp_path / "c.json", computer_name="PC")
    service.updates = Updater("0.2.0", root=tmp_path, fetch=explode)
    try:
        status = service.status()
        assert status["update"]["available"] is False
        assert status["state"], "the rest of the status must still be there"
    finally:
        service.close()


def test_mismatched_versions_between_the_two_halves_are_flagged(tmp_path):
    from pitrac_easy_connect.companion.service import CompanionService

    service = CompanionService(config_path=tmp_path / "c.json", computer_name="PC")
    service.updates = Updater("0.2.0", root=tmp_path, fetch=fake_release("v0.2.0"))
    try:
        service._pi_status = {"version": "0.1.0"}
        assert service.status()["update"]["versionsMatch"] is False
        service._pi_status = {"version": service.version}
        assert service.status()["update"]["versionsMatch"] is True
    finally:
        service.close()

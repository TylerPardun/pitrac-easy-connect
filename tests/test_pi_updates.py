"""Updating the enclosure from a published release.

The Pi is installed by copying a directory into /usr/lib, so it has no git
checkout to pull. It fetches the release archive instead, and the part that has
to be right is the swap: a half-written application directory on a machine with
no keyboard and no screen is not a bug report, it is a brick.

Nothing here talks to GitHub. A local stand-in serves a release, which is also
the only way to test what happens when the download is wrong.
"""

import hashlib
import json
import os
import threading

from conftest import start_serving
import zipapp
import http.server
import pathlib
import shutil

import pytest

from pitrac_easy_connect.common.updates import ArchiveUpdater


def build_archive(tmp_path, version="9.9.9", broken=False, empty=False):
    """A real zipapp of the real package, with the version bumped."""

    staging = tmp_path / "src-{}".format(version)
    shutil.rmtree(staging, ignore_errors=True)
    source = pathlib.Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
    shutil.copytree(source, staging / "pitrac_easy_connect",
                    ignore=shutil.ignore_patterns("__pycache__"))
    if empty:
        # Keep it past the minimum size, so this exercises the content check
        # rather than being caught earlier by the size one.
        shutil.rmtree(staging / "pitrac_easy_connect")
        (staging / "something_else").mkdir()
        (staging / "something_else" / "x.py").write_text("# filler\n" * 20000)
    else:
        # Rewrite whatever version the source currently carries, rather than a
        # hardcoded one that goes stale the moment the project is released.
        import re as _re

        init = staging / "pitrac_easy_connect" / "__init__.py"
        init.write_text(_re.sub(r'__version__ = "[^"]+"',
                                '__version__ = "{}"'.format(version),
                                init.read_text()))
    (staging / "__main__.py").write_text("pass\n")
    out = tmp_path / "release-{}.pyz".format(version)
    zipapp.create_archive(staging, out)
    blob = out.read_bytes()
    return blob[: len(blob) // 2] if broken else blob


@pytest.fixture
def upstream(tmp_path):
    """A stand-in for the release API and its download."""

    state = {"tag": "9.9.9", "blob": build_archive(tmp_path), "asset": True}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("/releases/latest"):
                # The real API states a sha256 for every asset, and the
                # enclosure refuses an archive that does not match it, so a
                # stand-in without one is not a useful stand-in.
                digest = state.get("digest")
                if digest is None:
                    digest = "sha256:" + hashlib.sha256(state["blob"]).hexdigest()
                assets = ([{"name": "PiTrac-Easy-Connect.pyz",
                            "browser_download_url": base[0] + "/download",
                            "digest": digest}]
                          if state["asset"] else [])
                body = json.dumps({"tag_name": state["tag"], "assets": assets,
                                   "html_url": "http://example.invalid"}).encode()
            elif self.path == "/download":
                body = state["blob"]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    base = ["http://127.0.0.1:{}".format(server.server_port)]
    stop = start_serving(server)
    yield base[0], state
    stop()


@pytest.fixture
def installed(tmp_path):
    """An enclosure that already has a copy installed."""

    app_dir = tmp_path / "usr-lib"
    package = app_dir / "pitrac_easy_connect"
    (package / "pi").mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.2.0"\n')
    (package / "pi" / "service.py").write_text("# the running version\n")
    return app_dir


def updater(installed, upstream, **kwargs):
    base, _state = upstream
    restarted = kwargs.pop("restarted", None)
    return ArchiveUpdater(
        installed="0.2.0", app_dir=installed, repository="owner/repo",
        api_base=base, restart=restarted, **kwargs)


# --- Checking --------------------------------------------------------------


def test_a_newer_release_can_be_installed(installed, upstream):
    status = updater(installed, upstream).check()
    assert status.available is True
    assert status.can_apply is True
    assert status.latest == "9.9.9"


def test_the_same_version_is_up_to_date(installed, upstream):
    _base, state = upstream
    state["tag"] = "0.2.0"
    status = updater(installed, upstream).check()
    assert status.available is False


def test_a_release_with_nothing_to_install_says_so(installed, upstream):
    _base, state = upstream
    state["asset"] = False
    status = updater(installed, upstream).check()
    assert status.available is True
    assert status.can_apply is False


def test_an_unreachable_service_does_not_raise(installed):
    status = ArchiveUpdater("0.2.0", installed, "owner/repo",
                            api_base="http://127.0.0.1:1").check()
    assert status.available is False
    assert "could not" in status.detail.lower()


# --- Applying --------------------------------------------------------------


def test_applying_replaces_the_installed_copy(installed, upstream):
    restarts = []
    result = updater(installed, upstream, restarted=lambda: restarts.append(1)).apply()

    assert result["applied"] is True, result
    assert result["version"] == "9.9.9"
    text = (installed / "pitrac_easy_connect" / "__init__.py").read_text()
    assert '"9.9.9"' in text, "the new version should be in place"
    assert restarts == [1], "the service has to restart to run the new code"


def test_nothing_is_left_behind_after_a_successful_update(installed, upstream):
    updater(installed, upstream).apply()
    leftovers = [p.name for p in installed.iterdir()]
    assert leftovers == ["pitrac_easy_connect"], leftovers


# --- Everything that can go wrong -----------------------------------------


def test_a_truncated_download_leaves_the_running_version_alone(installed, upstream, tmp_path):
    _base, state = upstream
    state["blob"] = build_archive(tmp_path, broken=True)

    result = updater(installed, upstream).apply()
    assert result["applied"] is False
    assert (installed / "pitrac_easy_connect" / "pi" / "service.py").exists()
    assert '"0.2.0"' in (installed / "pitrac_easy_connect" / "__init__.py").read_text()


def test_an_archive_that_is_not_the_app_is_refused(installed, upstream, tmp_path):
    _base, state = upstream
    state["blob"] = build_archive(tmp_path, empty=True)

    result = updater(installed, upstream).apply()
    assert result["applied"] is False
    assert "does not contain" in result["detail"] or "missing" in result["detail"]
    assert '"0.2.0"' in (installed / "pitrac_easy_connect" / "__init__.py").read_text()


def test_a_download_that_is_far_too_small_is_refused(installed, upstream):
    _base, state = upstream
    state["blob"] = b"nope"
    result = updater(installed, upstream).apply()
    assert result["applied"] is False
    assert "size" in result["detail"].lower()


def test_a_failed_update_does_not_restart_the_service(installed, upstream):
    _base, state = upstream
    state["blob"] = b"nope"
    restarts = []
    updater(installed, upstream, restarted=lambda: restarts.append(1)).apply()
    assert restarts == [], "restarting into a failed update is how a Pi bricks"


def test_a_restart_that_fails_puts_the_old_version_back(installed, upstream):
    """New files that cannot be started are worse than no update at all: the
    enclosure has no keyboard and nobody can reach it to undo them."""

    def explode():
        raise RuntimeError("systemctl said no")

    result = updater(installed, upstream, restarted=explode).apply()
    assert result["applied"] is False
    assert "undone" in result["detail"]
    assert '"0.2.0"' in (installed / "pitrac_easy_connect" / "__init__.py").read_text()


def test_a_version_that_starts_but_is_unhealthy_is_rolled_back(installed, upstream):
    """It restarted and then did not answer. That is a broken enclosure, and
    the only safe move is backwards."""

    restarts = []
    up = updater(installed, upstream, restarted=lambda: restarts.append(1))
    up._healthy = lambda: False

    result = up.apply()
    assert result["applied"] is False
    assert result.get("rolledBack") is True
    assert '"0.2.0"' in (installed / "pitrac_easy_connect" / "__init__.py").read_text()
    assert len(restarts) == 2, "restarted into the new version, then back into the old"


def test_a_healthy_update_keeps_the_new_version_and_tidies_up(installed, upstream):
    up = updater(installed, upstream, restarted=lambda: None)
    up._healthy = lambda: True

    result = up.apply()
    assert result["applied"] is True
    assert '"9.9.9"' in (installed / "pitrac_easy_connect" / "__init__.py").read_text()
    assert [p.name for p in installed.iterdir()] == ["pitrac_easy_connect"], \
        "the previous copy should be gone once the new one has proved itself"


def test_an_archive_cannot_write_outside_its_own_directory(installed, upstream, tmp_path):
    """A zip that escapes its extraction directory would let a release
    overwrite anything the service can reach."""

    import zipfile

    nasty = tmp_path / "nasty.pyz"
    with zipfile.ZipFile(nasty, "w") as z:
        z.writestr("pitrac_easy_connect/__init__.py", "x")
        z.writestr("../../../../tmp/escaped.py", "pwned")
    _base, state = upstream
    state["blob"] = nasty.read_bytes() * 40   # past the minimum size check

    result = updater(installed, upstream).apply()
    assert result["applied"] is False


def test_a_version_that_will_not_run_is_rejected_before_anything_is_swapped(installed, upstream):
    """Restarting the service kills the process doing the update, so a check
    made afterwards can never act on the answer. The check has to come first."""

    swapped = []
    up = updater(installed, upstream, restarted=lambda: swapped.append("restart"))
    up._verify = lambda staged: False

    result = up.apply()
    assert result["applied"] is False
    assert "would not start" in result["detail"]
    assert swapped == [], "nothing should have been restarted"
    assert '"0.2.0"' in (installed / "pitrac_easy_connect" / "__init__.py").read_text()
    assert [p.name for p in installed.iterdir()] == ["pitrac_easy_connect"]


def test_a_version_that_runs_is_installed(installed, upstream):
    up = updater(installed, upstream, restarted=lambda: None)
    up._verify = lambda staged: True
    assert up.apply()["applied"] is True
    assert '"9.9.9"' in (installed / "pitrac_easy_connect" / "__init__.py").read_text()


def test_the_real_verifier_rejects_a_broken_package(tmp_path):
    """The check that ships, against a package that cannot import."""

    from pitrac_easy_connect.pi.service import _can_run

    broken = tmp_path / "staged" / "pitrac_easy_connect"
    broken.mkdir(parents=True)
    (broken / "__init__.py").write_text("import a_module_that_does_not_exist\n")
    assert _can_run(broken) is False


def test_the_real_verifier_accepts_the_package_that_is_running(tmp_path):
    import pathlib as _p

    from pitrac_easy_connect.pi.service import _can_run

    here = _p.Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
    assert _can_run(here) is True


# --- The versioned-release layout the installer creates --------------------
#
# This layout exists only on the Raspberry Pi. Windows has no
# /usr/lib/pitrac-easy-connect, creating a symlink there needs elevation, and
# replacing one is not the same atomic operation, so these say nothing useful
# on Windows and fail for reasons that have nothing to do with the code.

on_posix = pytest.mark.skipif(
    os.name != "posix",
    reason="the enclosure's release layout is POSIX-only; it never runs on Windows",
)


@pytest.fixture
def released(tmp_path):
    """An enclosure installed the way install.sh installs it."""

    root = tmp_path / "usr-lib"
    releases = root / "releases"
    current = releases / "0.2.0-1000"
    package = current / "pitrac_easy_connect"
    (package / "pi").mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.2.0"\n')
    (package / "pi" / "service.py").write_text("# the running version\n")

    link = root / "pitrac-easy-connect"
    link.symlink_to(current)
    return root, link, releases, current


def release_updater(released, upstream, **kwargs):
    root, link, releases, current = released
    base, _state = upstream
    return ArchiveUpdater(
        installed="0.2.0", app_dir=current, repository="owner/repo",
        api_base=base, link_path=link, releases_dir=releases, **kwargs)


@on_posix
def test_an_update_becomes_a_new_release_and_moves_the_link(released, upstream):
    """The running release is never modified, so there is no moment where the
    application directory is missing."""

    _root, link, releases, current = released
    up = release_updater(released, upstream, restart=lambda: None)
    up._verify = lambda staged: True

    assert up.apply()["applied"] is True

    assert link.resolve() != current, "the link should point at a new release"
    assert '"9.9.9"' in (link.resolve() / "pitrac_easy_connect" / "__init__.py").read_text()
    assert current.exists(), "the previous release must stay, to go back to"
    assert len(list(releases.iterdir())) == 2


@on_posix
def test_a_release_that_will_not_start_leaves_the_link_alone(released, upstream):
    _root, link, _releases, current = released
    up = release_updater(released, upstream, restart=lambda: None)
    up._verify = lambda staged: False

    assert up.apply()["applied"] is False
    assert link.resolve() == current
    assert '"0.2.0"' in (link.resolve() / "pitrac_easy_connect" / "__init__.py").read_text()


@on_posix
def test_a_release_that_starts_but_is_unhealthy_points_the_link_back(released, upstream):
    _root, link, _releases, current = released
    up = release_updater(released, upstream, restart=lambda: None)
    up._verify = lambda staged: True
    up._healthy = lambda: False

    result = up.apply()
    assert result["applied"] is False and result.get("rolledBack") is True
    assert link.resolve() == current, "the link must be back on the working release"
    assert '"0.2.0"' in (link.resolve() / "pitrac_easy_connect" / "__init__.py").read_text()


@on_posix
def test_the_running_release_is_never_written_to(released, upstream):
    """Modifying the directory being executed from is what the symlink layout
    exists to avoid."""

    _root, link, _releases, current = released
    before = (current / "pitrac_easy_connect" / "__init__.py").read_text()

    up = release_updater(released, upstream, restart=lambda: None)
    up._verify = lambda staged: True
    up.apply()

    assert (current / "pitrac_easy_connect" / "__init__.py").read_text() == before


# --- Running the check as somebody other than root -------------------------
#
# The enclosure runs as root and drops to "nobody" to try the downloaded code
# before trusting it. Every test here runs as an ordinary user, where that drop
# does not happen, so the parts that only bite as root are asserted directly.


@on_posix
def test_the_staged_tree_can_be_read_by_the_account_that_checks_it(tmp_path):
    """mkdtemp is 0700; the probe runs as nobody and must get in.

    With the directory left at 0700 the probe cannot traverse to the package
    at all, so every valid update is rejected -- on a real enclosure only.
    """

    import os
    import stat

    from pitrac_easy_connect.common.updates import ArchiveUpdater

    updater = ArchiveUpdater(installed="1.0.0", app_dir=tmp_path / "install")
    package = updater._unpack(build_archive(tmp_path, "2.0.0"))

    staging = package.parent.parent
    walked = 0
    for path in [staging] + [
        pathlib.Path(parent) / name
        for parent, directories, files in os.walk(staging)
        for name in list(directories) + list(files)
    ]:
        mode = stat.S_IMODE(path.stat().st_mode)
        walked += 1
        if path.is_dir():
            assert mode & stat.S_IROTH, "{} cannot be listed by the prober".format(path)
            assert mode & stat.S_IXOTH, "{} cannot be entered by the prober".format(path)
        else:
            assert mode & stat.S_IROTH, "{} cannot be read by the prober".format(path)
        # Readable, never writable: the prober must not be able to edit the
        # code that is about to be installed as root.
        assert not mode & stat.S_IWOTH, "{} is writable by the prober".format(path)
    assert walked > 3, "the staged tree was not actually walked"


def test_the_check_drops_privileges_without_running_python_after_the_fork(monkeypatch):
    """preexec_fn is not safe in a process with threads, and this one has them."""

    from pitrac_easy_connect.pi import service as service_module

    monkeypatch.setattr(service_module.os, "geteuid", lambda: 0, raising=False)

    class FakePasswd:
        pw_uid, pw_gid = 65534, 65534

    import pwd

    monkeypatch.setattr(pwd, "getpwnam", lambda name: FakePasswd)

    lowered = service_module._unprivileged()
    assert lowered == {"user": 65534, "group": 65534, "extra_groups": []}
    assert "preexec_fn" not in lowered


def test_an_ordinary_user_runs_the_check_as_itself(monkeypatch):
    from pitrac_easy_connect.pi import service as service_module

    monkeypatch.setattr(service_module.os, "geteuid", lambda: 1000, raising=False)
    assert service_module._unprivileged() == {}


def test_the_check_stays_as_root_rather_than_failing_when_nobody_is_missing(monkeypatch):
    """A machine without a nobody account still has to be able to update."""

    from pitrac_easy_connect.pi import service as service_module

    monkeypatch.setattr(service_module.os, "geteuid", lambda: 0, raising=False)

    import pwd

    def no_such_user(name):
        raise KeyError(name)

    monkeypatch.setattr(pwd, "getpwnam", no_such_user)
    assert service_module._unprivileged() == {}


# --- Checking the download against what the release says it is -------------


def _release_with(tmp_path, blob, digest=None):
    release = {
        "tag_name": "v9.9.9",
        "assets": [{
            "name": "PiTrac-Easy-Connect-9.9.9.pyz",
            "browser_download_url": "https://example.invalid/a.pyz",
        }],
    }
    if digest is not None:
        release["assets"][0]["digest"] = digest
    return release


def _updater(tmp_path, release, blob):
    from pitrac_easy_connect.common.updates import ArchiveUpdater

    updater = ArchiveUpdater(
        installed="1.0.0",
        app_dir=tmp_path / "app",
        fetch=lambda url: blob,
    )
    updater._release = lambda: release
    return updater


def test_an_archive_that_does_not_match_its_published_checksum_is_refused(tmp_path):
    """The listing and the bytes come from different hosts."""

    import hashlib

    blob = build_archive(tmp_path, "9.9.9")
    wrong = hashlib.sha256(b"something else entirely").hexdigest()
    updater = _updater(tmp_path, _release_with(tmp_path, blob, "sha256:" + wrong), blob)

    result = updater.apply()

    assert result["applied"] is False
    assert "checksum" in result["detail"]
    assert not (tmp_path / "app").exists(), "nothing may be staged from a bad download"


def test_an_archive_that_matches_its_checksum_is_installed(tmp_path):
    import hashlib

    blob = build_archive(tmp_path, "9.9.9")
    right = hashlib.sha256(blob).hexdigest()
    (tmp_path / "app").mkdir(parents=True)
    updater = _updater(tmp_path, _release_with(tmp_path, blob, "sha256:" + right), blob)

    assert updater.apply()["applied"] is True


def test_a_release_with_no_checksum_at_all_is_refused(tmp_path):
    blob = build_archive(tmp_path, "9.9.9")
    updater = _updater(tmp_path, _release_with(tmp_path, blob, None), blob)

    result = updater.apply()

    assert result["applied"] is False
    assert "no checksum" in result["detail"]


def test_the_digest_is_read_from_a_real_release_listing():
    """Exactly the shape api.github.com returns."""

    from pitrac_easy_connect.common.updates import ArchiveUpdater

    release = {
        "assets": [
            {"name": "PiTrac-Easy-Connect-macos.zip",
             "digest": "sha256:28e185448113a1d90036f4b8797ade7b2c6e5f2a1854c37139cf8ff978f4cd8c"},
            {"name": "PiTrac-Easy-Connect-0.3.0.pyz",
             "digest": "sha256:865aa95c7052df8b7c498334b4f6b14a58cf0e8b15b6d5695863720851fedf15"},
        ]
    }
    assert ArchiveUpdater._archive_digest(release) == (
        "865aa95c7052df8b7c498334b4f6b14a58cf0e8b15b6d5695863720851fedf15"
    )


# --- Releases must not pile up, and must not collide -----------------------


def _bare_updater(released):
    """An updater over the installed layout, with no release server involved."""

    _root, link, releases, current = released
    return ArchiveUpdater(installed="0.2.0", app_dir=current,
                          link_path=link, releases_dir=releases)


@on_posix
def test_two_updates_in_one_second_do_not_delete_each_other(released):
    """The running copy is one of the directories a collision would remove."""

    updater = _bare_updater(released)
    first = updater._new_release_dir("2.0.0")
    second = updater._new_release_dir("2.0.0")

    assert first != second, "a second update would have deleted the first"
    assert first.exists() and second.exists()


@on_posix
def test_updating_over_the_air_keeps_the_current_and_previous_releases(released):
    """Installing by hand keeps two; updating kept every release ever made."""

    import os
    import time as _time

    updater = _bare_updater(released)
    releases_dir = updater.releases_dir

    made = []
    for index in range(5):
        path = updater._new_release_dir("1.{}.0".format(index))
        (path / "pitrac_easy_connect").mkdir()
        # Distinct mtimes, so "newest" is not down to filesystem resolution.
        os.utime(path, (_time.time() + index, _time.time() + index))
        made.append(path)

    # The symlink points at the newest, as it would after an update.
    link = updater.link_path
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(made[-1])

    updater._prune_releases()

    left = sorted(path for path in releases_dir.iterdir() if path.is_dir())
    assert len(left) == 2, "expected the current and previous only, got {}".format(left)
    assert made[-1] in left, "the running release was removed"
    assert made[-2] in left, "the release to go back to was removed"


@on_posix
def test_pruning_never_removes_the_release_that_is_running(released):
    """Even when it is the oldest directory there."""

    import os
    import time as _time

    updater = _bare_updater(released)
    oldest = updater._new_release_dir("0.1.0")
    os.utime(oldest, (1, 1))
    for index in range(3):
        newer = updater._new_release_dir("9.{}.0".format(index))
        os.utime(newer, (_time.time() + index, _time.time() + index))

    link = updater.link_path
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(oldest)

    updater._prune_releases()

    assert oldest.exists(), "the running release was deleted as stale"

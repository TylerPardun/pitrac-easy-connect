"""Updating the enclosure from a published release.

The Pi is installed by copying a directory into /usr/lib, so it has no git
checkout to pull. It fetches the release archive instead, and the part that has
to be right is the swap: a half-written application directory on a machine with
no keyboard and no screen is not a bug report, it is a brick.

Nothing here talks to GitHub. A local stand-in serves a release, which is also
the only way to test what happens when the download is wrong.
"""

import json
import threading
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
                assets = ([{"name": "PiTrac-Easy-Connect.pyz",
                            "browser_download_url": base[0] + "/download"}]
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield base[0], state
    server.shutdown()
    server.server_close()


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


def test_the_service_still_runs_if_the_restart_itself_fails(installed, upstream):
    def explode():
        raise RuntimeError("systemctl said no")

    result = updater(installed, upstream, restarted=explode).apply()
    assert result["applied"] is True, "the files are in place; the restart is separate"


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

"""Obtaining the models is the owner's decision, taken by them, on their machine.

These tests never touch PiTracLM's real files. A local server stands in for
their repository, which is also the only way to test the failure paths.
"""

import http.server
import threading

from conftest import start_serving

import pytest

from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.pi import ml_models
from test_pi_service import service  # noqa: F401  (fixture)

WEIGHTS = b"ncnn-weights" * 200
PARAMS = b"7767517\n" + b"layer-definitions\n" * 100


class FakeUpstream(http.server.BaseHTTPRequestHandler):
    """Stands in for PiTracLM's repository."""

    behaviour = "ok"
    served = []

    def do_GET(self):
        FakeUpstream.served.append(self.path)
        if FakeUpstream.behaviour == "missing":
            self.send_error(404)
            return
        if FakeUpstream.behaviour == "truncated":
            body = b"nope"
        elif self.path.endswith(".param"):
            body = PARAMS
        else:
            body = WEIGHTS
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def upstream():
    FakeUpstream.behaviour = "ok"
    FakeUpstream.served = []
    server = http.server.HTTPServer(("127.0.0.1", 0), FakeUpstream)
    stop = start_serving(server)
    yield "http://127.0.0.1:{}".format(server.server_port)
    stop()


# --- The happy path --------------------------------------------------------


def test_installing_puts_both_models_where_pitrac_looks(tmp_path, upstream):
    target = tmp_path / "models"
    result = ml_models.install_from_source(installed_dir=target, source_base=upstream)

    assert result["installed"]
    for name in ml_models.MODEL_NAMES:
        for filename in ml_models.MODEL_FILES:
            assert (target / name / filename).exists()
    assert ml_models.installed_files(target) == {
        "yolo26-ball-detector": 2,
        "spin-predictor": 2,
    }


def test_it_fetches_only_the_four_files(tmp_path, upstream):
    """Anything else would be pulling more of their repository than we need."""

    ml_models.install_from_source(installed_dir=tmp_path / "m", source_base=upstream)
    assert len(FakeUpstream.served) == 4
    for path in FakeUpstream.served:
        assert path.endswith(("best.ncnn.param", "best.ncnn.bin"))


def test_what_was_installed_is_recorded(tmp_path, upstream):
    """Upstream publishes no checksums, so record what actually arrived."""

    result = ml_models.install_from_source(installed_dir=tmp_path / "m", source_base=upstream)
    assert len(result["files"]) == 4
    for digest in result["files"].values():
        assert len(digest) == 64


# --- Failure leaves the machine as it was ---------------------------------


def test_a_failed_download_does_not_disturb_what_is_there(tmp_path, upstream):
    """Half a model is worse than none: PiTrac would load it and misbehave."""

    target = tmp_path / "models"
    ml_models.install_from_source(installed_dir=target, source_base=upstream)
    before = {
        path.name: path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }

    FakeUpstream.behaviour = "missing"
    with pytest.raises(Exception):
        ml_models.install_from_source(installed_dir=target, source_base=upstream)

    after = {
        path.name: path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }
    assert after == before, "the previous models should survive a failed attempt"


def test_a_truncated_file_is_refused(tmp_path, upstream):
    """A proxy error page is a 200 with a body, and would install happily."""

    FakeUpstream.behaviour = "truncated"
    with pytest.raises(ValueError):
        ml_models.install_from_source(
            installed_dir=tmp_path / "models", source_base=upstream
        )
    assert not (tmp_path / "models" / "spin-predictor").exists()


def test_nothing_is_left_behind_when_it_fails(tmp_path, upstream):
    import pathlib
    import tempfile

    FakeUpstream.behaviour = "missing"
    before = set(pathlib.Path(tempfile.gettempdir()).glob("pitrac-models-*"))
    with pytest.raises(Exception):
        ml_models.install_from_source(
            installed_dir=tmp_path / "models", source_base=upstream
        )
    after = set(pathlib.Path(tempfile.gettempdir()).glob("pitrac-models-*"))
    assert after == before, "the staging directory should be cleaned up"


# --- Consent ---------------------------------------------------------------


def test_the_enclosure_refuses_to_install_without_acceptance(service):
    """The licence is granted to whoever accepts it. If we could accept on the
    owner's behalf, the machine's builder would be the licensee, which is the
    one thing this whole arrangement exists to avoid."""

    with pytest.raises(EasyConnectError) as caught:
        service.command("installModels", {"accepted": False})
    assert caught.value.info.code == "PT-PI-012"

    with pytest.raises(EasyConnectError) as caught:
        service.command("installModels", {})
    assert caught.value.info.code == "PT-PI-012"


def test_the_licence_is_read_from_pitraclm_rather_than_bundled():
    """Somebody should agree to the current text, not a copy that went stale."""

    source = (
        __import__("pathlib").Path(ml_models.__file__).read_text()
    )
    assert "raw.githubusercontent.com/PiTracLM/PiTrac" in source
    assert ml_models.LICENCE_URL.endswith("LICENSE.MODEL.md")


def test_the_models_are_only_ever_fetched_from_pitraclm():
    """Serving a copy from anywhere of ours is redistribution, which their
    licence forbids outright."""

    assert ml_models.SOURCE_BASE.startswith(
        "https://raw.githubusercontent.com/PiTracLM/PiTrac/"
    )


def test_a_failure_partway_leaves_both_models_as_they_were(tmp_path, upstream):
    """Deleting each model before moving its replacement meant a failure on
    the second left the first replaced and the second missing -- exactly what
    the module promises does not happen."""

    import shutil as _shutil

    target = tmp_path / "models"
    ml_models.install_from_source(installed_dir=target, source_base=upstream)
    before = {
        str(p.relative_to(target)): p.read_bytes()
        for p in sorted(target.rglob("*")) if p.is_file()
    }

    # Fail on the second move, after the first has already been replaced.
    calls = {"n": 0}
    real_move = _shutil.move

    def fail_second(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("the card filled up")
        return real_move(src, dst)

    _shutil.move = fail_second
    try:
        with pytest.raises(Exception):
            ml_models.install_from_source(installed_dir=target, source_base=upstream)
    finally:
        _shutil.move = real_move

    after = {
        str(p.relative_to(target)): p.read_bytes()
        for p in sorted(target.rglob("*")) if p.is_file()
    }
    assert after == before, "both models should be exactly as they were"

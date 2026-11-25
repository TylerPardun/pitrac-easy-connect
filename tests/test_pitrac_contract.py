"""Easy-Connect against PiTrac's real web server.

Everything else in the suite uses a stand-in for PiTrac, which can only ever be
as right as the last time somebody looked. PiTrac moved its simulators and
calibration into a database two days after a release of this, and the stand-in
went on agreeing with code that no longer worked. This is the test that would
have noticed.

It needs a PiTrac checkout and an interpreter with PiTrac's own requirements,
and is skipped without them. ``packaging/check.sh`` provides both:

    ./packaging/check.sh                the revision this release was tested with
    ./packaging/check.sh --pitrac main  whatever PiTrac is today
"""

import copy
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from pitrac_easy_connect.common.configstore import ConfigStore
from pitrac_easy_connect.common.identity import IdentityStore
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.backup import BackupManager
from pitrac_easy_connect.pi.pairing import PairingManager
from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.pitrac_api import PitracApi, PitracRefused, PitracUnsupported
from pitrac_easy_connect.pi.relay import ShotRelay
from pitrac_easy_connect.pi.simulated import SimulatedPitracApi

SOURCE = os.environ.get("PITRAC_SOURCE", "")
PYTHON = os.environ.get("PITRAC_PYTHON", "")

pytestmark = pytest.mark.skipif(
    not (SOURCE and PYTHON), reason="needs PITRAC_SOURCE and PITRAC_PYTHON"
)

#: The shape PiTrac's calibration wizard saves, down to the value types.
CALIBRATION = {"gs_config": {"cameras": {
    "kCamera1CalibrationMatrix": [["1833.5", "0.0", "697.2"], ["0.0", "1832.1", "513.7"], ["0.0", "0.0", "1.0"]],
    "kCamera1DistortionVector": ["-0.5", "0.29", "0.0012", "0.0004", "-0.18"],
    "kCamera1FocalLength": "6.1",
    "kCamera1Angles": ["1.2", "-3.4"],
    "kCamera2CalibrationMatrix": [["2340.2", "0.0", "698.4"], ["0.0", "2338.6", "462.7"], ["0.0", "0.0", "1.0"]],
    "kCamera2DistortionVector": ["-0.81", "4.4", "-0.0018", "0.0015", "-38.1"],
    "kCamera2FocalLength": "6.2",
    "kCamera2Angles": ["0.8", "2.2"],
}}}


def wait_for(condition, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = condition()
        if found:
            return found
        time.sleep(0.1)
    return condition()


class RealPitrac:
    def __init__(self, home: Path):
        self.home = home
        self.port = None
        self.process = None
        self.start()

    def start(self):
        if self.port is None:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                self.port = probe.getsockname()[1]
        self.url = "http://127.0.0.1:{}".format(self.port)
        self.log = open(self.home / "pitrac.log", "ab")
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("PITRAC_")
        }
        environment.update(HOME=str(self.home), PITRAC_WEB_PORT=str(self.port),
                           PYTHONDONTWRITEBYTECODE="1")
        self.process = subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"],
            cwd=str(Path(SOURCE).expanduser() / "Software" / "web-server"),
            env=environment, stdout=self.log, stderr=self.log,
        )

        def answering():
            if self.process.poll() is not None:
                return True
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=2) as answer:
                    return answer.status == 200
            except OSError:
                return False

        if not wait_for(answering, 60) or self.process.poll() is not None:
            self.stop()
            pytest.fail("PiTrac did not start:\n" + (self.home / "pitrac.log").read_text()[-3000:])

    def stop(self):
        self.process.terminate()
        try:
            self.process.wait(15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(5)
        self.log.close()

    def hit(self, **measured):
        """Report a swing exactly as ``pitrac_lm`` does."""

        body = {"result_type": 7, "speed_mps": 54.5, "launch_angle": 16.3, "side_angle": 0.0,
                "back_spin": 7097, "side_spin": -240, "carry": 0}
        body.update(measured)
        request = urllib.request.Request(
            self.url + "/api/internal/shot-result", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as answer:
            return json.loads(answer.read())


@pytest.fixture
def pitrac(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    running = RealPitrac(home)
    yield running
    running.stop()


@pytest.fixture
def relay():
    with ShotRelay(ports={Simulator.GSPRO: 0, Simulator.E6: 0}) as running:
        yield running


def installation(pitrac, tmp_path):
    return PitracInstallation(PitracApi(pitrac.url), config_dir=tmp_path / "config")


def test_a_new_pitrac_is_connected_and_its_shots_arrive(pitrac, relay, tmp_path):
    """The whole point: from PiTrac's database to our relay, with no hand edits."""

    arrived = []
    relay.attach_companion(arrived.append)
    pitrac_here = installation(pitrac, tmp_path)
    port = relay.ports[Simulator.GSPRO]

    assert pitrac_here.snapshot(0).relay_target(port) is None
    assert pitrac_here.ensure_relay_target(relay.ports) == [
        "Added Easy-Connect to PiTrac's simulators"]
    assert wait_for(lambda: pitrac_here.snapshot(0).relay_target(port).delivering), \
        pitrac_here.snapshot(0)

    pitrac.hit()
    shots = wait_for(lambda: [
        frame for frame in arrived if frame["payload"]["ShotDataOptions"]["ContainsBallData"]])
    assert len(shots) == 1
    ball = shots[0]["payload"]["BallData"]
    assert ball["Speed"] == pytest.approx(121.9, abs=0.1)
    assert (ball["VLA"], ball["HLA"]) == (16.3, 0.0)
    assert (ball["BackSpin"], ball["SideSpin"]) == (7097.0, -240.0)


def test_the_target_survives_restarts_without_being_doubled(pitrac, relay, tmp_path):
    pitrac_here = installation(pitrac, tmp_path)
    pitrac_here.ensure_relay_target(relay.ports)
    first = pitrac_here.api.sims()

    pitrac.stop()
    assert pitrac_here.snapshot(0).reachable is False
    pitrac.start()

    assert pitrac_here.ensure_relay_target(relay.ports) == []
    assert [sim["id"] for sim in pitrac_here.api.sims()] == [sim["id"] for sim in first]
    port = relay.ports[Simulator.GSPRO]
    assert wait_for(lambda: pitrac_here.snapshot(0).relay_target(port).delivering)


def test_targets_an_earlier_release_left_in_json_are_tidied(pitrac, relay, tmp_path):
    """PiTrac imports them as two live simulators. Only one may stay on."""

    pitrac.stop()
    config = pitrac.home / ".pitrac" / "config"
    config.mkdir(parents=True, exist_ok=True)
    (pitrac.home / ".pitrac" / "pitrac.db").unlink()
    gspro, e6 = relay.ports[Simulator.GSPRO], relay.ports[Simulator.E6]
    (config / "user_settings.json").write_text(json.dumps({"gs_config": {"golf_simulator_interfaces": {
        "GSPro": {"kGSProConnectAddress": "127.0.0.1", "kGSProConnectPort": gspro},
        "E6": {"kE6ConnectAddress": "127.0.0.1", "kE6ConnectPort": e6},
    }}}))
    pitrac.start()

    pitrac_here = installation(pitrac, tmp_path)
    assert sorted(sim["type"] for sim in pitrac_here.api.sims() if sim["on"]) == ["e6", "gspro"]
    pitrac_here.ensure_relay_target(relay.ports)
    assert [sim["type"] for sim in pitrac_here.api.sims() if sim["on"]] == ["gspro"]


def test_an_edited_target_is_corrected(pitrac, relay, tmp_path):
    pitrac_here = installation(pitrac, tmp_path)
    pitrac_here.ensure_relay_target(relay.ports)
    sim = pitrac_here.api.sims()[0]
    pitrac_here.api.update_sim(sim["id"], {"settings": {"host": "10.0.0.9", "port": 921}})

    pitrac_here.ensure_relay_target(relay.ports)
    port = relay.ports[Simulator.GSPRO]
    assert len(pitrac_here.api.sims()) == 1
    assert wait_for(lambda: pitrac_here.snapshot(0).relay_target(port).delivering)


def test_calibration_readiness_is_read_from_pitrac(pitrac, tmp_path):
    pitrac_here = installation(pitrac, tmp_path)
    fresh = pitrac_here.snapshot(0)
    assert fresh.readable is True
    assert fresh.uncalibrated() == [
        "camera 1 lens", "camera 1 position", "camera 2 lens", "camera 2 position"]
    assert isinstance(fresh.strobe["safe"], bool)

    assert pitrac_here.import_(calibration_data=CALIBRATION) == {}
    assert pitrac_here.snapshot(0).calibrated is True


def test_calibration_survives_a_backup_and_a_lost_database(pitrac, tmp_path):
    pitrac_here = installation(pitrac, tmp_path)
    pitrac_here.import_(
        calibration_data=CALIBRATION,
        user_settings={"gs_config": {"cameras": {"kCamera1Gain": 2.5}}},
    )
    saved = pitrac_here.export()

    identity = IdentityStore(tmp_path / "device.json")
    manager = BackupManager(
        identity, ConfigStore(tmp_path / "settings.json", {}), pitrac_here,
        PairingManager(tmp_path / "pairings.json", identity.identity.device_id),
        tmp_path / "backups",
    )
    backup = manager.create_bytes()

    pitrac.stop()
    (pitrac.home / ".pitrac" / "pitrac.db").unlink()
    pitrac.start()
    assert pitrac_here.snapshot(0).calibrated is False

    manager.restore(backup)
    assert pitrac_here.snapshot(0).calibrated is True
    restored = pitrac_here.export()
    assert restored["calibration_data"] == saved["calibration_data"]
    assert restored["user_settings"] == saved["user_settings"]


def test_restoring_one_section_leaves_the_other_alone(pitrac, tmp_path):
    pitrac_here = installation(pitrac, tmp_path)
    pitrac_here.import_(calibration_data=CALIBRATION)
    pitrac_here.import_(user_settings={"gs_config": {"cameras": {"kCamera1Gain": 2.5}}})
    assert pitrac_here.snapshot(0).calibrated is True


def test_a_value_pitrac_will_not_take_is_reported(pitrac, tmp_path):
    broken = copy.deepcopy(CALIBRATION)
    broken["gs_config"]["cameras"]["kCamera1FocalLength"] = "not a number"
    refused = installation(pitrac, tmp_path).import_(calibration_data=broken)
    assert list(refused) == ["gs_config.cameras.kCamera1FocalLength"]


def test_refusals_and_missing_routes_are_told_apart(pitrac):
    api = PitracApi(pitrac.url)
    with pytest.raises(PitracRefused):
        api.update_sim("no-such-simulator", {"on": False})
    with pytest.raises(PitracRefused):
        api.create_sim({"type": "gspro", "settings": {"host": "", "port": 9210}})
    with pytest.raises(PitracUnsupported):
        api._call("GET", "/api/not-a-route")


def test_the_stand_in_answers_in_the_same_shapes(pitrac):
    """What the rest of the suite relies on."""

    real, stand_in = PitracApi(pitrac.url), SimulatedPitracApi()
    body = {"type": "gspro", "name": "x", "on": True, "settings": {"host": "127.0.0.1", "port": 9}}
    for answer in ("create_sim", "sims", "setup_status", "export_config"):
        arguments = (body,) if answer == "create_sim" else ()
        theirs = getattr(real, answer)(*arguments)
        ours = getattr(stand_in, answer)(*arguments)
        _assert_within(ours, theirs, answer)


def _assert_within(ours, theirs, where):
    """Everything the stand-in provides exists in the real answer, same type."""

    if isinstance(ours, dict):
        assert isinstance(theirs, dict), where
        for key, value in ours.items():
            assert key in theirs, "{}.{}".format(where, key)
            _assert_within(value, theirs[key], "{}.{}".format(where, key))
    elif isinstance(ours, list):
        assert isinstance(theirs, list), where
        if ours and theirs:
            _assert_within(ours[0], theirs[0], where + "[]")
    else:
        assert type(ours) is type(theirs), "{}: {!r} / {!r}".format(where, ours, theirs)

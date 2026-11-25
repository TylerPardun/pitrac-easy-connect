"""Playing with nothing but PiTrac and this computer.

No simulator, no account, no internet, and on a Mac no choice: GSPro does not
run there. A measured swing has to be saved once, drawn, and reported to the
enclosure as handled, without anything trying to open a simulator.
"""

import json
import socket
import sys
import time

import pytest

from pitrac_easy_connect.common.states import State
from pitrac_easy_connect.companion.service import CompanionService
from pitrac_easy_connect.models import PlayMode, Simulator

from test_companion import Rig

SHOT = {
    "DeviceID": "PiTrac LM 0.1", "Units": "Yards", "ShotNumber": 1, "APIversion": "1",
    "BallData": {"Speed": 122.0, "SpinAxis": 0.0, "TotalSpin": 7097.0, "BackSpin": 7097.0,
                 "SideSpin": 0.0, "HLA": 0.0, "VLA": 16.3},
    "ClubData": {},
    "ShotDataOptions": {"ContainsBallData": True, "ContainsClubData": False,
                        "LaunchMonitorIsReady": True, "LaunchMonitorBallDetected": True,
                        "IsHeartBeat": False},
}
HEARTBEAT = dict(SHOT, ShotNumber=0, ShotDataOptions=dict(
    SHOT["ShotDataOptions"], ContainsBallData=False, IsHeartBeat=True))


def wait_for(condition, seconds=8.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return bool(condition())


class Pitrac:
    """PiTrac's end of the relay: sends shots, and hears the club."""

    def __init__(self, rig):
        self.sock = socket.create_connection(
            ("127.0.0.1", rig.pi.relay.ports[Simulator.GSPRO]), timeout=5)
        self.heard = []

    def send(self, message):
        self.sock.sendall(json.dumps(message).encode())

    def listen(self, seconds=1.0):
        self.sock.settimeout(0.1)
        buffer, decoder = "", json.JSONDecoder()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                buffer += self.sock.recv(65536).decode()
            except socket.timeout:
                continue
            while buffer:
                try:
                    message, end = decoder.raw_decode(buffer)
                except ValueError:
                    break
                self.heard.append(message)
                buffer = buffer[end:]
        return self.heard

    def clubs(self, seconds=1.0):
        return [m["Player"]["Club"] for m in self.listen(seconds) if m.get("Code") == 201]

    def close(self):
        self.sock.close()


@pytest.fixture
def rig(tmp_path):
    built = Rig(tmp_path)
    # Nothing is listening where GSPro would be.
    built.mock.stop()
    built.companion.select_simulator("local")
    built.pair()
    assert built.wait_linked() is True
    yield built
    built.close()


@pytest.fixture
def pitrac(rig):
    connected = Pitrac(rig)
    yield connected
    connected.close()


# --- The default, and what can be chosen -----------------------------------


def test_a_new_installation_starts_on_the_local_range(tmp_path):
    service = CompanionService(tmp_path / "c.json", discovery_port=0, startup_update_check=False)
    try:
        assert service.mode is PlayMode.LOCAL
        assert [mode["value"] for mode in service.status()["playModes"]] == ["local", "ogs", "gspro"]
    finally:
        service.close()


def test_a_choice_that_is_no_longer_offered_becomes_the_local_range(tmp_path):
    service = CompanionService(tmp_path / "c.json", discovery_port=0, startup_update_check=False)
    try:
        service.store.set("simulator", "e6")
        assert service.status()["simulator"] == "local"
    finally:
        service.close()


@pytest.mark.parametrize("platform, said", [("darwin", "only on Windows"), ("win32", "")])
def test_a_mac_is_told_gspro_will_not_run_there(rig, monkeypatch, platform, said):
    monkeypatch.setattr(sys, "platform", platform)
    note = rig.companion.play_modes()[-1]["note"]
    assert (said in note) if said else note == ""


# --- A swing ----------------------------------------------------------------


def test_a_swing_is_saved_once_drawn_and_accepted(rig, pitrac):
    pitrac.send(SHOT)
    assert wait_for(lambda: rig.pi.relay.status()["shotsForwarded"] == 1)

    recent = rig.companion.shots.recent()
    assert len(recent) == 1
    assert recent[0]["simulator"] == "local"
    assert recent[0]["delivered"] is None, "there was nobody to deliver it to"
    assert (recent[0]["speed"], recent[0]["direction"]) == (122.0, 0.0)

    drawn = rig.companion.range_status()
    assert drawn["count"] == 1
    assert drawn["shots"][0]["ball"]["direction"] == 0.0
    assert rig.pi.relay.status()["shotsFailed"] == 0


def test_nothing_tries_to_open_a_simulator(rig, pitrac, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("tried to open a simulator")

    import pitrac_easy_connect.companion.service as service_module

    monkeypatch.setattr(service_module, "SimulatorSession", refuse)
    pitrac.send(HEARTBEAT)
    pitrac.send(SHOT)
    assert wait_for(lambda: rig.companion.range_status()["count"] == 1)
    rig.companion.check_simulator()


def test_pitrac_is_not_told_the_shot_failed(rig, pitrac):
    pitrac.send(SHOT)
    assert [m for m in pitrac.listen() if m.get("Code", 0) >= 500] == []


def test_heartbeats_are_not_swings(rig, pitrac):
    for _ in range(3):
        pitrac.send(HEARTBEAT)
    pitrac.send(SHOT)
    assert wait_for(lambda: rig.companion.range_status()["count"] == 1)
    assert len(rig.companion.shots.recent()) == 1
    assert rig.companion._shots_delivered == 1


def test_club_averages_work_with_no_simulator(rig, pitrac):
    rig.companion.set_club("I7")
    for _ in range(3):
        pitrac.send(SHOT)
    assert wait_for(lambda: len(rig.companion.shots.recent()) == 3)
    row = rig.companion.status()["shotLog"]["byClub"][0]
    assert (row["club"], row["shots"], row["speed"]) == ("7 iron", 3, 122.0)


# --- Being ready ------------------------------------------------------------


def test_ready_needs_no_simulator_and_no_test_shot(rig):
    assert rig.wait_state(State.READY_TO_PLAY.value) is True
    assert [step["key"] for step in rig.companion.chain()] == ["pitrac", "link", "capture"]


def test_the_enclosure_agrees_it_is_ready(rig):
    def check():
        return next(c for c in rig.pi.selftest.run().checks if c.key == "simulator")

    assert wait_for(lambda: check().status == "pass")
    assert check().title == "Local Range"
    assert "test shot" not in check().detail


def test_a_test_shot_is_refused_rather_than_pretended(rig):
    with pytest.raises(ValueError, match="no simulator"):
        rig.companion.send_test_shot()


def test_a_shot_that_cannot_be_saved_is_said_so_and_still_drawn(rig, pitrac, monkeypatch):
    def full(*_args, **_kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(rig.companion.shots, "record", full)
    pitrac.send(SHOT)
    assert wait_for(lambda: rig.pi.relay.status()["shotsFailed"] == 1)

    assert rig.companion.range_status()["count"] == 1
    status = rig.companion.status()
    assert status["ready"] is False
    assert status["state"] == State.RECOVERY_REQUIRED.value
    assert "No space left" in status["simulatorStatus"]["message"]

    monkeypatch.undo()
    rig.companion.check_simulator()
    assert rig.companion.simulator_status()["ready"] is True


# --- Putting, which PiTrac has to be told about ------------------------------


def test_choosing_the_putter_tells_pitrac(rig, pitrac):
    rig.companion.set_club("Putter")
    assert pitrac.clubs() == ["PT"]
    rig.companion.set_club("I7")
    assert pitrac.clubs() == ["PT", "DR"]


def test_pitrac_is_reminded_whenever_it_reconnects(rig, pitrac):
    """It forgets the club when its connection drops, and says hello again."""

    rig.companion.set_club("Putter")
    pitrac.close()
    again = Pitrac(rig)
    try:
        again.send(HEARTBEAT)
        assert again.clubs() == ["PT"]
    finally:
        again.close()


def test_switching_to_gspro_takes_pitrac_off_the_putter(rig, pitrac):
    rig.companion.set_club("Putter")
    rig.companion.select_simulator("gspro")
    assert pitrac.clubs() == ["PT", "DR"]
    rig.companion.set_club("Putter")
    assert pitrac.clubs() == ["PT", "DR"], "GSPro decides the club in its own mode"


def test_a_putt_is_recorded_though_it_never_leaves_the_ground(rig, pitrac):
    rig.companion.set_club("Putter")
    putt = dict(SHOT, BallData=dict(SHOT["BallData"], Speed=4.2, VLA=0.0, BackSpin=0.0))
    pitrac.send(putt)
    assert wait_for(lambda: len(rig.companion.shots.recent()) == 1)

    drawn = rig.companion.range_status()
    assert drawn["count"] == 0, "no flight was invented"
    assert drawn["unflown"]["club"] == "Putter"
    assert drawn["unflown"]["ball"]["launch"] == 0.0

    pitrac.send(SHOT)
    assert wait_for(lambda: rig.companion.range_status()["count"] == 1)
    assert rig.companion.range_status()["unflown"] is None


# --- Numbers the launch monitor did not give ---------------------------------


def test_missing_spin_is_not_shown_as_zero(rig):
    ball = {key: value for key, value in SHOT["BallData"].items() if "pin" not in key}
    rig.companion._forward_shot(1, "gspro", dict(SHOT, BallData=ball))
    drawn = rig.companion.range_status()["shots"][0]
    assert drawn["ball"]["backSpin"] is None
    assert drawn["ball"]["direction"] == 0.0
    assert drawn["carryYards"] > 0, "the flight still has to assume something"

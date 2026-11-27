"""Playing OpenGolfSim, and knowing what became of each shot.

It answers every message, whether or not it is showing anything a ball could be
hit on, so being answered and being played are kept apart.
"""

import os
import subprocess
import time

import pytest

from pitrac_easy_connect.common.states import State
from pitrac_easy_connect.companion import opengolfsim
from pitrac_easy_connect.companion.page import PAGE
from pitrac_easy_connect.models import PlayMode, Simulator

from fake_simulators import FakeGSPro, FakeOpenGolfSim
from test_companion import Rig
from test_local_range import HEARTBEAT, SHOT, Pitrac, wait_for


def swing(**ball):
    return dict(SHOT, BallData=dict(SHOT["BallData"], **ball))


def heartbeat(ball):
    return dict(HEARTBEAT, ShotDataOptions=dict(
        HEARTBEAT["ShotDataOptions"], LaunchMonitorBallDetected=ball))


@pytest.fixture
def ogs():
    running = FakeOpenGolfSim()
    yield running
    running.close()


@pytest.fixture
def rig(tmp_path, ogs):
    built = Rig(tmp_path)
    built.companion.simulator_ports[Simulator.OGS] = ogs.port
    built.companion.select_simulator("ogs")
    built.pair()
    assert built.wait_linked() is True
    yield built
    built.close()


@pytest.fixture
def pitrac(rig):
    connected = Pitrac(rig)
    yield connected
    connected.close()


def latest(rig):
    recent = rig.companion.shots.recent()
    return recent[0] if recent else {}


# --- The shot, in its language ------------------------------------------------


def test_a_shot_is_translated_exactly():
    message = opengolfsim.shot_message(swing(
        Speed=101.2, VLA=15.4, HLA=-2.1, BackSpin=3000.0, SideSpin=-300.0, TotalSpin=3015.0))
    assert message == {"type": "shot", "unit": "imperial", "shot": {
        "ballSpeed": 101.2, "verticalLaunchAngle": 15.4, "horizontalLaunchAngle": -2.1,
        "spinSpeed": 3015, "spinAxis": -5.7}}


@pytest.mark.parametrize("ball, expected", [
    ({"VLA": 80.0}, {"verticalLaunchAngle": 45.0}),
    ({"VLA": -3.0}, {"verticalLaunchAngle": 0.0}),
    ({"HLA": -60.0}, {"horizontalLaunchAngle": -45.0}),
    ({"BackSpin": 0.0, "SideSpin": 9000.0}, {"spinAxis": 45.0}),
    ({"BackSpin": 0.0, "SideSpin": 0.0, "TotalSpin": 0.0}, {"spinAxis": 0.0, "spinSpeed": 0}),
])
def test_what_it_cannot_take_is_brought_within_range(ball, expected):
    shot = opengolfsim.shot_message(swing(**ball))["shot"]
    for key, value in expected.items():
        assert shot[key] == value


@pytest.mark.parametrize("payload", [{}, {"BallData": {}}, swing(Speed=0), swing(Speed=None)])
def test_no_ball_is_no_shot(payload):
    assert opengolfsim.shot_message(payload) is None


def test_the_direction_signs_agree_with_its_own_published_result():
    """A comment in its examples has the spin axis the other way round. Its own
    documented shot finished 0.08 m from the line, which says otherwise."""

    import math

    from pitrac_easy_connect.companion import flight

    sent = opengolfsim.shot_message(swing(
        Speed=135.0, VLA=11.1, HLA=1.2,
        BackSpin=4800 * math.cos(math.radians(-2.5)), SideSpin=4800 * math.sin(math.radians(-2.5)),
        TotalSpin=4800.0))["shot"]
    assert (sent["horizontalLaunchAngle"], sent["spinAxis"]) == (1.2, -2.5)
    flown = flight.simulate(135, 11.1, 1.2, 4800 * math.cos(math.radians(-2.5)),
                            4800 * math.sin(math.radians(-2.5)))
    assert abs(flown["offlineYards"]) < 1.0


@pytest.mark.skipif(not os.environ.get("PITRAC_SOURCE"), reason="needs PITRAC_SOURCE")
def test_it_is_what_pitrac_itself_would_have_sent():
    """PiTrac has its own OpenGolfSim sender, tried against the real thing."""

    code = """
import sys, json; sys.path.insert(0, sys.argv[1])
from models import ShotData
from sims.ogs_sim import build_shot_payload as ogs
from sims.gspro_sim import build_shot_payload as gspro
out = []
for v in ((122, 16.3, 0, 7097, 0), (167, 10.9, 2.4, 2686, -420), (84, 33, -5.1, 9300, 600), (4.2, 0, 0, 0, 0)):
    s = ShotData(speed=v[0], launch_angle=v[1], side_angle=v[2], back_spin=v[3], side_spin=v[4])
    out.append([gspro(s, 1), ogs(s)])
print(json.dumps(out))
"""
    import json

    done = subprocess.run(
        [os.environ["PITRAC_PYTHON"], "-c", code,
         os.path.join(os.environ["PITRAC_SOURCE"], "Software", "web-server")],
        capture_output=True, text=True, check=True)
    for relayed, theirs in json.loads(done.stdout):
        ours = opengolfsim.shot_message(relayed)
        assert {k: v for k, v in ours.items() if k != "shot"} == {
            k: v for k, v in theirs.items() if k != "shot"}
        for key, value in theirs["shot"].items():
            assert ours["shot"][key] == pytest.approx(value, abs=1 if key == "spinSpeed" else 0.11)


@pytest.mark.parametrize("theirs, ours", [
    ("7I", "I7"), ("3W", "W3"), ("4H", "H4"), ("DR", "DR"), ("PW", "PW"), ("PT", "PT"),
    ("Putter", "PT"), ("", ""),
])
def test_its_clubs_are_understood(theirs, ours):
    assert opengolfsim.gspro_club(theirs) == ours


# --- A swing, from PiTrac to the simulator and back -----------------------------


def test_a_swing_is_played_and_its_result_comes_back(rig, pitrac, ogs):
    pitrac.send(SHOT)
    assert wait_for(lambda: latest(rig).get("outcome") == "played")
    shot = latest(rig)
    assert ogs.shots[0]["ballSpeed"] == 122.0
    assert (shot["simCarry"], shot["simTotal"], shot["simOffline"]) == (164.0, 168.4, -2.2)
    assert shot["delivered"] is True and shot["simulator"] == "ogs"
    assert shot["carry"] > 0, "and it is on the range as well"
    assert rig.pi.relay.status()["shotsForwarded"] == 1


def test_every_message_arrives_alone(rig, pitrac, ogs):
    """Two in one read are both dropped, silently."""

    ogs.read_delay = 0.09
    for ball in (True, False, True):
        pitrac.send(heartbeat(ball))
    for speed in (118.0, 121.0, 124.0):
        pitrac.send(swing(Speed=speed))
    assert wait_for(lambda: len(ogs.shots) == 3, 10)
    assert ogs.lost == 0
    assert wait_for(lambda: [s["outcome"] for s in rig.companion.shots.recent()] == ["played"] * 3)


def test_results_go_to_the_shots_they_are_for(rig, pitrac, ogs):
    ogs.on_a_hole = False
    for speed in (118.0, 124.0):
        pitrac.send(swing(Speed=speed))
    assert wait_for(lambda: len(ogs.shots) == 2)
    ogs.finish(ogs.shots[1], carry=200.0)
    ogs.finish({"ballSpeed": 99.0, "verticalLaunchAngle": 9.0, "horizontalLaunchAngle": 0.0,
                "spinSpeed": 100, "spinAxis": 0.0}, carry=10.0)      # somebody's mouse
    assert wait_for(lambda: latest(rig).get("outcome") == "played")
    second, first = rig.companion.shots.recent()
    assert (second["speed"], second["simCarry"]) == (124.0, 218.7)
    assert (first["outcome"], "simCarry" in first) == ("accepted", False)


def test_nowhere_to_hit_from_is_taken_but_not_played(rig, pitrac, ogs):
    ogs.on_a_hole = False
    pitrac.send(SHOT)
    assert wait_for(lambda: latest(rig).get("outcome") == "accepted")
    assert rig.companion.status()["ready"] is False, "nothing has shown that shots count"


def test_a_refusal_is_not_called_delivered(rig, pitrac, ogs):
    ogs.refuse = True
    pitrac.send(SHOT)
    assert wait_for(lambda: latest(rig).get("outcome") == "rejected")
    assert latest(rig)["delivered"] is False
    assert wait_for(lambda: rig.pi.relay.status()["shotsFailed"] == 1)


def test_silence_is_reported_as_silence(rig, pitrac, ogs):
    ogs.silent = True
    pitrac.send(SHOT)
    assert wait_for(lambda: latest(rig).get("outcome") == "unknown")
    assert latest(rig)["delivered"] is None


def test_a_swing_with_it_closed_is_still_kept(rig, pitrac, ogs):
    ogs.close()
    pitrac.send(SHOT)
    assert wait_for(lambda: latest(rig).get("outcome") == "undelivered", 12)
    assert rig.companion.range_status()["count"] == 1


def test_it_is_found_again_after_being_restarted(rig, pitrac, ogs):
    pitrac.send(SHOT)
    assert wait_for(lambda: latest(rig).get("outcome") == "played")
    ogs.close()
    again = FakeOpenGolfSim()
    try:
        rig.companion.simulator_ports[Simulator.OGS] = again.port
        rig.companion._session.close()
        rig.companion._session = None
        pitrac.send(swing(Speed=130.0))
        assert wait_for(lambda: len(again.shots) == 1)
    finally:
        again.close()


# --- Being ready ----------------------------------------------------------------


def test_one_real_swing_that_is_played_is_proof(rig, pitrac, ogs):
    assert rig.companion.status()["ready"] is False
    pitrac.send(SHOT)
    assert rig.wait_state(State.READY_TO_PLAY.value)


def test_a_test_shot_waits_to_see_it_played(rig, ogs):
    rig.companion.send_test_shot()
    assert rig.companion.status()["simulatorStatus"]["ready"] is True
    assert rig.companion.shots.recent() == [], "nobody hit that"


def test_a_test_shot_with_nowhere_to_go_says_so(rig, ogs, monkeypatch):
    monkeypatch.setattr(opengolfsim, "TEST_RESULT_SECONDS", 0.5)
    ogs.on_a_hole = False
    rig.companion.send_test_shot()
    status = rig.companion.status()["simulatorStatus"]
    assert status["ready"] is False
    assert status["errorCode"] == "PT-SIM-007"


def test_it_hears_whether_there_is_a_ball(rig, pitrac, ogs):
    pitrac.send(heartbeat(True))
    assert wait_for(lambda: ogs.statuses[-1:] == ["ready"])
    pitrac.send(heartbeat(False))
    assert wait_for(lambda: ogs.statuses[-1] == "busy")


def test_it_is_reminded_while_nothing_happens(monkeypatch, ogs):
    monkeypatch.setattr(opengolfsim, "KEEPALIVE_SECONDS", 0.2)
    session = opengolfsim.OpenGolfSimSession(port=ogs.port)
    try:
        session.connect()
        assert wait_for(lambda: len(ogs.statuses) >= 4)
    finally:
        session.close()
    time.sleep(0.5)
    count = len(ogs.statuses)
    time.sleep(0.6)
    assert len(ogs.statuses) == count, "it went on after being closed"


# --- Clubs --------------------------------------------------------------------------


def test_changing_club_there_changes_it_here_and_on_pitrac(rig, pitrac, ogs):
    ogs.choose("PT")
    assert wait_for(lambda: rig.companion.shots.club == "Putter")
    assert pitrac.clubs()[-1] == "PT"
    ogs.choose("7I")
    assert wait_for(lambda: rig.companion.shots.club == "7 iron")
    assert pitrac.clubs()[-1] == "DR"


def test_its_own_messages_never_reach_pitrac(rig, pitrac, ogs):
    """PiTrac would read them as GSPro being broken."""

    pitrac.send(SHOT)
    assert wait_for(lambda: latest(rig).get("outcome") == "played")
    assert all("Code" in message for message in pitrac.listen(0.5))


def test_auto_club_leaves_it_to_the_simulator(rig, ogs):
    ogs.choose("5I")
    assert wait_for(lambda: rig.companion.shots.club == "5 iron")
    status = rig.companion.set_range_target(60)
    assert (status["club"], status["autoClub"], status["clubIsOurs"]) == ("5 iron", False, False)


# --- GSPro, judged the same way --------------------------------------------------------


@pytest.mark.parametrize("answer, chatter, outcome, delivered", [
    ({"Code": 200, "Message": "ok"}, False, "accepted", True),
    ({"Code": 200, "Message": "ok"}, True, "accepted", True),
    ({"Code": 501, "Message": "not ready"}, False, "rejected", False),
    ({"Code": 500, "Message": "bad"}, True, "rejected", False),
    (False, True, "unknown", None),       # only ever talked about the player
    (False, False, "unknown", None),
])
def test_gspro_shots_are_called_what_gspro_called_them(tmp_path, answer, chatter, outcome, delivered):
    """A shot it explicitly refused was shown in history as delivered."""

    gspro = FakeGSPro(answer)
    gspro.chatter = chatter
    rig = Rig(tmp_path)
    try:
        rig.companion.simulator_ports[Simulator.GSPRO] = gspro.port
        rig.companion.select_simulator("gspro")
        result = rig.companion._forward_shot(1, "gspro", SHOT)
        assert (result["outcome"], latest(rig)["delivered"]) == (outcome, delivered)
        assert result["accepted"] is (outcome != "rejected")
        assert rig.companion.simulator_status()["ready"] is (outcome == "accepted")
    finally:
        rig.close()
        gspro.close()


def test_heartbeats_are_not_waited_on(tmp_path):
    gspro = FakeGSPro(False)
    rig = Rig(tmp_path)
    try:
        rig.companion.simulator_ports[Simulator.GSPRO] = gspro.port
        rig.companion.select_simulator("gspro")
        began = time.monotonic()
        for _ in range(5):
            rig.companion._forward_shot(1, "gspro", HEARTBEAT)
        assert time.monotonic() - began < 0.5
        assert rig.companion.shots.recent() == []
    finally:
        rig.close()
        gspro.close()


def test_gspro_dying_in_the_middle_is_not_silence(tmp_path):
    gspro = FakeGSPro(False)
    real = gspro.heard
    gspro.heard = lambda client, data: (real(client, data), gspro.close())
    rig = Rig(tmp_path)
    try:
        rig.companion.simulator_ports[Simulator.GSPRO] = gspro.port
        rig.companion.select_simulator("gspro")
        assert rig.companion._forward_shot(1, "gspro", SHOT)["outcome"] == "undelivered"
    finally:
        rig.close()


# --- In the window ------------------------------------------------------------------------


def test_it_is_offered_wherever_the_others_are():
    assert [mode.value for mode in PlayMode] == ["local", "ogs", "gspro"]
    assert PAGE.count('data-sim="ogs"') == PAGE.count('data-sim="gspro"') == 1
    assert '"wizOgs"' in PAGE


def test_the_thing_people_miss_is_said():
    where = PAGE.split("const SIM_WHERE = {")[1].split("};")[0]
    assert "Developer API" in where and "3111" in where


def test_a_test_shot_is_not_said_to_test_more_than_it_does():
    """It starts on this computer, so it passes neither the cameras nor the Pi."""

    assert "proves the whole path" not in PAGE
    assert "A test shot checks only this computer" in PAGE


def test_every_outcome_has_words():
    from pitrac_easy_connect.companion import simulator_session as s

    body = PAGE.split("function outcomeText(s){")[1].split("\n}")[0]
    for outcome in (s.PLAYED, s.ACCEPTED, s.UNKNOWN, s.REJECTED, s.UNDELIVERED, s.LOCAL):
        assert 'case "{}"'.format(outcome) in body


# --- Whose answer is it -----------------------------------------------------------


HOOK = swing(BackSpin=7000.0, SideSpin=-900.0, TotalSpin=7058.0)
SLICE = swing(BackSpin=7000.0, SideSpin=900.0, TotalSpin=7058.0)


def outcomes(rig):
    """Oldest first."""

    return [shot["outcome"] for shot in reversed(rig.companion.shots.recent())]


@pytest.mark.parametrize("played, expected", [(0, ["played", "accepted"]), (1, ["accepted", "played"])])
def test_a_hook_is_not_mistaken_for_the_slice_that_matches_it(rig, pitrac, ogs, played, expected):
    ogs.on_a_hole = False
    for shot in (HOOK, SLICE):
        pitrac.send(shot)
    assert wait_for(lambda: outcomes(rig) == ["accepted", "accepted"])
    ogs.finish(ogs.shots[played])
    assert wait_for(lambda: outcomes(rig) == expected)


def test_a_result_that_fits_two_swings_is_given_to_neither(rig, pitrac, ogs):
    ogs.on_a_hole = False
    for _ in range(2):
        pitrac.send(SHOT)
    assert wait_for(lambda: outcomes(rig) == ["accepted", "accepted"])
    ogs.finish(ogs.shots[0])
    time.sleep(0.4)
    assert outcomes(rig) == ["accepted", "accepted"]


class Holding:
    """Keeps back what it would have said to each shot, until told."""

    def __init__(self, server, is_shot):
        self.server, self.is_shot, self.waiting = server, is_shot, []
        self.real, server.heard = server.heard, self.heard

    def heard(self, client, data):
        if self.is_shot(data):
            self.server.received.append(__import__("json").loads(data))
            self.waiting.append(client)
        else:
            self.real(client, data)


def ogs_holding(ogs):
    return Holding(ogs, lambda data: b'"shot"' in data)


def test_a_late_yes_is_not_given_to_a_shot_that_was_refused(rig, ogs):
    holding = ogs_holding(ogs)
    rig.companion._forward_shot(1, "gspro", swing(Speed=120.0))
    assert outcomes(rig) == ["unknown"]

    import threading

    def then():
        time.sleep(0.8)
        ogs.say({"status": 200}, holding.waiting[0])        # for the first, far too late
        time.sleep(0.2)
        ogs.say({"status": 400, "error": "no"}, holding.waiting[1])

    threading.Thread(target=then, daemon=True).start()
    rig.companion._forward_shot(2, "gspro", swing(Speed=125.0))
    assert wait_for(lambda: outcomes(rig)[1] in ("rejected", "unknown"), 3)
    assert outcomes(rig)[0] == "unknown"
    assert "accepted" not in outcomes(rig)


def test_a_late_yes_before_the_next_swing_belongs_to_the_one_before(rig, ogs):
    """It can only be about that one, so it is not thrown away."""

    holding = ogs_holding(ogs)
    rig.companion._forward_shot(1, "gspro", SHOT)
    assert outcomes(rig) == ["unknown"]
    ogs.say({"status": 200}, holding.waiting[0])
    assert wait_for(lambda: outcomes(rig) == ["accepted"])
    assert len(ogs.clients) == 1, "a simulator that was only slow was cut off"


def test_a_reminder_is_not_mistaken_for_an_answer(rig, ogs, monkeypatch):
    """Everything is answered in the same words, so nothing else may be said
    while a shot is owed one."""

    monkeypatch.setattr(opengolfsim, "OWED_SECONDS", 0.6)
    ogs_holding(ogs)
    rig.companion._forward_shot(1, "gspro", SHOT)
    for ball in (True, False, True):
        rig.companion._forward_shot(2, "gspro", heartbeat(ball))
        time.sleep(0.15)
    time.sleep(1.0)
    rig.companion._forward_shot(2, "gspro", heartbeat(False))
    time.sleep(0.5)
    assert outcomes(rig) == ["unknown"]
    assert len(ogs.clients) == 2, "it started again rather than staying silent for ever"


def test_an_unanswered_greeting_is_not_the_answer_to_a_shot(ogs):
    said = []
    ogs.silent = True
    session = opengolfsim.OpenGolfSimSession(port=ogs.port, on_late_answer=lambda *a: said.append(a))
    try:
        session.connect()
        assert session.deliver(SHOT, "one").outcome == "unknown"
        ogs.say({"status": 200})         # about the greeting, at last
        time.sleep(0.3)
        assert said == []
        ogs.say({"status": 200})         # and this is about the shot
        assert wait_for(lambda: [(i, d.outcome) for i, d in said] == [("one", "accepted")])
    finally:
        session.close()


@pytest.fixture
def gspro_rig(tmp_path):
    server = FakeGSPro(False)
    built = Rig(tmp_path)
    built.companion.simulator_ports[Simulator.GSPRO] = server.port
    built.companion.select_simulator("gspro")
    built.server = server
    yield built
    built.close()
    server.close()


def test_gspros_late_yes_is_not_given_to_a_shot_it_refused(gspro_rig):
    import threading

    rig, server = gspro_rig, gspro_rig.server
    first = []
    real = server.heard

    def heard(client, data):
        real(client, data)
        shots = [m for m in server.received if not m["ShotDataOptions"]["IsHeartBeat"]]
        if len(shots) == 1:
            first.append(client)
        else:
            threading.Thread(target=lambda: (
                time.sleep(0.2), server.say({"Code": 200, "Message": "the first"}, first[0]),
                time.sleep(0.2), server.say({"Code": 501, "Message": "the second"}, client),
            ), daemon=True).start()

    server.heard = heard
    for speed in (120.0, 125.0):
        rig.companion._forward_shot(1, "gspro", swing(Speed=speed))
    assert outcomes(rig) == ["unknown", "rejected"]


def test_gspros_late_yes_before_the_next_swing_is_kept(gspro_rig):
    rig, server = gspro_rig, gspro_rig.server
    rig.companion._forward_shot(1, "gspro", SHOT)
    assert outcomes(rig) == ["unknown"]
    server.say({"Code": 201, "Message": "player", "Player": {"Club": "I7"}})
    time.sleep(0.2)
    assert outcomes(rig) == ["unknown"], "that was not about the shot"
    server.say({"Code": 200, "Message": "ok"})
    assert wait_for(lambda: outcomes(rig) == ["accepted"])
    rig.companion._forward_shot(2, "gspro", swing(Speed=99.0))
    assert len(server.clients) == 1


def test_gspros_late_no_is_kept_too(gspro_rig):
    rig, server = gspro_rig, gspro_rig.server
    rig.companion._forward_shot(1, "gspro", SHOT)
    server.say({"Code": 501, "Message": "not ready"})
    assert wait_for(lambda: outcomes(rig) == ["rejected"])
    assert rig.companion.shots.recent()[0]["delivered"] is False
    assert rig.companion.simulator_status()["ready"] is False


# --- Proof belongs to the connection it was seen on ---------------------------------


def test_being_ready_does_not_survive_a_reconnection(rig, pitrac, ogs):
    pitrac.send(SHOT)
    assert wait_for(lambda: rig.companion.simulator_status()["ready"])
    ogs.on_a_hole = False
    for client in list(ogs.clients):
        client.shutdown(2)
    assert wait_for(lambda: not rig.companion.simulator_status()["connected"])
    assert rig.companion.simulator_status()["ready"] is False
    rig.companion.connect_simulator()
    assert rig.companion.simulator_status()["connected"] is True
    assert rig.companion.simulator_status()["ready"] is False, "nothing has been played since"
    ogs.on_a_hole = True
    pitrac.send(swing(Speed=118.0))
    assert wait_for(lambda: rig.companion.simulator_status()["ready"])


def test_a_result_from_before_is_kept_but_proves_nothing_now(rig, pitrac, ogs):
    ogs.on_a_hole = False
    pitrac.send(SHOT)
    assert wait_for(lambda: outcomes(rig) == ["accepted"])
    before = len(ogs.received)
    rig.companion._session.reconnect()
    # Until it has been heard from, the stand-in does not know whom to tell.
    assert wait_for(lambda: len(ogs.received) > before)
    ogs.finish(ogs.shots[0])
    assert wait_for(lambda: outcomes(rig) == ["played"])
    assert rig.companion.simulator_status()["ready"] is False


def test_an_old_connection_closing_does_not_take_down_the_new_one(ogs):
    session = opengolfsim.OpenGolfSimSession(port=ogs.port)
    try:
        session.connect()
        old = session._sock
        session.reconnect()
        session._drop("the old one noticed", old)
        assert session.connected is True
    finally:
        session.close()


def test_every_connection_is_kept_alive_and_only_by_one(ogs, monkeypatch):
    """A reconnection could find the old reminder still on its way out, and
    start none."""

    monkeypatch.setattr(opengolfsim, "KEEPALIVE_SECONDS", 0.2)
    session = opengolfsim.OpenGolfSimSession(port=ogs.port)
    try:
        session.connect()
        for _ in range(5):
            session.reconnect()
        before = len(ogs.received)
        time.sleep(1.1)
        assert 3 <= len(ogs.received) - before <= 7
    finally:
        session.close()

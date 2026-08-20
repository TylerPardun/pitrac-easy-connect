"""The whole chain, end to end, with nothing stubbed in the middle.

    fake pitrac_lm  ->  Pi relay  ->  authenticated link  ->  Companion  ->  mock GSPro

Every hop in this test is the real class that will run on the hardware. Only the
two ends are stand-ins: a socket pretending to be ``pitrac_lm``, and the mock
simulator that already backs the desktop tests.
"""

import json
import socket
import threading
import time

import pytest

from pitrac_easy_connect.common import link
from pitrac_easy_connect.companion.link_client import CompanionLinkClient
from pitrac_easy_connect.companion.simulator_session import SimulatorSession
from pitrac_easy_connect.mock_simulators import RunningMock
from pitrac_easy_connect.models import TEST_SHOT, Simulator
from pitrac_easy_connect.pi.link_server import CompanionLinkServer
from pitrac_easy_connect.pi.pairing import PairingManager
from pitrac_easy_connect.pi.relay import ShotRelay
from pitrac_easy_connect.protocols import gspro_message

VERSION = "0.2.0"


class Chain:
    """Everything wired together, for the duration of one test."""

    def __init__(self, tmp_path, simulator=Simulator.GSPRO, pair=True):
        self.simulator = simulator
        self.mock = RunningMock(simulator).start()

        self.pairings = PairingManager(tmp_path / "pairings.json", "P3V2PW2U")
        self.relay = ShotRelay(ports={simulator: 0})
        self.relay.start()

        self.server = CompanionLinkServer(
            self.pairings,
            device_info=lambda: {"deviceId": "P3V2PW2U", "displayName": "PiTrac Bay"},
            version=VERSION,
            on_attach=lambda session: self.relay.attach_companion(session.send),
            on_detach=lambda session: self.relay.detach_companion(),
            on_frame=self._on_frame,
            host="127.0.0.1",
            port=0,
        )
        self.link_port = self.server.start()

        self.session = SimulatorSession(
            simulator, *self.mock.address, on_message=self._on_simulator_message
        )
        self.session.connect()

        self.client = None
        self.pairing = None
        if pair:
            self.pair_companion()

    # --- Pi side ----------------------------------------------------------

    def _on_frame(self, session, frame):
        kind = frame.get("type")
        if kind == "simulatorMessage":
            self.relay.handle_simulator_message(frame.get("payload") or {})
        elif kind == "shotResult":
            self.relay.handle_shot_result(frame)

    # --- Companion side ---------------------------------------------------

    def _on_simulator_message(self, payload):
        if self.client is not None:
            self.client.send_simulator_message(payload)

    def _on_shot(self, sequence, simulator, payload):
        try:
            self.session.send(payload)
        except OSError as exc:
            return {"accepted": False, "message": str(exc), "code": "PT-SIM-001"}
        return {"accepted": True, "message": "sent to the simulator"}

    def pair_companion(self, wait=True):
        code = self.pairings.issue_code().code
        self.pairing = self.pairings.redeem(code, "Sim Room PC")
        self.client = CompanionLinkClient(
            "127.0.0.1",
            self.link_port,
            self.pairing.pairing_id,
            self.pairing.secret,
            VERSION,
            "Sim Room PC",
            on_shot=self._on_shot,
            reconnect_seconds=0.05,
        )
        self.client.start()
        if wait:
            assert self.client.wait_until_connected(5), "the Companion never connected"
            _wait_for(lambda: self.relay.companion_attached, "the relay never saw the Companion")
        return self.client

    # --- The fake launch monitor -----------------------------------------

    def pitrac_socket(self):
        sock = socket.create_connection(("127.0.0.1", self.relay.ports[self.simulator]), timeout=5)
        sock.settimeout(5)
        return sock

    def close(self):
        for closer in (
            lambda: self.client.stop() if self.client else None,
            self.session.close,
            self.server.stop,
            self.relay.stop,
            self.mock.stop,
        ):
            try:
                closer()
            except Exception:
                pass


def _wait_for(predicate, message, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(message)


def _read_json(sock, timeout=5.0):
    sock.settimeout(timeout)
    decoder = json.JSONDecoder()
    buffer = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buffer += chunk.decode("utf-8")
        try:
            value, _consumed = decoder.raw_decode(buffer.lstrip())
            return value
        except ValueError:
            continue
    raise AssertionError("PiTrac never received a reply")


@pytest.fixture
def chain(tmp_path):
    built = Chain(tmp_path)
    yield built
    built.close()


# --- The path that has to work -------------------------------------------


def test_a_shot_travels_from_pitrac_to_the_simulator_and_the_reply_comes_back(chain):
    sock = chain.pitrac_socket()
    sock.sendall(json.dumps(gspro_message(TEST_SHOT, shot_number=1)).encode("utf-8"))

    reply = _read_json(sock)
    assert reply["Code"] == 200, "PiTrac must receive the simulator's own reply"

    _wait_for(lambda: chain.mock.received, "the simulator never received the shot")
    delivered = chain.mock.received[0]
    assert delivered["BallData"]["Speed"] == TEST_SHOT.speed_mph
    assert delivered["BallData"]["VLA"] == TEST_SHOT.vertical_launch_deg
    sock.close()


def test_the_shot_arrives_at_the_simulator_byte_for_byte(chain):
    original = gspro_message(TEST_SHOT, shot_number=42)
    sock = chain.pitrac_socket()
    sock.sendall(json.dumps(original).encode("utf-8"))
    _read_json(sock)

    _wait_for(lambda: chain.mock.received, "nothing arrived")
    assert chain.mock.received[0] == original, "the relay must not rewrite PiTrac's message"
    sock.close()


def test_several_shots_keep_their_order(chain):
    sock = chain.pitrac_socket()
    for number in range(1, 6):
        sock.sendall(json.dumps(gspro_message(TEST_SHOT, shot_number=number)).encode("utf-8"))
        _read_json(sock)

    _wait_for(lambda: len(chain.mock.received) == 5, "not every shot arrived")
    assert [item["ShotNumber"] for item in chain.mock.received] == [1, 2, 3, 4, 5]
    sock.close()


def test_two_shots_sent_in_one_packet_are_both_delivered(chain):
    # PiTrac does not delimit its messages, so two can share a single read.
    first = json.dumps(gspro_message(TEST_SHOT, shot_number=1))
    second = json.dumps(gspro_message(TEST_SHOT, shot_number=2))
    sock = chain.pitrac_socket()
    sock.sendall((first + second).encode("utf-8"))

    _wait_for(lambda: len(chain.mock.received) == 2, "the second shot was swallowed")
    assert [item["ShotNumber"] for item in chain.mock.received] == [1, 2]
    sock.close()


# --- When the PC is not there --------------------------------------------


def test_a_shot_with_no_companion_fails_honestly_instead_of_pretending(tmp_path):
    chain = Chain(tmp_path, pair=False)
    try:
        sock = chain.pitrac_socket()
        sock.sendall(json.dumps(gspro_message(TEST_SHOT)).encode("utf-8"))

        reply = _read_json(sock)
        assert reply["Code"] != 200, "a shot nobody received must never look accepted"
        assert "not connected" in reply["Message"].lower()
        assert chain.mock.received == []
        sock.close()
    finally:
        chain.close()


def test_a_shot_is_not_replayed_when_the_computer_comes_back(tmp_path):
    # Re-sending a shot minutes later would score a stroke the player did not
    # just hit, which is worse than losing it.
    chain = Chain(tmp_path, pair=False)
    try:
        sock = chain.pitrac_socket()
        sock.sendall(json.dumps(gspro_message(TEST_SHOT)).encode("utf-8"))
        _read_json(sock)

        chain.pair_companion()
        time.sleep(0.4)
        assert chain.mock.received == [], "the missed shot must stay missed"
        sock.close()
    finally:
        chain.close()


def test_losing_the_simulator_is_reported_and_does_not_kill_the_link(chain):
    chain.session.close()
    chain.mock.stop()

    sock = chain.pitrac_socket()
    sock.sendall(json.dumps(gspro_message(TEST_SHOT)).encode("utf-8"))
    reply = _read_json(sock)
    assert reply["Code"] != 200
    assert chain.client.connected is True, "the enclosure link must survive a simulator outage"
    sock.close()


# --- Authentication -------------------------------------------------------


def test_an_unpaired_computer_is_refused(tmp_path):
    chain = Chain(tmp_path, pair=False)
    try:
        sock = socket.create_connection(("127.0.0.1", chain.link_port), timeout=5)
        stream = link.FrameStream(sock)
        hello = stream.receive(timeout=5)
        assert hello["type"] == "hello"

        stream.send(link.auth("made-up-id", "0" * 64, VERSION, "Intruder PC"))
        reply = stream.receive(timeout=5)
        assert reply["type"] == "error"
        assert reply["error"]["code"] == "PT-PAIR-004"
        stream.close()
    finally:
        chain.close()


def test_a_wrong_secret_is_refused(tmp_path):
    chain = Chain(tmp_path, pair=False)
    try:
        pairing = chain.pairings.redeem(chain.pairings.issue_code().code, "Real PC")
        sock = socket.create_connection(("127.0.0.1", chain.link_port), timeout=5)
        stream = link.FrameStream(sock)
        hello = stream.receive(timeout=5)

        wrong = PairingManager.client_proof("not-the-secret", hello["challenge"])
        stream.send(link.auth(pairing.pairing_id, wrong, VERSION, "Impostor"))
        assert stream.receive(timeout=5)["error"]["code"] == "PT-PAIR-004"
        stream.close()
    finally:
        chain.close()


def test_a_revoked_computer_cannot_reconnect(chain):
    chain.pairings.revoke(chain.pairing.pairing_id)
    chain.client.stop()

    sock = socket.create_connection(("127.0.0.1", chain.link_port), timeout=5)
    stream = link.FrameStream(sock)
    hello = stream.receive(timeout=5)
    proof = PairingManager.client_proof(chain.pairing.secret, hello["challenge"])
    stream.send(link.auth(chain.pairing.pairing_id, proof, VERSION, "Sim Room PC"))
    # Specifically "your access was removed", not "who are you" — the revoked
    # computer's owner needs to know which of those happened.
    assert stream.receive(timeout=5)["error"]["code"] == "PT-PAIR-005"
    stream.close()


def test_the_enclosure_proves_itself_to_the_computer(chain):
    # A device answering on the right address that cannot produce the server
    # proof must be refused, or shots could be sent to the wrong machine.
    assert chain.client.connected is True
    assert chain.client.device["deviceId"] == "P3V2PW2U"


def test_a_second_computer_is_told_the_enclosure_is_busy(chain):
    second = chain.pairings.redeem(chain.pairings.issue_code().code, "Kitchen laptop")
    sock = socket.create_connection(("127.0.0.1", chain.link_port), timeout=5)
    stream = link.FrameStream(sock)
    hello = stream.receive(timeout=5)
    proof = PairingManager.client_proof(second.secret, hello["challenge"])
    stream.send(link.auth(second.pairing_id, proof, VERSION, "Kitchen laptop"))

    reply = stream.receive(timeout=5)
    assert reply["type"] == "error"
    assert reply["error"]["code"] == "PT-LINK-004"
    stream.close()


def test_a_protocol_mismatch_names_the_side_that_must_be_updated(tmp_path):
    chain = Chain(tmp_path, pair=False)
    try:
        pairing = chain.pairings.redeem(chain.pairings.issue_code().code, "Old PC")
        sock = socket.create_connection(("127.0.0.1", chain.link_port), timeout=5)
        stream = link.FrameStream(sock)
        hello = stream.receive(timeout=5)

        frame = link.auth(
            pairing.pairing_id,
            PairingManager.client_proof(pairing.secret, hello["challenge"]),
            "0.0.1",
            "Old PC",
        )
        frame["protocol"] = link.PROTOCOL_VERSION - 1
        stream.send(frame)
        assert stream.receive(timeout=5)["error"]["code"] == "PT-LINK-003"
        stream.close()
    finally:
        chain.close()


# --- Reconnection ---------------------------------------------------------


def test_the_companion_reconnects_after_the_enclosure_restarts(chain):
    assert chain.client.connected is True
    old_session = chain.server.session
    old_session.close()

    # Wait for a genuinely new session, not merely for the flag to be set. The
    # dying session is still attached for a few tens of milliseconds after the
    # socket closes, so "attached" alone would be satisfied by the old one.
    _wait_for(
        lambda: chain.server.session is not None
        and chain.server.session is not old_session
        and chain.relay.companion_attached,
        "the Companion never came back",
        timeout=10,
    )
    _wait_for(lambda: chain.client.connected, "the client never reported connected", timeout=10)

    sock = chain.pitrac_socket()
    sock.sendall(json.dumps(gspro_message(TEST_SHOT)).encode("utf-8"))
    assert _read_json(sock)["Code"] == 200, "shots must flow again after a reconnect"
    sock.close()


def test_a_shot_during_the_reconnect_gap_is_reported_lost_not_queued(chain):
    # There is a short window while the Companion reconnects when no computer is
    # attached. A shot in that window must fail immediately rather than be held
    # and replayed into a hole the player has already finished.
    chain.client.stop()
    _wait_for(lambda: not chain.relay.companion_attached, "the relay never detached")

    sock = chain.pitrac_socket()
    sock.sendall(json.dumps(gspro_message(TEST_SHOT)).encode("utf-8"))
    assert _read_json(sock)["Code"] == 501
    delivered_before = len(chain.mock.received)

    chain.pair_companion()
    time.sleep(0.5)
    assert len(chain.mock.received) == delivered_before, "the lost shot must not arrive late"
    sock.close()


def test_a_garbage_frame_does_not_bring_the_link_down(chain):
    sock = socket.create_connection(("127.0.0.1", chain.link_port), timeout=5)
    sock.sendall(b"this is not a frame\n")
    sock.close()

    time.sleep(0.2)
    assert chain.client.connected is True


# --- E6, which needs four messages per shot -------------------------------


@pytest.fixture
def e6_chain(tmp_path):
    built = Chain(tmp_path, simulator=Simulator.E6)
    yield built
    built.close()


def test_the_full_e6_sequence_travels_and_is_accepted(e6_chain):
    """PiTrac's real E6 conversation: handshake, ball, club, then send."""
    sock = e6_chain.pitrac_socket()

    sock.sendall(json.dumps({"Type": "Handshake"}).encode("utf-8"))
    assert _read_json(sock)["Type"] in {"Handshake", "HandshakeAck"}

    sock.sendall(json.dumps({
        "Type": "SetBallData",
        "BallData": {"BackSpin": 2604, "BallSpeed": 148.3, "LaunchAngle": 12.9,
                     "LaunchDirection": 0.8, "SideSpin": -186},
    }).encode("utf-8"))
    sock.sendall(json.dumps({"Type": "SetClubData", "ClubData": {"ClubHeadSpeed": 0.0}}).encode("utf-8"))
    sock.sendall(json.dumps({"Type": "SendShot"}).encode("utf-8"))

    assert _read_json(sock)["Type"] == "ShotAccepted"
    _wait_for(lambda: len(e6_chain.mock.received) == 4, "the full sequence did not arrive")
    assert [m["Type"] for m in e6_chain.mock.received] == [
        "Handshake", "SetBallData", "SetClubData", "SendShot"
    ]
    sock.close()


def test_one_e6_shot_is_counted_once_not_four_times(e6_chain):
    # PiTrac sends four messages per E6 shot. Counting each one would tell the
    # user they hit four balls.
    sock = e6_chain.pitrac_socket()
    sock.sendall(json.dumps({"Type": "Handshake"}).encode("utf-8"))
    _read_json(sock)
    for message in (
        {"Type": "SetBallData", "BallData": {"BallSpeed": 100}},
        {"Type": "SetClubData", "ClubData": {}},
        {"Type": "SendShot"},
    ):
        sock.sendall(json.dumps(message).encode("utf-8"))
    _read_json(sock)

    _wait_for(lambda: e6_chain.relay.shots_forwarded == 1, "the shot was not counted")
    status = e6_chain.relay.status()
    assert status["shotsForwarded"] == 1
    assert status["messagesForwarded"] == 4
    sock.close()


def test_a_gspro_heartbeat_is_not_counted_as_a_shot(chain):
    sock = chain.pitrac_socket()
    sock.sendall(json.dumps({
        "DeviceID": "PiTrac", "ShotDataOptions": {"ContainsBallData": False, "IsHeartBeat": True},
    }).encode("utf-8"))
    time.sleep(0.4)
    assert chain.relay.shots_forwarded == 0
    assert chain.relay.status()["messagesForwarded"] == 1
    sock.close()


def test_e6_reconnects_and_still_works_after_the_link_drops(e6_chain):
    old_session = e6_chain.server.session
    old_session.close()
    _wait_for(
        lambda: e6_chain.server.session is not None
        and e6_chain.server.session is not old_session
        and e6_chain.relay.companion_attached,
        "the Companion never came back",
        timeout=10,
    )

    sock = e6_chain.pitrac_socket()
    sock.sendall(json.dumps({"Type": "Handshake"}).encode("utf-8"))
    assert _read_json(sock)["Type"] in {"Handshake", "HandshakeAck"}
    sock.close()

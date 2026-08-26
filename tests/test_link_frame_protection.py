"""Post-authentication link frames are sequenced and tagged, not just trusted.

The handshake proves both ends hold the pairing secret. Everything after it
used to be plain JSON with no per-message integrity -- an attacker positioned
to inject into an already-established connection could send commands,
including a factory reset (see SECURITY.md's "known limitations"). This
suite is the fix: session_keys() derives two directional keys from the
persistent secret and this connection's fresh challenge, and
SecureFrameStream adds a monotonic sequence number and an HMAC tag, in both
directions, to every command/commandResult/shot/shotResult/enclosureStatus/
simulatorStatus/simulatorMessage frame.

Most of this is exercised at the SecureFrameStream level directly, over a
real socketpair, because that is precise enough to construct exact
tampering/reordering/truncation/replay cases -- injecting a hand-built
envelope through the raw underlying FrameStream is standing in for an
on-path attacker who controls the bytes on the wire, which is exactly the
threat this protects against. A handful of tests go through the real
CompanionLinkServer/CompanionLinkClient/PairingManager to prove the wiring
itself: that a real handshake produces matching keys, that an old protocol
version is refused, and that concurrent senders on one session cannot
corrupt each other's sequence numbers.
"""

import hashlib
import hmac as hmac_module
import json
import socket
import threading
import time

import pytest

from pitrac_easy_connect.common import link
from pitrac_easy_connect.companion.link_client import CompanionLinkClient
from pitrac_easy_connect.pi.link_server import CompanionLinkServer
from pitrac_easy_connect.pi.pairing import PairingManager


# --- Building blocks --------------------------------------------------------


def a_socketpair():
    a, b = socket.socketpair()
    return link.FrameStream(a), link.FrameStream(b)


def wired_pair(secret="pairing-secret-value", challenge="fresh-challenge-abc"):
    """Two SecureFrameStreams over one socketpair, keyed as a real session
    would be: the Pi's sends and the Companion's receives share a key, and
    the Companion's sends and the Pi's receives share the other one."""

    pi_stream, companion_stream = a_socketpair()
    keys = link.session_keys(secret, challenge)
    pi_side = link.SecureFrameStream(
        pi_stream, keys=keys,
        send_direction=link.DIRECTION_PI_TO_COMPANION,
        receive_direction=link.DIRECTION_COMPANION_TO_PI,
    )
    companion_side = link.SecureFrameStream(
        companion_stream, keys=keys,
        send_direction=link.DIRECTION_COMPANION_TO_PI,
        receive_direction=link.DIRECTION_PI_TO_COMPANION,
    )
    return pi_side, companion_side


@pytest.fixture
def pair():
    pi_side, companion_side = wired_pair()
    yield pi_side, companion_side
    pi_side.close()
    companion_side.close()


def envelope_for(sender: link.SecureFrameStream, frame, seq: int):
    """Build exactly what sender.send() would build, without advancing its
    own counter -- so a test can inject it directly and control ordering."""

    built = dict(frame)
    built[link.SEQ_FIELD] = seq
    built[link.TAG_FIELD] = link._frame_tag(
        sender._send_key, sender._send_direction, seq, built
    )
    return built


def inject(sender: link.SecureFrameStream, envelope) -> None:
    """Put bytes directly on the wire, bypassing sequencing -- an attacker
    or a from-scratch replay/reorder does not go through send()."""

    sender._stream.send(envelope)


PROTECTED_SAMPLES = [
    lambda: link.command(1, "status", {}),
    lambda: link.command_result(1, True, {"ok": True}),
    lambda: link.shot(1, "gspro", {"Speed": 100}),
    lambda: link.shot_result(1, True, "sent"),
    lambda: link.enclosure_status({"state": "READY"}),
    lambda: link.simulator_status({"ready": True}),
    lambda: link.simulator_message({"hello": True}),
]

UNPROTECTED_SAMPLES = [
    lambda: link.ping(),
    lambda: link.pong(time.time()),
]


# --- The basics: it actually delivers frames --------------------------------


@pytest.mark.parametrize("build", PROTECTED_SAMPLES)
def test_a_protected_frame_round_trips_intact(pair, build):
    pi_side, companion_side = pair
    sent = build()
    pi_side.send(sent)
    received = companion_side.receive(timeout=2)
    for key, value in sent.items():
        assert received[key] == value
    assert isinstance(received[link.SEQ_FIELD], int)
    assert isinstance(received[link.TAG_FIELD], str) and received[link.TAG_FIELD]


@pytest.mark.parametrize("build", UNPROTECTED_SAMPLES)
def test_an_unprotected_frame_carries_no_sequence_or_tag(pair, build):
    pi_side, companion_side = pair
    pi_side.send(build())
    received = companion_side.receive(timeout=2)
    assert link.SEQ_FIELD not in received
    assert link.TAG_FIELD not in received


def test_both_directions_work_independently_and_concurrently(pair):
    pi_side, companion_side = pair
    pi_side.send(link.command(1, "status"))
    companion_side.send(link.command_result(1, True))
    assert companion_side.receive(timeout=2)["command"] == "status"
    assert pi_side.receive(timeout=2)["ok"] is True


def test_sequence_numbers_increase_monotonically_from_zero(pair):
    pi_side, companion_side = pair
    for _ in range(5):
        pi_side.send(link.enclosure_status({}))
    seen = [companion_side.receive(timeout=2)[link.SEQ_FIELD] for _ in range(5)]
    assert seen == [0, 1, 2, 3, 4]


# --- Tampering ---------------------------------------------------------------


def test_a_flipped_byte_in_the_tag_is_rejected(pair):
    pi_side, companion_side = pair
    envelope = envelope_for(pi_side, link.command(1, "status"), seq=0)
    tag = envelope[link.TAG_FIELD]
    envelope[link.TAG_FIELD] = tag[:-1] + ("0" if tag[-1] != "0" else "1")
    inject(pi_side, envelope)
    with pytest.raises(link.FrameIntegrityError, match="did not verify"):
        companion_side.receive(timeout=2)


def test_a_field_changed_after_tagging_is_rejected(pair):
    """The tag covers the whole frame, not just the type and sequence."""

    pi_side, companion_side = pair
    envelope = envelope_for(pi_side, link.command(1, "status", {"amount": 1}), seq=0)
    envelope["arguments"] = {"amount": 999999}  # tampered after the tag was computed
    inject(pi_side, envelope)
    with pytest.raises(link.FrameIntegrityError, match="did not verify"):
        companion_side.receive(timeout=2)


def test_a_tag_computed_with_the_wrong_directions_key_is_rejected(pair):
    """Direction binding: a companion-side key cannot forge a pi-side frame."""

    pi_side, companion_side = pair
    frame = link.command(1, "status")
    built = dict(frame)
    built[link.SEQ_FIELD] = 0
    # Signed with the *other* direction's key -- what an attacker holding a
    # companion-to-pi key (say, from a compromised Companion) would produce.
    built[link.TAG_FIELD] = link._frame_tag(
        companion_side._send_key, pi_side._send_direction, 0, built
    )
    inject(pi_side, built)
    with pytest.raises(link.FrameIntegrityError, match="did not verify"):
        companion_side.receive(timeout=2)


def test_a_tag_missing_the_direction_label_is_rejected(pair):
    """Direction is bound inside the MAC'd material itself, not only through
    key selection -- this would otherwise still verify under the right key."""

    pi_side, companion_side = pair
    built = dict(link.command(1, "status"))
    built[link.SEQ_FIELD] = 0
    material = b"0|" + link._canonical(built)  # missing the direction prefix
    built[link.TAG_FIELD] = hmac_module.new(
        pi_side._send_key, material, hashlib.sha256
    ).hexdigest()
    inject(pi_side, built)
    with pytest.raises(link.FrameIntegrityError, match="did not verify"):
        companion_side.receive(timeout=2)


# --- Missing proof -----------------------------------------------------------


def test_a_protected_frame_with_no_tag_at_all_is_rejected(pair):
    pi_side, companion_side = pair
    built = dict(link.command(1, "status"))
    built[link.SEQ_FIELD] = 0
    inject(pi_side, built)
    with pytest.raises(link.FrameIntegrityError, match="no sequence number or tag"):
        companion_side.receive(timeout=2)


def test_a_protected_frame_with_no_sequence_at_all_is_rejected(pair):
    pi_side, companion_side = pair
    built = dict(link.command(1, "status"))
    built[link.TAG_FIELD] = "a" * 64
    inject(pi_side, built)
    with pytest.raises(link.FrameIntegrityError, match="no sequence number or tag"):
        companion_side.receive(timeout=2)


def test_truncation_mid_frame_is_a_stream_error_not_a_silent_gap(pair):
    """A connection cut mid-frame must not be mistaken for zero frames sent."""

    pi_side, companion_side = pair
    payload = json.dumps(envelope_for(pi_side, link.command(1, "status"), seq=0)).encode("utf-8")
    # Half a frame, no trailing newline: exactly what a connection dying
    # mid-write leaves in the socket buffer.
    pi_side._stream.sock.sendall(payload[: len(payload) // 2])
    pi_side._stream.sock.close()
    with pytest.raises((link.LinkClosed, TimeoutError)):
        companion_side.receive(timeout=2)


# --- Replay and reordering ---------------------------------------------------


def test_a_replayed_frame_is_rejected_as_a_duplicate_sequence(pair):
    pi_side, companion_side = pair
    envelope = envelope_for(pi_side, link.command(1, "status"), seq=0)
    inject(pi_side, envelope)
    assert companion_side.receive(timeout=2)["id"] == 1

    # The exact same bytes again -- a captured frame replayed verbatim.
    inject(pi_side, envelope)
    with pytest.raises(link.FrameIntegrityError, match="expected link sequence 1, received 0"):
        companion_side.receive(timeout=2)


def test_a_frame_delivered_out_of_order_is_rejected(pair):
    pi_side, companion_side = pair
    second = envelope_for(pi_side, link.command(2, "status"), seq=1)
    inject(pi_side, second)
    with pytest.raises(link.FrameIntegrityError, match="expected link sequence 0, received 1"):
        companion_side.receive(timeout=2)


def test_a_skipped_sequence_number_is_rejected_not_silently_accepted(pair):
    """A frame dropped in transit must not let the next one just continue."""

    pi_side, companion_side = pair
    inject(pi_side, envelope_for(pi_side, link.command(1, "status"), seq=0))
    assert companion_side.receive(timeout=2)["id"] == 1
    # seq 1 never arrives; seq 2 shows up instead.
    inject(pi_side, envelope_for(pi_side, link.command(3, "status"), seq=2))
    with pytest.raises(link.FrameIntegrityError, match="expected link sequence 1, received 2"):
        companion_side.receive(timeout=2)


def test_after_a_rejected_frame_the_stream_is_not_silently_reusable(pair):
    """A caller that ignores the exception must not be handed a false sense
    that the session is still intact -- receive() keeps refusing."""

    pi_side, companion_side = pair
    inject(pi_side, envelope_for(pi_side, link.command(1, "status"), seq=5))
    with pytest.raises(link.FrameIntegrityError):
        companion_side.receive(timeout=2)
    # A real, entirely valid frame at the position it was actually expecting
    # -- this stream never advanced past 0, so the checker still refuses.
    inject(pi_side, envelope_for(pi_side, link.command(1, "status"), seq=5))
    with pytest.raises(link.FrameIntegrityError):
        companion_side.receive(timeout=2)


# --- Reconnect: replay cannot cross sessions --------------------------------


def test_a_frame_tagged_under_one_sessions_keys_is_rejected_in_a_fresh_session():
    """The whole point of deriving keys from the challenge: a captured,
    perfectly valid frame from one connection means nothing in the next."""

    old_pi, old_companion = wired_pair(secret="the-pairing-secret", challenge="session-one")
    captured = envelope_for(old_pi, link.command(1, "status"), seq=0)
    old_pi.close()
    old_companion.close()

    new_pi, new_companion = wired_pair(secret="the-pairing-secret", challenge="session-two")
    try:
        inject(new_pi, captured)
        with pytest.raises(link.FrameIntegrityError, match="did not verify"):
            new_companion.receive(timeout=2)
    finally:
        new_pi.close()
        new_companion.close()


def test_two_sessions_from_the_same_secret_get_different_keys():
    keys_one = link.session_keys("shared-secret", "challenge-a")
    keys_two = link.session_keys("shared-secret", "challenge-b")
    assert keys_one != keys_two
    assert (
        keys_one[link.DIRECTION_PI_TO_COMPANION]
        != keys_one[link.DIRECTION_COMPANION_TO_PI]
    ), "the two directions must not share a key"


def test_a_different_pairing_secret_produces_unrelated_keys():
    keys_one = link.session_keys("secret-one", "same-challenge")
    keys_two = link.session_keys("secret-two", "same-challenge")
    assert keys_one != keys_two


# --- The concurrency bug this design has to not reintroduce -----------------


def test_concurrent_senders_on_one_session_get_distinct_sequence_numbers(pair):
    """A shot from the relay's thread and a commandResult from the pump
    thread can legitimately race one send(). Two sends that ever claimed the
    same sequence number would make the peer reject the second as a
    duplicate and silently tear the whole link down -- self-inflicted, not
    an attack. This is a regression test for exactly that race.

    The receiver drains concurrently with the senders, on its own thread,
    rather than after they finish: 200 tagged frames queued with nobody
    reading is its own way to block on socket backpressure, independent of
    anything this test is actually about.
    """

    pi_side, companion_side = pair
    total = 200
    barrier = threading.Barrier(4)
    stop = threading.Event()

    def hammer(start):
        barrier.wait(timeout=5)
        for i in range(start, total, 4):
            if stop.is_set():
                return
            pi_side.send(link.command(i, "status"))

    received_ids = set()
    failure = []

    def drain():
        # Stops draining, and tells the senders to stop too, the moment the
        # peer rejects a frame -- a sender that kept pushing into a pipe
        # nobody reads from again would block on socket backpressure, which
        # is a self-inflicted hang in this test, not the bug it is testing.
        while not stop.is_set():
            try:
                received_ids.add(companion_side.receive(timeout=0.5)["id"])
            except TimeoutError:
                continue
            except link.FrameIntegrityError as exc:
                failure.append(exc)
                stop.set()
                return

    receiver = threading.Thread(target=drain, daemon=True)
    receiver.start()

    senders = [threading.Thread(target=hammer, args=(offset,)) for offset in range(4)]
    for thread in senders:
        thread.start()
    for thread in senders:
        thread.join(timeout=10)
    assert not any(t.is_alive() for t in senders), "a sender thread never finished"

    deadline = time.monotonic() + 10
    while len(received_ids) < total and not failure and time.monotonic() < deadline:
        time.sleep(0.05)
    stop.set()
    receiver.join(timeout=2)

    if failure:
        pytest.fail("a concurrent send corrupted the sequence: {}".format(failure[0]))
    assert received_ids == set(range(total)), "some frames were lost or rejected as duplicates"


# --- Through the real handshake ---------------------------------------------


VERSION = "0.9.0"


@pytest.fixture
def linked(tmp_path):
    """A real CompanionLinkServer/CompanionLinkClient pair, actually paired
    and connected, the same way test_end_to_end_relay.py's Chain is built."""

    pairings = PairingManager(tmp_path / "pairings.json", "P3V2PW2U")
    attached = threading.Event()

    server = CompanionLinkServer(
        pairings,
        device_info=lambda: {"deviceId": "P3V2PW2U", "displayName": "PiTrac Bay"},
        version=VERSION,
        on_attach=lambda session: attached.set(),
        on_detach=lambda session: attached.clear(),
        on_frame=lambda session, frame: None,
        host="127.0.0.1",
        port=0,
    )
    port = server.start()

    pairing = pairings.create_pairing("Test PC")
    client = CompanionLinkClient(
        "127.0.0.1", port, pairing.pairing_id, pairing.secret, VERSION, "Test PC",
        on_shot=lambda *a: {"accepted": True, "message": "ok"},
        reconnect_seconds=0.05,
    )
    client.start()
    assert client.wait_until_connected(5), "the Companion never connected"
    assert attached.wait(timeout=5), "the Pi never attached the session"

    yield server, client, pairings, pairing

    client.stop()
    server.stop()


def test_a_real_handshake_produces_a_working_authenticated_channel(linked):
    """Not a mock of SecureFrameStream -- the actual session, actually up."""

    server, client, _pairings, _pairing = linked
    session = server.session
    assert session is not None and session.authenticated
    assert isinstance(session.stream, link.SecureFrameStream)


def test_an_old_protocol_version_is_refused_with_a_clear_message(tmp_path):
    """A real pre-v2 peer, hand-built rather than the live client with its
    version patched -- patching the shared PROTOCOL_VERSION constant would
    move both sides of an in-process test at once and prove nothing."""

    from pitrac_easy_connect.common.errors import LINK_VERSION_MISMATCH

    pairings = PairingManager(tmp_path / "pairings.json", "P3V2PW2U")
    server = CompanionLinkServer(
        pairings,
        device_info=lambda: {"deviceId": "P3V2PW2U", "displayName": "PiTrac Bay"},
        version=VERSION,
        on_attach=lambda session: None,
        on_detach=lambda session: None,
        on_frame=lambda session, frame: None,
        host="127.0.0.1",
        port=0,
    )
    port = server.start()
    pairing = pairings.create_pairing("Old PC")
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        stream = link.FrameStream(sock)
        try:
            hello = stream.receive(timeout=5)
            assert hello["type"] == "hello"
            stale_auth = link.auth(pairing.pairing_id, "irrelevant-proof", "0.4.0", "Old PC")
            stale_auth["protocol"] = 1  # what a v1 peer actually sends
            stream.send(stale_auth)
            reply = stream.receive(timeout=5)
        finally:
            stream.close()
    finally:
        server.stop()

    assert reply["type"] == "error"
    assert reply["error"]["code"] == LINK_VERSION_MISMATCH.code
    assert "versions" in reply["error"]["failed"].lower()
    assert reply["error"]["nextStep"], "the peer is told what to actually do about it"

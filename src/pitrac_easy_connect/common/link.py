"""The wire between the enclosure and the Windows PC.

Frames are one JSON object per line. Line framing is used rather than the
length-prefixed scheme because it is trivially inspectable when something goes
wrong on someone else's home network at ten at night.

**The Companion dials out to the enclosure, never the other way round.** That
choice is what keeps the Windows side free of firewall configuration: Windows
permits outbound connections by default and blocks inbound ones, and a beginner
must never be asked to add a firewall rule. It also means the PC's address can
change freely, because nothing on the Pi ever needs to know it.

The handshake proves both directions before anything else is allowed:

    Pi        -> hello    (protocol version, device identity, random challenge)
    Companion -> auth     (pairing id, HMAC of the challenge, its own version)
    Pi        -> authOk   (its own HMAC, proving it holds the same secret)

An eavesdropper on the LAN sees only challenges and HMACs, and an old exchange
cannot be replayed because the challenge is fresh every time.
"""

import hmac
import json
import re

from . import jsontext
import socket
import threading
import time
from hashlib import sha256
from typing import Any, Callable, Dict, Optional, Tuple

#: Bumped when a frame's meaning changes in a way an older peer would
#: misinterpret. Mismatches produce PT-LINK-003, which names the side to update.
#:
#: Bumped to 2 for per-frame sequence numbers and HMAC tags on
#: command/commandResult/shot/shotResult/enclosureStatus/simulatorStatus/
#: simulatorMessage -- see SecureFrameStream. A v1 peer does not send or check
#: either field, so letting a v1 peer through unprotected would be silent, not
#: refused; check_protocol() refuses the mismatch outright instead.
PROTOCOL_VERSION = 2

#: The Companion connects here. Chosen above 1024 so the service never needs to
#: bind a privileged port.
LINK_PORT = 39877

#: A frame is small. Anything larger is a bug or an attack, not a golf shot.
MAX_FRAME_BYTES = 256 * 1024


class LinkError(RuntimeError):
    pass


class LinkClosed(LinkError):
    pass


class TerminalLinkError(LinkError):
    """A link failure that unchanged credentials cannot recover from.

    Raised instead of a bare LinkError so the reconnect loop can stop
    retrying immediately rather than hammering the enclosure every few
    seconds with the same rejected pairing id.
    """

    def __init__(self, info: Dict[str, Any]):
        super().__init__(info.get("failed", "PiTrac refused the connection"))
        self.info = dict(info)


class FrameIntegrityError(LinkError):
    """A protected frame was missing its proof, out of order, or tampered.

    Deliberately a LinkError subclass: every existing ``except (LinkClosed,
    LinkError)`` around a pump loop already tears the connection down on one
    of these without being told anything new. The one thing this type adds
    is that a caller who wants to distinguish "the network went away" from
    "someone is interfering with an authenticated session" can.
    """


#: Frame types exchanged only before a session's directional keys exist
#: (the handshake itself) or that carry no state-changing meaning (a bare
#: liveness check). Everything else that crosses an authenticated session --
#: command, commandResult, shot, shotResult, enclosureStatus,
#: simulatorStatus, simulatorMessage -- is sequenced and tagged.
UNPROTECTED_TYPES = {"hello", "auth", "authOk", "error", "ping", "pong"}

#: The field names carrying the sequence number and HMAC tag on a protected
#: frame. Deliberately not named "sequence": shot() and shotResult() already
#: use that field for the application-level golf-shot ordering PiTrac and the
#: simulator agree on, which is a different number with a different meaning.
SEQ_FIELD = "linkSeq"
TAG_FIELD = "linkTag"

#: Domain-separation labels. Used both to derive two independent directional
#: keys from one shared base key and, again, inside every tag's own MAC'd
#: material -- so a frame tagged for one direction cannot verify in the
#: other even if a key were ever mixed up, not only because the keys differ.
DIRECTION_PI_TO_COMPANION = "pi->companion"
DIRECTION_COMPANION_TO_PI = "companion->pi"


def session_keys(secret: str, challenge: str) -> Dict[str, bytes]:
    """Two directional session keys, fresh for one connection.

    Derived from the long-lived pairing secret and this connection's
    handshake challenge, which is why a session's keys are useless for
    replaying a frame into any *other* session: every connection gets a
    fresh challenge (``PairingManager.new_challenge``), so it gets fresh
    keys, and a tag computed under an old connection's key does not verify
    under a new one's.
    """

    base = hmac.new(
        secret.encode("utf-8"), ("link-session|" + str(challenge)).encode("utf-8"), sha256
    ).digest()
    return {
        DIRECTION_PI_TO_COMPANION: hmac.new(
            base, DIRECTION_PI_TO_COMPANION.encode("utf-8"), sha256
        ).digest(),
        DIRECTION_COMPANION_TO_PI: hmac.new(
            base, DIRECTION_COMPANION_TO_PI.encode("utf-8"), sha256
        ).digest(),
    }


def _canonical(frame: Dict[str, Any]) -> bytes:
    """The exact bytes a tag covers, independent of dict insertion order."""

    return json.dumps(frame, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _frame_tag(key: bytes, direction: str, seq: int, frame_with_seq: Dict[str, Any]) -> str:
    material = "{}|{}|".format(direction, seq).encode("utf-8") + _canonical(frame_with_seq)
    return hmac.new(key, material, sha256).hexdigest()


class FrameStream:
    """Newline-delimited JSON over one socket, safe for one reader and one writer."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._buffer = bytearray()
        self._write_lock = threading.Lock()

    def send(self, frame: Dict[str, Any]) -> None:
        payload = json.dumps(frame, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_FRAME_BYTES:
            raise LinkError("frame is too large to send")
        with self._write_lock:
            try:
                self.sock.sendall(payload + b"\n")
            except OSError as exc:
                raise LinkClosed("the connection was lost while sending") from exc

    def receive(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                # Checked before decoding. The buffer limit below only catches
                # a frame with no newline yet, so a single oversized line that
                # arrived complete slipped past it.
                if newline > MAX_FRAME_BYTES:
                    raise LinkError("the other side sent an oversized frame")
                line = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                if not line.strip():
                    continue
                return _decode(line)

            if len(self._buffer) > MAX_FRAME_BYTES:
                raise LinkError("the other side sent an oversized frame")

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("no frame arrived before the timeout")
                self.sock.settimeout(remaining)
            else:
                self.sock.settimeout(None)

            try:
                chunk = self.sock.recv(65536)
            except socket.timeout as exc:
                raise TimeoutError("no frame arrived before the timeout") from exc
            except OSError as exc:
                raise LinkClosed("the connection was lost while receiving") from exc
            if not chunk:
                raise LinkClosed("the other side closed the connection")
            self._buffer.extend(chunk)

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class SecureFrameStream:
    """Wraps an authenticated FrameStream: sequence numbers and HMAC tags on
    every protected frame, in both directions, using session_keys().

    Constructed once per connection, right after the handshake proves the
    pairing and the fresh challenge is known -- never before, because the
    keys do not exist yet, and never reused across a reconnect, because a
    new connection gets a new challenge and therefore new keys.

    ``send_direction``/``receive_direction`` are the two session_keys()
    labels: the Pi passes (PI_TO_COMPANION, COMPANION_TO_PI), the Companion
    passes the reverse. Getting them backwards is a same-session,
    fail-closed bug -- the first frame in the wrong direction would fail its
    own tag check -- not a silent cross-wire.
    """

    def __init__(self, stream: FrameStream, *, keys: Dict[str, bytes],
                send_direction: str, receive_direction: str):
        self._stream = stream
        self._send_key = keys[send_direction]
        self._receive_key = keys[receive_direction]
        self._send_direction = send_direction
        self._receive_direction = receive_direction
        self._send_seq = 0
        self._expected_receive_seq = 0
        # A shot from the relay's thread and a commandResult from the pump
        # thread can both be in flight for one session at once. Without this,
        # two sends racing the same counter can both claim sequence N -- the
        # peer would then reject the second as a duplicate and tear the link
        # down, exactly the kind of self-inflicted "tampering" this exists to
        # rule out. receive() needs no such lock: exactly one thread ever
        # reads from a given direction (the pump loop that owns this stream).
        self._send_lock = threading.Lock()

    def send(self, frame: Dict[str, Any]) -> None:
        if frame.get("type") in UNPROTECTED_TYPES:
            self._stream.send(frame)
            return
        with self._send_lock:
            seq = self._send_seq
            envelope = dict(frame)
            envelope[SEQ_FIELD] = seq
            envelope[TAG_FIELD] = _frame_tag(self._send_key, self._send_direction, seq, envelope)
            self._stream.send(envelope)
            self._send_seq = seq + 1

    def receive(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        frame = self._stream.receive(timeout=timeout)
        if frame.get("type") in UNPROTECTED_TYPES:
            return frame
        self._verify(frame)
        self._expected_receive_seq += 1
        return frame

    def _verify(self, frame: Dict[str, Any]) -> None:
        seq = frame.get(SEQ_FIELD)
        tag = frame.get(TAG_FIELD)
        if not isinstance(seq, int) or not isinstance(tag, str) or not tag:
            raise FrameIntegrityError(
                "a protected frame arrived with no sequence number or tag"
            )
        # One rule catches a missing, duplicated, or reordered frame: each
        # protected frame has exactly one valid position in this direction.
        if seq != self._expected_receive_seq:
            raise FrameIntegrityError(
                "expected link sequence {}, received {}".format(
                    self._expected_receive_seq, seq
                )
            )
        unsigned = {key: value for key, value in frame.items() if key != TAG_FIELD}
        expected = _frame_tag(self._receive_key, self._receive_direction, seq, unsigned)
        if not hmac.compare_digest(expected, tag):
            raise FrameIntegrityError("a protected frame's tag did not verify")

    def close(self) -> None:
        self._stream.close()


def _decode(line: bytes) -> Dict[str, Any]:
    try:
        frame = jsontext.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LinkError("the other side sent something that is not JSON") from exc
    if not isinstance(frame, dict):
        raise LinkError("a frame must be a JSON object")
    if not isinstance(frame.get("type"), str):
        raise LinkError("a frame must name its type")
    return frame


# --- Frame builders -------------------------------------------------------


def hello(device: Dict[str, Any], version: str, challenge: str) -> Dict[str, Any]:
    return {
        "type": "hello",
        "protocol": PROTOCOL_VERSION,
        "version": version,
        "challenge": challenge,
        "device": device,
    }


def auth(
    pairing_id: str, proof: str, version: str, computer_name: str,
    take_over: bool = False, protocol: int = PROTOCOL_VERSION,
) -> Dict[str, Any]:
    """The computer's answer to hello.

    ``take_over`` is the person at this computer choosing it, the way picking a
    remembered device in a Bluetooth list moves the connection to it: PiTrac
    lets go of whichever paired computer it is talking to and takes this one.
    Without it a second paired computer is refused as busy, which is what stops
    two computers that both remember PiTrac from fighting over it on their own.

    ``protocol`` is only ever lowered to talk to an enclosure too old for this
    one, and then only to update it -- see ``LegacyUpdateLink``.
    """

    frame = {
        "type": "auth",
        "protocol": protocol,
        "pairingId": pairing_id,
        "proof": proof,
        "version": version,
        "computerName": computer_name,
    }
    if take_over:
        frame["takeOver"] = True
    return frame


def auth_ok(server_proof: str) -> Dict[str, Any]:
    return {"type": "authOk", "serverProof": server_proof}


def error(code: str, failed: str, next_step: str, still_safe: str = "") -> Dict[str, Any]:
    return {
        "type": "error",
        "error": {
            "code": code,
            "failed": failed,
            "nextStep": next_step,
            "stillSafe": still_safe,
        },
    }


def shot(sequence: int, simulator: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "shot", "sequence": sequence, "simulator": simulator, "payload": payload}


def shot_result(
    sequence: int, accepted: bool, message: str, response: Optional[Dict[str, Any]] = None,
    code: str = "",
) -> Dict[str, Any]:
    frame = {
        "type": "shotResult",
        "sequence": sequence,
        "accepted": bool(accepted),
        "message": message,
    }
    if response is not None:
        frame["response"] = response
    if code:
        frame["code"] = code
    return frame


def simulator_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Something the simulator said, on its way back to PiTrac.

    The relay is a transparent tunnel rather than a request/response call. GSPro
    and E6 each have their own conversational rules — E6 in particular expects a
    handshake and a multi-message shot sequence — and modelling those rules in
    the middle would mean re-implementing them correctly twice. Passing every
    message through in both directions preserves whatever the two ends already
    agree on.
    """

    return {"type": "simulatorMessage", "payload": payload}


def simulator_status(status: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "simulatorStatus", "status": status}


def enclosure_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The enclosure's own view, pushed to the Companion as it changes.

    The enclosure is authoritative about shots: the relay sees every one PiTrac
    sends, including those that never reached the computer at all. Without this,
    the Companion could only count what arrived, and would under-report losses
    to the one person who needs to know about them.
    """

    return {"type": "enclosureStatus", "status": payload}


def command(request_id: int, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"type": "command", "id": request_id, "command": name, "arguments": arguments or {}}


def command_result(
    request_id: int, ok: bool, data: Optional[Dict[str, Any]] = None,
    error_info: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    frame: Dict[str, Any] = {"type": "commandResult", "id": request_id, "ok": bool(ok)}
    if data is not None:
        frame["data"] = data
    if error_info:
        frame["error"] = error_info
    return frame


def ping() -> Dict[str, Any]:
    return {"type": "ping", "at": time.time()}


def pong(at: float) -> Dict[str, Any]:
    return {"type": "pong", "at": at}


def check_protocol(frame: Dict[str, Any]) -> Optional[str]:
    """Return which side is out of date, or ``None`` when the versions agree."""

    theirs = frame.get("protocol")
    if theirs == PROTOCOL_VERSION:
        return None
    if not isinstance(theirs, int):
        return "unknown"
    return "them" if theirs < PROTOCOL_VERSION else "us"


def serve_forever(
    sock: socket.socket, handler: Callable[[Dict[str, Any]], None], stop: threading.Event
) -> None:
    """Read frames until the peer goes away or ``stop`` is set."""

    stream = FrameStream(sock)
    while not stop.is_set():
        try:
            handler(stream.receive(timeout=1.0))
        except TimeoutError:
            continue
        except (LinkClosed, LinkError):
            return


def claim_port(sock) -> None:
    """Take a listening port in a way that means the same on every platform.

    ``SO_REUSEADDR`` does not mean the same thing everywhere. On Linux and macOS
    it lets a new listener take a port left in ``TIME_WAIT`` by a socket that has
    closed — which is what a service wants when it restarts. On Windows it means
    something else entirely: a *second* listener can bind a port another process
    is still using, and it silently takes over the connections.

    That difference matters here. A second copy of the app, or of the enclosure
    service, would quietly steal the port from the copy already running instead
    of failing to start — and the first copy would go on reporting that it was
    listening while nothing reached it.

    Windows spells the behaviour we actually want ``SO_EXCLUSIVEADDRUSE``.
    """

    import socket

    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:  # Windows
        sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

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

import json
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional

#: Bumped when a frame's meaning changes in a way an older peer would
#: misinterpret. Mismatches produce PT-LINK-003, which names the side to update.
PROTOCOL_VERSION = 1

#: The Companion connects here. Chosen above 1024 so the service never needs to
#: bind a privileged port.
LINK_PORT = 39877

#: A frame is small. Anything larger is a bug or an attack, not a golf shot.
MAX_FRAME_BYTES = 256 * 1024


class LinkError(RuntimeError):
    pass


class LinkClosed(LinkError):
    pass


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


def _decode(line: bytes) -> Dict[str, Any]:
    try:
        frame = json.loads(line.decode("utf-8"))
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


def auth(pairing_id: str, proof: str, version: str, computer_name: str) -> Dict[str, Any]:
    return {
        "type": "auth",
        "protocol": PROTOCOL_VERSION,
        "pairingId": pairing_id,
        "proof": proof,
        "version": version,
        "computerName": computer_name,
    }


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

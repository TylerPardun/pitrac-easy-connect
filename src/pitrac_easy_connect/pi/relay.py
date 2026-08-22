"""Carrying shots from PiTrac on the Pi to the simulator on the Windows PC.

``pitrac_lm`` is a TCP client: it dials out to whatever address is configured as
the simulator. Easy Connect points it at ``127.0.0.1`` and its own ports once, at
install time, and then stands in for the simulator. Moving house never changes
PiTrac's configuration again, and a new DHCP lease on the PC cannot silently
break shot delivery.

What travels over the link is the simulator's own protocol, untouched, in both
directions. This module does not interpret GSPro or E6 messages; it counts them
and passes them on.

**Shots are never retried.** If the link is down when a shot arrives, it fails
immediately and says so. Re-sending a golf shot once the PC comes back would
score a stroke the player did not just hit, which is worse than losing it.
"""

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ..common import link
from ..common.link import claim_port
from ..models import Simulator

#: Where ``pitrac_lm`` is told to find its simulator. Above 1024 so the service
#: never needs a privileged port, and distinct per simulator so the relay always
#: knows which protocol is in play.
DEFAULT_RELAY_PORTS = {Simulator.GSPRO: 9210, Simulator.E6: 9248}

RELAY_HOST = "127.0.0.1"

#: How often an accept loop checks whether it has been asked to stop.
ACCEPT_POLL_SECONDS = 0.2

#: How long a forwarded shot may wait for the Companion to say what happened to
#: it. A Companion that is connected but wedged would otherwise leave PiTrac
#: waiting for a reply forever, and leave a record behind for every shot.
SHOT_ACK_SECONDS = 15.0


@dataclass
class ShotRecord:
    sequence: int
    simulator: str
    at: float
    delivered: bool = False
    message: str = ""
    #: Whether this message completes a shot, as opposed to being one step of a
    #: multi-message sequence. Only these are counted for the user.
    is_shot: bool = True
    #: Monotonic deadline for the Companion's answer. Wall-clock time is not
    #: used because it can jump when the Pi first syncs its clock.
    deadline: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "simulator": self.simulator,
            "at": self.at,
            "delivered": self.delivered,
            "message": self.message,
            "isShot": self.is_shot,
        }


class _PitracConnection:
    """One open socket from ``pitrac_lm``."""

    def __init__(self, sock: socket.socket, simulator: Simulator):
        self.sock = sock
        self.simulator = simulator
        self._lock = threading.Lock()

    def send(self, message: Dict[str, Any]) -> None:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        with self._lock:
            self.sock.sendall(payload)

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def is_shot_message(simulator: Simulator, message: Dict[str, Any]) -> bool:
    """Whether this message is the one that puts a ball in the air.

    GSPro carries a whole shot in one message. E6 needs four — a handshake, ball
    data, club data, and finally SendShot — so counting every message would tell
    the user they hit four times as many balls as they did.
    """

    if simulator is Simulator.GSPRO:
        options = message.get("ShotDataOptions")
        if not isinstance(options, dict):
            return bool(message.get("BallData"))
        if options.get("IsHeartBeat"):
            return False
        return bool(options.get("ContainsBallData")) or bool(message.get("BallData"))
    return message.get("Type") == "SendShot"


def unavailable_reply(simulator: Simulator, reason: str) -> Dict[str, Any]:
    """A refusal in the shape the simulator would have used.

    PiTrac believes it is talking to GSPro or E6, so an honest failure has to
    arrive in their vocabulary. Reporting success here would put a shot on the
    scorecard that no simulator ever received.
    """

    if simulator is Simulator.GSPRO:
        return {"Code": 501, "Message": reason}
    return {"Type": "Error", "Message": reason}


class ShotRelay:
    """Listens for PiTrac and forwards whatever it sends to the paired PC."""

    def __init__(
        self,
        ports: Optional[Dict[Simulator, int]] = None,
        host: str = RELAY_HOST,
        history: int = 25,
    ):
        self.ports = dict(ports or DEFAULT_RELAY_PORTS)
        self.host = host
        self._history_limit = history
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._servers: List[socket.socket] = []
        self._threads: List[threading.Thread] = []
        self._connections: Dict[Simulator, _PitracConnection] = {}
        self._send_to_companion: Optional[Callable[[Dict[str, Any]], None]] = None
        self._sequence = 0
        self._history: List[ShotRecord] = []
        self._pending: Dict[int, ShotRecord] = {}
        self.shots_forwarded = 0
        self.shots_failed = 0
        self.messages_forwarded = 0
        self.messages_failed = 0

    # --- Lifecycle --------------------------------------------------------

    def start(self) -> Dict[Simulator, int]:
        bound: Dict[Simulator, int] = {}
        for simulator, port in self.ports.items():
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            claim_port(server)
            server.bind((self.host, port))
            server.listen(4)
            server.settimeout(ACCEPT_POLL_SECONDS)
            self._servers.append(server)
            bound[simulator] = server.getsockname()[1]
            thread = threading.Thread(
                target=self._accept_loop, args=(server, simulator), daemon=True
            )
            thread.start()
            self._threads.append(thread)
        self.ports = bound
        return bound

    def stop(self) -> None:
        self._stop.set()
        for server in self._servers:
            try:
                server.close()
            except OSError:
                pass
        with self._lock:
            for connection in list(self._connections.values()):
                connection.close()
            self._connections.clear()
        for thread in self._threads:
            thread.join(timeout=2)
        self._servers.clear()
        self._threads.clear()

    def __enter__(self) -> "ShotRelay":
        self.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.stop()

    # --- The Companion side ----------------------------------------------

    def attach_companion(self, sender: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._send_to_companion = sender

    def detach_companion(self) -> None:
        """The computer has gone. Answer anything still in the air.

        Clearing the pending records was not enough: PiTrac was left waiting
        for a reply that would never come, and the shots did not show up as
        failures anywhere, so a disconnect mid-swing looked like nothing had
        happened at all. This does what the send-failure path already does.
        """

        with self._lock:
            self._send_to_companion = None
            stranded = list(self._pending.values())
            for record in stranded:
                record.message = "the connection to the computer was lost"
                self.messages_failed += 1
                if record.is_shot:
                    self.shots_failed += 1
            self._pending.clear()
            connections = dict(self._connections)

        reason = "the connection to the computer was lost"
        for record in stranded:
            try:
                simulator = Simulator(record.simulator)
            except ValueError:
                continue
            connection = connections.get(simulator)
            if connection is None:
                continue
            try:
                connection.send(unavailable_reply(simulator, reason))
            except OSError:
                pass

    @property
    def companion_attached(self) -> bool:
        with self._lock:
            return self._send_to_companion is not None

    def handle_simulator_message(self, payload: Dict[str, Any]) -> None:
        """A message from the real simulator, on its way back to PiTrac."""

        with self._lock:
            connections = list(self._connections.values())
        for connection in connections:
            try:
                connection.send(payload)
            except OSError:
                continue

    def handle_shot_result(self, frame: Dict[str, Any]) -> None:
        """The Companion reporting whether it could hand a shot to the simulator."""

        sequence = frame.get("sequence")
        accepted = bool(frame.get("accepted"))
        message = str(frame.get("message", ""))
        with self._lock:
            record = self._pending.pop(sequence, None)
            if record is None:
                return
            record.delivered = accepted
            record.message = message
            if accepted:
                self.messages_forwarded += 1
                if record.is_shot:
                    self.shots_forwarded += 1
            else:
                self.messages_failed += 1
                if record.is_shot:
                    self.shots_failed += 1

        if not accepted:
            # Tell PiTrac in the simulator's own language rather than leaving it
            # waiting for a reply that is never coming.
            with self._lock:
                connection = self._connections.get(Simulator(record.simulator))
            if connection is not None:
                try:
                    connection.send(
                        unavailable_reply(Simulator(record.simulator), message or "not delivered")
                    )
                except OSError:
                    pass

    # --- The PiTrac side --------------------------------------------------

    def _accept_loop(self, server: socket.socket, simulator: Simulator) -> None:
        while not self._stop.is_set():
            try:
                sock, _address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            thread = threading.Thread(
                target=self._serve_pitrac, args=(sock, simulator), daemon=True
            )
            thread.start()

    def _serve_pitrac(self, sock: socket.socket, simulator: Simulator) -> None:
        connection = _PitracConnection(sock, simulator)
        with self._lock:
            previous = self._connections.get(simulator)
            self._connections[simulator] = connection
        if previous is not None:
            previous.close()

        buffer = ""
        decoder = json.JSONDecoder()
        sock.settimeout(ACCEPT_POLL_SECONDS)
        try:
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    return
                if not chunk:
                    return
                try:
                    buffer += chunk.decode("utf-8")
                except UnicodeDecodeError:
                    return

                # PiTrac does not delimit its messages, so decode as much as
                # each read makes available and keep the remainder.
                while True:
                    stripped = buffer.lstrip()
                    if not stripped:
                        buffer = ""
                        break
                    try:
                        message, consumed = decoder.raw_decode(stripped)
                    except ValueError:
                        buffer = stripped
                        break
                    buffer = stripped[consumed:]
                    if isinstance(message, dict):
                        self._forward(connection, simulator, message)
        finally:
            with self._lock:
                if self._connections.get(simulator) is connection:
                    del self._connections[simulator]
            connection.close()

    def _expire_pending(self) -> List[ShotRecord]:
        """Give up on shots the Companion never answered. Returns the expired ones."""

        now = time.monotonic()
        with self._lock:
            expired = [
                record
                for sequence, record in list(self._pending.items())
                if record.deadline and record.deadline <= now
            ]
            for record in expired:
                self._pending.pop(record.sequence, None)
                record.delivered = False
                record.message = "the computer did not confirm the shot"
                self.messages_failed += 1
                if record.is_shot:
                    self.shots_failed += 1
        return expired

    def sweep(self) -> None:
        """Tell PiTrac about any shot that timed out. Safe to call often."""

        for record in self._expire_pending():
            with self._lock:
                connection = self._connections.get(Simulator(record.simulator))
            if connection is None:
                continue
            try:
                connection.send(
                    unavailable_reply(Simulator(record.simulator), record.message)
                )
            except OSError:
                continue

    def _forward(
        self, connection: _PitracConnection, simulator: Simulator, message: Dict[str, Any]
    ) -> None:
        self.sweep()
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
            sender = self._send_to_companion
            record = ShotRecord(
                sequence,
                simulator.value,
                time.time(),
                deadline=time.monotonic() + SHOT_ACK_SECONDS,
                is_shot=is_shot_message(simulator, message),
            )
            self._history.append(record)
            del self._history[: max(0, len(self._history) - self._history_limit)]

            if sender is None:
                self.messages_failed += 1
                if record.is_shot:
                    self.shots_failed += 1
                record.message = "no computer is connected"
            else:
                self._pending[sequence] = record

        if sender is None:
            try:
                connection.send(
                    unavailable_reply(
                        simulator,
                        "PiTrac Easy-Connect is not connected to a computer running your simulator",
                    )
                )
            except OSError:
                pass
            return

        try:
            sender(link.shot(sequence, simulator.value, message))
        except Exception:  # the link died between the check and the send
            with self._lock:
                self._pending.pop(sequence, None)
                self.messages_failed += 1
                if record.is_shot:
                    self.shots_failed += 1
                record.message = "the connection to the computer was lost"
            try:
                connection.send(
                    unavailable_reply(simulator, "the connection to the computer was lost")
                )
            except OSError:
                pass

    # --- Reporting --------------------------------------------------------

    @property
    def listening(self) -> bool:
        """Whether the relay actually holds its ports.

        Checked separately from PiTrac's configuration: if the bind failed —
        because another copy of the service is running, say — PiTrac would be
        pointed at a port with nothing behind it, and every shot would vanish.
        """

        return len(self._servers) == len(self.ports) and bool(self._servers)

    @property
    def pitrac_connected(self) -> bool:
        with self._lock:
            return bool(self._connections)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "listening": self.listening,
                "pitracConnected": bool(self._connections),
                "companionConnected": self._send_to_companion is not None,
                "shotsForwarded": self.shots_forwarded,
                "shotsFailed": self.shots_failed,
                "messagesForwarded": self.messages_forwarded,
                "messagesFailed": self.messages_failed,
                "ports": {sim.value: port for sim, port in self.ports.items()},
                "recentShots": [record.as_dict() for record in reversed(self._history)],
            }

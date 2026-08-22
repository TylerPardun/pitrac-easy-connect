"""One long-lived connection to GSPro or E6 on this computer.

The connection is held open rather than dialled per shot. E6 in particular is
stateful — it expects a handshake and then a shot sequence on the same socket —
so reconnecting between shots would throw away the state it depends on. GSPro is
happier either way, but a held connection also means a shot is not delayed by a
TCP handshake at the moment the ball is struck.

Everything PiTrac sends is written through untouched. This class does not
compose simulator messages during play; it only recognises enough of the replies
to tell the user whether the simulator is actually listening.
"""

import json
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional

from ..common.errors import SIM_BAD_RESPONSE, SIM_NOT_ARMED, SIM_NO_RESPONSE, SIM_REJECTED_SHOT
from ..models import ShotData, Simulator
from ..protocols import e6_ball_message, e6_club_message, gspro_message

CONNECT_TIMEOUT = 3.0
RESPONSE_TIMEOUT = 5.0


class SimulatorSession:
    def __init__(
        self,
        simulator: Simulator,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.simulator = simulator
        self.host = host
        self.port = port if port is not None else simulator.default_port
        self.on_message = on_message
        #: Counts inbound messages. A shot is confirmed delivered the moment
        #: the simulator says anything back, which is far quicker than waiting
        #: out a timeout to prove the connection is still there.
        self.messages_seen = 0
        self._lock = threading.RLock()
        self._sock: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._waiters: list = []
        self.last_error = ""
        self.messages_sent = 0
        self.messages_received = 0
        self.last_message_at: Optional[float] = None

    # --- Connecting -------------------------------------------------------

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._sock is not None

    def connect(self) -> None:
        with self._lock:
            if self._sock is not None:
                return
            try:
                sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT)
            except OSError as exc:
                self.last_error = _friendly(self.simulator, exc)
                raise
            sock.settimeout(0.5)
            self._sock = sock
            self.last_error = ""
            self._stop.clear()
            self._reader = threading.Thread(target=self._read_loop, args=(sock,), daemon=True)
            self._reader.start()

    def ensure_connected(self) -> bool:
        try:
            self.connect()
            return True
        except OSError:
            return False

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2)
        self._reader = None

    def _drop(self, reason: str) -> None:
        with self._lock:
            self._sock = None
            self.last_error = reason
            waiters = list(self._waiters)
            self._waiters.clear()
        for event, slot in waiters:
            slot.append(None)
            event.set()

    # --- Reading ----------------------------------------------------------

    def _read_loop(self, sock: socket.socket) -> None:
        buffer = ""
        decoder = json.JSONDecoder()
        while not self._stop.is_set():
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                self._drop("the simulator closed the connection")
                return
            if not chunk:
                self._drop("the simulator closed the connection")
                return
            try:
                buffer += chunk.decode("utf-8")
            except UnicodeDecodeError:
                self._drop("the simulator sent text we could not read")
                return

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
                    self._dispatch(message)

    def _dispatch(self, message: Dict[str, Any]) -> None:
        with self._lock:
            self.messages_received += 1
            self.last_message_at = time.time()
            waiters = list(self._waiters)
            self._waiters.clear()
        for event, slot in waiters:
            slot.append(message)
            event.set()
        self.messages_seen += 1
        if self.on_message is not None:
            try:
                self.on_message(message)
            except Exception:
                pass

    # --- Writing ----------------------------------------------------------

    def send(self, message: Dict[str, Any]) -> None:
        with self._lock:
            sock = self._sock
        if sock is None:
            raise OSError("not connected to the simulator")
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        try:
            sock.sendall(payload)
        except OSError:
            self._drop("the connection to the simulator was lost")
            raise
        with self._lock:
            self.messages_sent += 1

    def send_and_wait(
        self, message: Dict[str, Any], timeout: float = RESPONSE_TIMEOUT
    ) -> Optional[Dict[str, Any]]:
        event = threading.Event()
        slot: list = []
        with self._lock:
            self._waiters.append((event, slot))
        try:
            self.send(message)
        except OSError:
            with self._lock:
                if (event, slot) in self._waiters:
                    self._waiters.remove((event, slot))
            raise
        if not event.wait(timeout):
            with self._lock:
                if (event, slot) in self._waiters:
                    self._waiters.remove((event, slot))
            return None
        return slot[0] if slot else None

    # --- The deliberate test shot ----------------------------------------

    def send_test_shot(self, shot: ShotData) -> Dict[str, Any]:
        """Send one known shot and report exactly what the simulator did with it.

        This is the only shot Easy Connect composes itself. It is sent only when
        the user asks for it, because a simulator may score it into a live round.
        """

        if self.simulator is Simulator.GSPRO:
            response = self.send_and_wait(gspro_message(shot))
            if response is None:
                return {"accepted": False, "code": SIM_NO_RESPONSE.code, "response": None}
            if response.get("Code") == 200:
                return {"accepted": True, "code": "", "response": response}
            if response.get("Code") in (201, 202):
                # GSPro answers player-change and similar notices with 2xx codes
                # that are not shot acknowledgements.
                return {"accepted": False, "code": SIM_NOT_ARMED.code, "response": response}
            return {"accepted": False, "code": SIM_REJECTED_SHOT.code, "response": response}

        handshake = self.send_and_wait({"Type": "Handshake"})
        if handshake is None:
            return {"accepted": False, "code": SIM_NO_RESPONSE.code, "response": None}
        if handshake.get("Type") not in {"Handshake", "HandshakeAck"}:
            return {"accepted": False, "code": SIM_BAD_RESPONSE.code, "response": handshake}

        self.send(e6_ball_message(shot))
        time.sleep(0.05)
        self.send(e6_club_message())
        time.sleep(0.05)
        response = self.send_and_wait({"Type": "SendShot"})
        if response is None:
            return {"accepted": False, "code": SIM_NO_RESPONSE.code, "response": None}
        if response.get("Type") in {"ShotComplete", "ShotAccepted"}:
            return {"accepted": True, "code": "", "response": response}
        if response.get("Type") == "Error":
            return {"accepted": False, "code": SIM_REJECTED_SHOT.code, "response": response}
        return {"accepted": False, "code": SIM_BAD_RESPONSE.code, "response": response}

    # --- Reporting --------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "simulator": self.simulator.value,
                "simulatorLabel": self.simulator.label,
                "connected": self._sock is not None,
                "endpoint": "{}:{}".format(self.host, self.port),
                "messagesSent": self.messages_sent,
                "messagesReceived": self.messages_received,
                "lastError": self.last_error,
            }


def _friendly(simulator: Simulator, error: BaseException) -> str:
    if isinstance(error, ConnectionRefusedError):
        return "{} is not accepting connections on this computer".format(simulator.label)
    if isinstance(error, socket.timeout):
        return "{} did not answer in time".format(simulator.label)
    return str(error) or error.__class__.__name__

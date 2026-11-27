"""One long-lived connection to a golf simulator on this computer.

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
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ..common.errors import SIM_BAD_RESPONSE, SIM_NOT_ARMED, SIM_NO_RESPONSE, SIM_REJECTED_SHOT
from ..models import ShotData, Simulator
from ..protocols import e6_ball_message, e6_club_message, gspro_message

#: What became of a shot, from best to worst. Kept apart because they are
#: different things to somebody wondering whether a stroke counted.
PLAYED = "played"          # the simulator said where it went
ACCEPTED = "accepted"      # the simulator said it took it
UNKNOWN = "unknown"        # it was sent, and nothing was said
REJECTED = "rejected"      # the simulator said no
UNDELIVERED = "undelivered"  # there was nothing to send it to
LOCAL = "local"            # there was never meant to be


@dataclass(frozen=True)
class Delivery:
    outcome: str
    message: str = ""

    @property
    def sent(self) -> bool:
        return self.outcome in (PLAYED, ACCEPTED, UNKNOWN)


#: How long to wait for a simulator to say something about a shot. A shot is in
#: the air for seconds, so this is invisible; being told a lie about it is not.
ANSWER_SECONDS = 1.0

CONNECT_TIMEOUT = 3.0
RESPONSE_TIMEOUT = 5.0


class SimulatorSession:
    def __init__(
        self,
        simulator: Simulator,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_late_answer: Optional[Callable[[str, Delivery], None]] = None,
        on_lost: Optional[Callable[[], None]] = None,
    ):
        #: Told when a shot is answered after it was given up on.
        self.on_late_answer = on_late_answer
        #: Told when the connection goes, however it went.
        self.on_lost = on_lost
        #: Which connection this is. What one connection showed is no evidence
        #: about the next: the program may have been closed and reopened.
        self.generation = 0
        #: The shot still owed an answer. Answers carry no names, so at most one
        #: may be owed at a time or nobody could say whose the next one is.
        self._owed: Optional[str] = None
        self.simulator = simulator
        self.host = host
        self.port = port if port is not None else simulator.default_port
        self.on_message = on_message
        #: Counts inbound messages. A shot is confirmed delivered the moment
        #: the simulator says anything back, which is far quicker than waiting
        #: out a timeout to prove the connection is still there.
        self.messages_seen = 0
        self._lock = threading.RLock()
        #: One connection attempt at a time, held across the network wait so
        #: that _lock -- which every status read takes -- never is.
        self._connecting = threading.Lock()
        #: Bumped by close(), so a connect that was under way when the session
        #: was closed does not bring it back to life.
        self._closes = 0
        self._sock: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._waiters: list = []
        self._listener: Optional[Callable[[Dict[str, Any]], None]] = None
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
        # The connect itself happens outside _lock. Holding it across a refused
        # connection -- about two seconds on Windows -- stalled every status
        # read, and with it the window, for as long.
        with self._connecting:
            with self._lock:
                if self._sock is not None:
                    return
                closes = self._closes
            try:
                sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT)
            except OSError as exc:
                with self._lock:
                    self.last_error = _friendly(self.simulator, exc)
                raise
            sock.settimeout(0.5)
            self._prepare(sock)
            with self._lock:
                if self._closes != closes or self._sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                    if self._sock is not None:
                        return
                    raise ConnectionAbortedError("the session was closed while connecting")
                self._connect_locked(sock)

    def _connect_locked(self, sock: socket.socket) -> None:
        """Adopt a fresh connection. Called with _lock held."""

        self._sock = sock
        self.generation += 1
        self._owed = None
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

    def reconnect(self) -> None:
        """Start again on a connection where nothing is owed."""

        self.close()
        self.connect()

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._closes += 1
            sock, self._sock = self._sock, None
            self._owed = None
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
        if sock is not None:
            self._say_lost()

    def _say_lost(self) -> None:
        if self.on_lost is not None:
            try:
                self.on_lost()
            except Exception:
                pass

    def _drop(self, reason: str, sock: Optional[socket.socket] = None) -> None:
        with self._lock:
            if self._sock is None or (sock is not None and sock is not self._sock):
                # Already gone, or somebody else's: an old connection noticing
                # it has closed must not take down the new one.
                return
            self._sock = None
            self._owed = None
            self.last_error = reason
            waiters = list(self._waiters)
            self._waiters.clear()
        for event, slot in waiters:
            slot.append(None)
            event.set()
        self._say_lost()

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
                self._drop("the simulator closed the connection", sock)
                return
            if not chunk:
                self._drop("the simulator closed the connection", sock)
                return
            try:
                buffer += chunk.decode("utf-8")
            except UnicodeDecodeError:
                self._drop("the simulator sent text we could not read", sock)
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
            listen, owed = None, None
            if self._owed is not None and self._answers(message):
                listen, owed, self._owed = self._listener, self._owed, None
        for event, slot in waiters:
            slot.append(message)
            event.set()
        if listen is not None:
            listen(message)
        elif owed is not None and self.on_late_answer is not None:
            try:
                self.on_late_answer(owed, self._judge(message))
            except Exception:
                pass
        self.messages_seen += 1
        if self.on_message is not None:
            try:
                self.on_message(message)
            except Exception:
                pass

    # --- Writing ----------------------------------------------------------

    def _prepare(self, sock: socket.socket) -> None:
        """Anything this simulator needs of the connection itself."""

    def _encode(self, message: Dict[str, Any]) -> bytes:
        return json.dumps(message, separators=(",", ":")).encode("utf-8")

    def set_ready(self, ready: bool) -> None:
        """Whether there is a ball to hit, for a simulator that asks separately."""

    def deliver(self, payload: Dict[str, Any], shot_id: str = "") -> Delivery:
        """Hand over one swing, and report what was actually said about it.

        GSPro answers a shot with 200 or a 5xx. It also speaks up unasked, with
        2xx codes about the player, and those are not answers to anything.
        """

        self._owe_nothing()
        reply = self._answer_to(payload, shot_id)
        if reply is None:
            return Delivery(UNKNOWN, "sent to {}, which has not answered".format(self.simulator.label))
        return self._judge(reply)

    def _answers(self, reply: Dict[str, Any]) -> bool:
        """Whether this is an answer to a shot, rather than something else said."""

        code = reply.get("Code")
        return code == 200 or (isinstance(code, int) and code >= 500)

    def _judge(self, reply: Dict[str, Any]) -> Delivery:
        if reply.get("Code") == 200:
            return Delivery(ACCEPTED, "{} took it".format(self.simulator.label))
        return Delivery(REJECTED, str(reply.get("Message") or "{} refused it".format(
            self.simulator.label)))

    def _owe_nothing(self) -> None:
        """Make sure the next answer can only be about what is sent next.

        A shot that was never answered leaves a question open. If its answer
        came in the meantime it has been credited to it. If not, it might arrive
        any moment and be taken for the next shot's, so that connection is
        finished with. Only when there is a next shot: one that is merely slow
        is not cut off for being slow.
        """

        if self._owed is not None:
            self.reconnect()

    def _answer_to(self, message: Dict[str, Any], shot_id: str) -> Optional[Dict[str, Any]]:
        """Send, and wait briefly for something that answers it.

        Raises ``OSError`` if the connection goes while waiting: a write to a
        program that has died succeeds, and its silence is not "no answer".
        """

        answered = threading.Event()
        found: List[Dict[str, Any]] = []

        def listen(reply: Dict[str, Any]) -> None:
            found.append(reply)
            answered.set()

        with self._lock:
            self._listener = listen
            self._owed = shot_id
            generation = self.generation
        try:
            self.send(message)
            deadline = time.monotonic() + ANSWER_SECONDS
            while not answered.wait(0.05):
                if not self.connected or self.generation != generation:
                    raise OSError("the simulator closed the connection")
                if time.monotonic() >= deadline:
                    break
        finally:
            with self._lock:
                self._listener = None
        # Read once nothing can be added: an answer is either this or late.
        return found[0] if found else None

    def send(self, message: Dict[str, Any]) -> None:
        with self._lock:
            sock = self._sock
        if sock is None:
            raise OSError("not connected to the simulator")
        payload = self._encode(message)
        try:
            sock.sendall(payload)
        except OSError:
            self._drop("the connection to the simulator was lost", sock)
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
            delivery = self.deliver(gspro_message(shot))
            if delivery.outcome == ACCEPTED:
                return {"accepted": True, "code": "", "response": {"Code": 200}}
            code = SIM_REJECTED_SHOT if delivery.outcome == REJECTED else SIM_NO_RESPONSE
            return {"accepted": False, "code": code.code, "response": None}

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

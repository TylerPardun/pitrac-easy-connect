"""The Companion's end of the link to the enclosure.

Runs a small state machine in a background thread: connect, prove the pairing,
pump frames, and on any failure wait and try again. Reconnecting is expected
rather than exceptional — the enclosure reboots, the router hands out a new
lease, someone closes the laptop — so the loop treats a lost link as routine and
says so plainly instead of raising.

Shots arriving from the enclosure are written straight into the open simulator
session. Nothing is queued. A shot that could not be delivered when it happened
is reported as lost, not replayed later into a hole the player has already
finished.
"""

import socket
import threading
import time
from typing import Any, Callable, Dict, Optional

from ..common import link
from ..common.errors import LINK_LOST, LINK_VERSION_MISMATCH, ErrorInfo, lookup

RECONNECT_SECONDS = 3.0
CONNECT_TIMEOUT = 5.0
HANDSHAKE_TIMEOUT = 10.0


class CompanionLinkClient:
    def __init__(
        self,
        host: str,
        port: int,
        pairing_id: str,
        secret: str,
        version: str,
        computer_name: str,
        on_shot: Callable[[int, str, Dict[str, Any]], Dict[str, Any]],
        on_state: Optional[Callable[[], None]] = None,
        on_enclosure_status: Optional[Callable[[Dict[str, Any]], None]] = None,
        reconnect_seconds: float = RECONNECT_SECONDS,
    ):
        self.host = host
        self.port = port
        self.pairing_id = pairing_id
        self.secret = secret
        self.version = version
        self.computer_name = computer_name
        self.on_shot = on_shot
        self.on_state = on_state
        self.on_enclosure_status = on_enclosure_status
        self.reconnect_seconds = reconnect_seconds

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stream: Optional[link.FrameStream] = None
        self._device: Dict[str, Any] = {}
        self._pending_commands: Dict[int, Any] = {}
        self._command_id = 0
        self.connected = False
        self.last_error: Optional[Dict[str, str]] = None
        self.connected_since: Optional[float] = None

    # --- Lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            stream = self._stream
        if stream is not None:
            stream.close()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None

    def wait_until_connected(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.connected:
                return True
            time.sleep(0.02)
        return False

    # --- The loop ---------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._connect_once()
            except Exception as exc:  # every failure here is a retry, not a crash
                self._set_error(_as_error(exc))
            finally:
                self._mark_disconnected()
            if self._stop.wait(self.reconnect_seconds):
                return

    def _connect_once(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT)
        sock.settimeout(None)
        stream = link.FrameStream(sock)
        with self._lock:
            self._stream = stream
        try:
            self._handshake(stream)
            self._pump(stream)
        finally:
            stream.close()
            with self._lock:
                if self._stream is stream:
                    self._stream = None

    def _handshake(self, stream: link.FrameStream) -> None:
        hello = stream.receive(timeout=HANDSHAKE_TIMEOUT)
        if hello.get("type") != "hello":
            raise link.LinkError("PiTrac did not introduce itself")

        outdated = link.check_protocol(hello)
        if outdated is not None:
            side = "PiTrac" if outdated == "them" else "this computer"
            self._set_error(
                LINK_VERSION_MISMATCH.as_dict("{} needs to be updated".format(side))
            )
            raise link.LinkError("protocol mismatch")

        challenge = str(hello.get("challenge", ""))
        from ..pi.pairing import PairingManager  # shared HMAC construction

        stream.send(
            link.auth(
                self.pairing_id,
                PairingManager.client_proof(self.secret, challenge),
                self.version,
                self.computer_name,
            )
        )
        reply = stream.receive(timeout=HANDSHAKE_TIMEOUT)
        if reply.get("type") == "error":
            info = reply.get("error") or {}
            self._set_error(info)
            raise link.LinkError(info.get("failed", "PiTrac refused the connection"))
        if reply.get("type") != "authOk":
            raise link.LinkError("PiTrac sent an unexpected reply")

        expected = PairingManager.expected_server_proof(self.secret, challenge)
        if str(reply.get("serverProof", "")) != expected:
            # Something is answering on the enclosure's address but does not
            # hold its secret. Refuse rather than send shots into it.
            raise link.LinkError("that device could not prove it is your PiTrac")

        with self._lock:
            self._device = dict(hello.get("device") or {})
            self.connected = True
            self.connected_since = time.time()
            self.last_error = None
        self._notify()

    def _pump(self, stream: link.FrameStream) -> None:
        while not self._stop.is_set():
            try:
                frame = stream.receive(timeout=1.0)
            except TimeoutError:
                continue
            kind = frame.get("type")

            if kind == "shot":
                self._handle_shot(stream, frame)
            elif kind == "ping":
                stream.send(link.pong(frame.get("at", time.time())))
            elif kind == "commandResult":
                self._resolve_command(frame)
            elif kind == "enclosureStatus":
                payload = frame.get("status") or {}
                with self._lock:
                    self._device.update(payload.get("device") or {})
                if self.on_enclosure_status is not None:
                    try:
                        self.on_enclosure_status(payload)
                    except Exception:
                        pass
                self._notify()
            elif kind == "error":
                self._set_error(frame.get("error") or {})

    def _handle_shot(self, stream: link.FrameStream, frame: Dict[str, Any]) -> None:
        sequence = frame.get("sequence", 0)
        try:
            outcome = self.on_shot(
                sequence, str(frame.get("simulator", "")), frame.get("payload") or {}
            )
        except Exception as exc:
            outcome = {"accepted": False, "message": str(exc)}
        stream.send(
            link.shot_result(
                sequence,
                bool(outcome.get("accepted")),
                str(outcome.get("message", "")),
                code=str(outcome.get("code", "")),
            )
        )

    # --- Talking back to the enclosure -----------------------------------

    def send_simulator_message(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            stream = self._stream
            connected = self.connected
        if stream is None or not connected:
            return
        try:
            stream.send(link.simulator_message(payload))
        except (link.LinkError, link.LinkClosed):
            pass

    def send_simulator_status(self, status: Dict[str, Any]) -> None:
        with self._lock:
            stream = self._stream
            connected = self.connected
        if stream is None or not connected:
            return
        try:
            stream.send(link.simulator_status(status))
        except (link.LinkError, link.LinkClosed):
            pass

    def call(self, name: str, arguments: Optional[Dict[str, Any]] = None, timeout: float = 20.0):
        """Ask the enclosure to do something and wait for its answer."""

        with self._lock:
            stream = self._stream
            if stream is None or not self.connected:
                raise link.LinkClosed("not connected to PiTrac")
            self._command_id += 1
            request_id = self._command_id
            event = threading.Event()
            slot: list = []
            self._pending_commands[request_id] = (event, slot)

        try:
            stream.send(link.command(request_id, name, arguments))
        except (link.LinkError, link.LinkClosed):
            with self._lock:
                self._pending_commands.pop(request_id, None)
            raise

        if not event.wait(timeout):
            with self._lock:
                self._pending_commands.pop(request_id, None)
            raise TimeoutError("PiTrac did not answer the {} request".format(name))
        return slot[0] if slot else None

    def _resolve_command(self, frame: Dict[str, Any]) -> None:
        with self._lock:
            waiter = self._pending_commands.pop(frame.get("id"), None)
        if waiter is None:
            return
        event, slot = waiter
        slot.append(frame)
        event.set()

    # --- Reporting --------------------------------------------------------

    def _mark_disconnected(self) -> None:
        with self._lock:
            was_connected = self.connected
            self.connected = False
            self.connected_since = None
            pending = list(self._pending_commands.values())
            self._pending_commands.clear()
        for event, slot in pending:
            slot.append(None)
            event.set()
        if was_connected:
            self._set_error(LINK_LOST.as_dict())
        self._notify()

    def _set_error(self, info: Dict[str, str]) -> None:
        with self._lock:
            self.last_error = dict(info) if info else None
        self._notify()

    def _notify(self) -> None:
        if self.on_state is not None:
            try:
                self.on_state()
            except Exception:
                pass

    @property
    def device(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._device)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "connected": self.connected,
                "address": "{}:{}".format(self.host, self.port),
                "device": dict(self._device),
                "connectedSince": self.connected_since,
                "lastError": dict(self.last_error) if self.last_error else None,
            }


def _as_error(exc: BaseException) -> Dict[str, str]:
    if isinstance(exc, (ConnectionRefusedError, socket.timeout, OSError)):
        from ..common.errors import LINK_NOT_FOUND

        return LINK_NOT_FOUND.as_dict(str(exc))
    return LINK_LOST.as_dict(str(exc))

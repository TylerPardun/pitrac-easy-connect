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
from typing import Any, Callable, Dict, List, Optional

from ..common import link
from ..common.errors import (
    LINK_BUSY,
    LINK_DEVICE_MISMATCH,
    LINK_LOST,
    LINK_VERSION_MISMATCH,
    PAIR_NOT_PAIRED,
    PAIR_RATE_LIMITED,
    PAIR_REVOKED,
)

RECONNECT_SECONDS = 3.0
CONNECT_TIMEOUT = 5.0
HANDSHAKE_TIMEOUT = 10.0

#: Codes a Pi-reported handshake refusal can carry that no amount of retrying
#: with the same credentials will fix. Stop the reconnect loop rather than
#: hammering the enclosure (and its rate limiter) every few seconds with the
#: same rejected pairing id.
TERMINAL_CODES = {
    PAIR_RATE_LIMITED.code,
    PAIR_NOT_PAIRED.code,
    PAIR_REVOKED.code,
    LINK_VERSION_MISMATCH.code,
    LINK_BUSY.code,
}


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
        fallback_hosts: Optional[List[str]] = None,
        expected_device_id: str = "",
    ):
        self.host = host
        self.port = port
        self.pairing_id = pairing_id
        self.secret = secret
        self.version = version
        self.computer_name = computer_name
        self.expected_device_id = expected_device_id
        self.on_shot = on_shot
        self.on_state = on_state
        self.on_enclosure_status = on_enclosure_status
        self.reconnect_seconds = reconnect_seconds
        self._hosts = list(dict.fromkeys([host, *(fallback_hosts or [])]))

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
            # A structured error learned from one candidate this cycle (the
            # Pi actually answered and refused) must survive a later, less
            # informative failure from a lower-priority fallback candidate
            # (typically a DNS lookup that fails for an mDNS hostname).
            structured_this_cycle: Optional[Dict[str, Any]] = None
            terminal = False
            for candidate in self._hosts:
                if self._stop.is_set():
                    return
                with self._lock:
                    self.host = candidate
                connected_here = False
                try:
                    self._connect_once()
                except link.TerminalLinkError as exc:
                    # Snapshot this before finally marks the client down. A
                    # socket that completed its handshake and later dropped is
                    # not a failed address lookup. Trying every stale fallback
                    # after that made an ordinary reconnect take longer than
                    # all of their DNS/connect timeouts combined.
                    connected_here = self.connected
                    structured_this_cycle = exc.info
                    self._set_error(exc.info)
                    terminal = True
                except Exception as exc:  # every other failure here is a retry, not a crash
                    connected_here = self.connected
                    if structured_this_cycle is None:
                        self._set_error(_as_error(exc))
                finally:
                    self._mark_disconnected()
                if connected_here:
                    # Keep the address that just worked first and retry it on
                    # the next cycle. Fallbacks remain available if the next
                    # connection attempt itself fails.
                    self._hosts.remove(candidate)
                    self._hosts.insert(0, candidate)
                    break
                if terminal:
                    break
            if terminal:
                # These credentials cannot succeed against whatever answered.
                # Stop the thread rather than retrying every few seconds; a
                # fresh CompanionLinkClient is what resumes trying, once the
                # user has acted (removed the stale pairing, paired again).
                return
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
            info = LINK_VERSION_MISMATCH.as_dict("{} needs to be updated".format(side))
            self._set_error(info)
            raise link.TerminalLinkError(info)

        device = hello.get("device") or {}
        reported_id = str(device.get("deviceId", ""))
        if self.expected_device_id and reported_id and reported_id != self.expected_device_id:
            # Whatever answered at this host/port is not the PiTrac this
            # pairing id and secret were issued for. Refuse to present them —
            # sending stale credentials to an unrelated (or wiped/replaced)
            # enclosure teaches it nothing useful and only costs it a failed
            # attempt against its own rate limiter.
            info = LINK_DEVICE_MISMATCH.as_dict(
                "expected {}, found {}".format(self.expected_device_id, reported_id)
            )
            self._set_error(info)
            raise link.TerminalLinkError(info)

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
            if str(info.get("code", "")) in TERMINAL_CODES:
                raise link.TerminalLinkError(info)
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

"""Accepting the Companion's connection and proving both sides belong together.

The enclosure listens; the PC dials in. Exactly one Companion holds the link at
a time, because two PCs forwarding shots into two different simulators from one
launch monitor is never what anyone wanted, and silently picking one would be
worse than saying so.
"""

import socket
import threading
import time
from typing import Any, Callable, Dict, Optional

from ..common import link
from ..common.errors import (
    LINK_BUSY,
    LINK_VERSION_MISMATCH,
    PAIR_NOT_PAIRED,
    EasyConnectError,
)
from .pairing import PairingManager

HANDSHAKE_TIMEOUT = 10.0
IDLE_TIMEOUT = 90.0

#: How often the accept loop checks whether it has been asked to stop.
ACCEPT_POLL_SECONDS = 0.2


class CompanionLinkServer:
    def __init__(
        self,
        pairings: PairingManager,
        device_info: Callable[[], Dict[str, Any]],
        version: str,
        on_attach: Callable[["CompanionSession"], None],
        on_detach: Callable[["CompanionSession"], None],
        on_frame: Callable[["CompanionSession", Dict[str, Any]], None],
        host: str = "0.0.0.0",
        port: int = link.LINK_PORT,
    ):
        self.pairings = pairings
        self.device_info = device_info
        self.version = version
        self.on_attach = on_attach
        self.on_detach = on_detach
        self.on_frame = on_frame
        self.host = host
        self.port = port
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._session: Optional["CompanionSession"] = None

    # --- Lifecycle --------------------------------------------------------

    def start(self) -> int:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(4)
        server.settimeout(ACCEPT_POLL_SECONDS)
        self._server = server
        self.port = server.getsockname()[1]
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        with self._lock:
            session = self._session
        if session is not None:
            session.close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def __enter__(self) -> "CompanionLinkServer":
        self.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.stop()

    @property
    def session(self) -> Optional["CompanionSession"]:
        with self._lock:
            return self._session

    @property
    def connected(self) -> bool:
        session = self.session
        return session is not None and session.authenticated

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                sock, address = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(sock, address), daemon=True).start()

    # --- One connection ---------------------------------------------------

    def _handle(self, sock: socket.socket, address) -> None:
        stream = link.FrameStream(sock)
        session = CompanionSession(stream, address[0])
        try:
            challenge = self._authenticate(session)
        except EasyConnectError as exc:
            _try_send(stream, link.error(exc.info.code, exc.info.failed, exc.info.next_step,
                                         exc.info.still_safe))
            stream.close()
            return
        except (link.LinkError, link.LinkClosed, TimeoutError):
            stream.close()
            return

        # Admission comes after the pairing is proved but before the connection
        # is acknowledged. Acknowledging first and refusing afterwards would
        # leave the PC believing it is connected when it is not.
        with self._lock:
            existing = self._session
            if existing is not None and existing.authenticated and existing.alive:
                _try_send(
                    stream,
                    link.error(
                        LINK_BUSY.code, LINK_BUSY.failed, LINK_BUSY.next_step, LINK_BUSY.still_safe
                    ),
                )
                stream.close()
                return
            self._session = session

        session.authenticated = True
        _try_send(
            stream, link.auth_ok(self.pairings.server_proof(session.pairing_id, challenge))
        )
        self.on_attach(session)
        try:
            self._pump(session)
        finally:
            # Only detach if this session is still the current one. A Companion
            # that reconnects quickly can be admitted before the old session's
            # thread finishes unwinding, and an unguarded detach would tear down
            # the new link that had just been established.
            with self._lock:
                was_current = self._session is session
                if was_current:
                    self._session = None
            if was_current:
                self.on_detach(session)
            session.close()

    def _authenticate(self, session: "CompanionSession") -> str:
        """Prove the pairing. Does not yet admit the session, and sends no authOk."""

        challenge = self.pairings.new_challenge()
        session.stream.send(link.hello(self.device_info(), self.version, challenge))

        frame = session.stream.receive(timeout=HANDSHAKE_TIMEOUT)
        if frame.get("type") != "auth":
            raise EasyConnectError(PAIR_NOT_PAIRED, "the computer did not identify itself")

        outdated = link.check_protocol(frame)
        if outdated is not None:
            raise EasyConnectError(
                LINK_VERSION_MISMATCH,
                "the computer speaks protocol {}, PiTrac speaks {}".format(
                    frame.get("protocol"), link.PROTOCOL_VERSION
                ),
            )

        pairing_id = str(frame.get("pairingId", ""))
        self.pairings.verify(pairing_id, challenge, str(frame.get("proof", "")))

        session.pairing_id = pairing_id
        session.companion_version = str(frame.get("version", ""))
        session.computer_name = str(frame.get("computerName", "")) or "Windows PC"
        return challenge

    def _pump(self, session: "CompanionSession") -> None:
        last_heard = time.monotonic()
        while not self._stop.is_set() and session.alive:
            try:
                frame = session.stream.receive(timeout=1.0)
            except TimeoutError:
                if time.monotonic() - last_heard > IDLE_TIMEOUT:
                    return
                _try_send(session.stream, link.ping())
                continue
            except (link.LinkClosed, link.LinkError):
                return

            last_heard = time.monotonic()
            kind = frame.get("type")
            if kind == "ping":
                _try_send(session.stream, link.pong(frame.get("at", time.time())))
                continue
            if kind == "pong":
                continue
            try:
                self.on_frame(session, frame)
            except Exception:
                # One malformed frame must not take the link down.
                continue


class CompanionSession:
    def __init__(self, stream: link.FrameStream, peer_address: str):
        self.stream = stream
        self.peer_address = peer_address
        self.pairing_id = ""
        self.computer_name = ""
        self.companion_version = ""
        self.authenticated = False
        self.connected_at = time.time()
        self._alive = True

    @property
    def alive(self) -> bool:
        return self._alive

    def send(self, frame: Dict[str, Any]) -> None:
        self.stream.send(frame)

    def close(self) -> None:
        self._alive = False
        self.stream.close()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "computerName": self.computer_name,
            "address": self.peer_address,
            "companionVersion": self.companion_version,
            "connectedAt": self.connected_at,
            "pairingId": self.pairing_id,
        }


def _try_send(stream: link.FrameStream, frame: Dict[str, Any]) -> None:
    try:
        stream.send(frame)
    except (link.LinkError, link.LinkClosed, OSError):
        pass

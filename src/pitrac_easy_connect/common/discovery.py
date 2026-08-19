"""Finding the enclosure without ever asking a person for an IP address.

Two mechanisms, because neither is reliable everywhere:

**mDNS.** The Pi publishes ``_pitrac._tcp`` through the avahi daemon that is
already running. This is what makes ``pitrac-<id>.local`` work and is the
mechanism printed on the owner card as the fallback address.

**A UDP beacon.** The Companion broadcasts a short probe and every enclosure
that hears it answers. This exists because mDNS is blocked or unreliable on a
surprising number of consumer routers, and because it works unchanged on the
enclosure's own hotspot, where there is no router at all.

The beacon answers with identity and state only. It carries no secret, so
anything on the network learning that a PiTrac exists is the extent of the
exposure — the same thing mDNS already advertises. Doing anything with the
enclosure still requires a pairing.
"""

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

DISCOVERY_PORT = 39876
PROBE = b"PITRAC-DISCOVER-V1"
MAX_REPLY_BYTES = 8192
SERVICE_TYPE = "_pitrac._tcp"

#: How often the responder checks whether it has been asked to stop.
RESPONDER_POLL_SECONDS = 0.2


@dataclass(frozen=True)
class FoundEnclosure:
    device_id: str
    display_name: str
    #: Where the reply actually came from. This is the address to connect to,
    #: because it is the one proven to reach this enclosure from here.
    address: str
    link_port: int
    version: str
    state: str
    hostname: str = ""
    #: Where this enclosure serves its setup page. Advertised rather than
    #: assumed, because the installer allows it to be moved off port 80.
    portal_port: int = 80
    last_seen: float = 0.0
    #: The address the enclosure believes it has. Kept for display and for
    #: diagnosing the case where the two disagree, but never dialled: an
    #: enclosure behind a second interface, or holding a stale lease, can
    #: report an address that is not reachable from this computer.
    reported_address: str = ""

    @property
    def short_id(self) -> str:
        return self.device_id[-4:]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "deviceId": self.device_id,
            "shortId": self.short_id,
            "displayName": self.display_name,
            "address": self.address,
            "linkPort": self.link_port,
            "version": self.version,
            "state": self.state,
            "hostname": self.hostname,
            "portalPort": self.portal_port,
            "lastSeen": self.last_seen,
            "reportedAddress": self.reported_address,
        }


class DiscoveryResponder:
    """Runs on the Pi. Answers probes with who this enclosure is."""

    def __init__(
        self,
        describe: Callable[[], Dict[str, Any]],
        port: int = DISCOVERY_PORT,
        host: str = "0.0.0.0",
    ):
        self.describe = describe
        self.port = port
        self.host = host
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
        sock.bind((self.host, self.port))
        sock.settimeout(RESPONDER_POLL_SECONDS)
        self._sock = sock
        self.port = sock.getsockname()[1]
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def __enter__(self) -> "DiscoveryResponder":
        self.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.stop()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, sender = self._sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                return
            if data.strip() != PROBE:
                continue
            try:
                payload = json.dumps(self.describe(), separators=(",", ":")).encode("utf-8")
            except Exception:
                continue
            if len(payload) > MAX_REPLY_BYTES:
                continue
            try:
                self._sock.sendto(payload, sender)
            except OSError:
                continue


def discover(
    timeout: float = 2.0, port: int = DISCOVERY_PORT, broadcast_to: Optional[List[str]] = None
) -> List[FoundEnclosure]:
    """Runs on the Companion. Returns every enclosure that answered."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.3)
    try:
        sock.bind(("", 0))
        targets = broadcast_to or ["255.255.255.255", "127.0.0.1"]
        for target in targets:
            try:
                sock.sendto(PROBE, (target, port))
            except OSError:
                continue

        found: Dict[str, FoundEnclosure] = {}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, sender = sock.recvfrom(MAX_REPLY_BYTES)
            except socket.timeout:
                continue
            except OSError:
                break
            enclosure = _parse(data, sender[0])
            if enclosure is not None:
                found[enclosure.device_id] = enclosure
        # Sorted by name so two enclosures are always listed in the same order
        # rather than in whichever order they happened to answer.
        return sorted(found.values(), key=lambda item: (item.display_name, item.device_id))
    finally:
        sock.close()


def _parse(data: bytes, address: str) -> Optional[FoundEnclosure]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or not payload.get("deviceId"):
        return None
    return FoundEnclosure(
        device_id=str(payload.get("deviceId", "")),
        display_name=str(payload.get("displayName", "PiTrac")),
        address=address,
        reported_address=str(payload.get("address") or ""),
        link_port=int(payload.get("linkPort") or 0),
        version=str(payload.get("version", "")),
        state=str(payload.get("state", "")),
        hostname=str(payload.get("hostname", "")),
        portal_port=int(payload.get("portalPort") or 80),
        last_seen=time.time(),
    )

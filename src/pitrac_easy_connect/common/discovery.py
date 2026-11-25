"""Finding the enclosure without ever asking a person for an IP address.

Automatic discovery uses a UDP beacon. The Pi also publishes its ordinary
``pitrac-<id>.local`` hostname through mDNS, but the desktop does not browse a
Bonjour service catalogue. That hostname is a connection fallback for a paired
enclosure whose DHCP address changed; it is not a second discovery mechanism.

The beacon answers with identity and state only. It carries no secret, so
anything on the network learning that a PiTrac exists is the extent of the
exposure — the same thing mDNS already advertises. Doing anything with the
enclosure still requires a pairing.
"""

import json

from . import jsontext
import re
import errno
import ipaddress
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

DISCOVERY_PORT = 39876
PROBE = b"PITRAC-DISCOVER-V1"
MAX_REPLY_BYTES = 8192
# The Pi publishes this service for ordinary `.local` hostname resolution and
# other Bonjour-aware tools. The desktop's automatic search remains UDP-only.
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


@dataclass(frozen=True)
class DiscoveryProblem:
    """Why a search could not complete normally."""

    kind: str
    message: str
    next_step: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "kind": self.kind,
            "message": self.message,
            "nextStep": self.next_step,
        }


@dataclass(frozen=True)
class DiscoveryResult:
    """One atomic search result, safe to pass between concurrent callers."""

    enclosures: List[FoundEnclosure]
    problem: Optional[DiscoveryProblem] = None

    # Iteration keeps callers interested only in enclosures simple while the
    # error remains attached to the same result instead of living in a global.
    def __iter__(self) -> Iterator[FoundEnclosure]:
        return iter(self.enclosures)

    def __len__(self) -> int:
        return len(self.enclosures)

    def __getitem__(self, index):
        return self.enclosures[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list):
            return self.enclosures == other
        if isinstance(other, DiscoveryResult):
            return self.enclosures == other.enclosures and self.problem == other.problem
        return NotImplemented


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

    @property
    def listening(self) -> bool:
        """Whether the beacon socket is actually bound."""

        return self._sock is not None

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
) -> DiscoveryResult:
    """Runs on the desktop and returns enclosures plus any search failure.

    ``broadcast_to`` is an explicit test/service override. Production calls
    leave it unset and probe every active IPv4 broadcast plus the limited
    broadcast address. Loopback is kept as a local simulator probe, but never
    counts as proof that real network traffic was sent.
    """

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.3)
    except OSError as exc:
        return DiscoveryResult([], _socket_problem("send", exc))
    try:
        try:
            sock.bind(("", 0))
        except OSError as exc:
            return DiscoveryResult([], _socket_problem("send", exc))

        explicit_targets = broadcast_to is not None
        targets = _dedupe(broadcast_to or [*_network_broadcasts(), "127.0.0.1"])
        network_attempts = 0
        network_sent = 0
        failures = []
        for target in targets:
            is_local = _is_loopback(target)
            if not is_local:
                network_attempts += 1
            try:
                sock.sendto(PROBE, (target, port))
                if not is_local:
                    network_sent += 1
            except OSError as exc:
                if not is_local:
                    failures.append((target, exc))
                continue

        # A loopback success is useful to tests, but says nothing about whether
        # the computer was allowed to ask the LAN. Explicit loopback-only calls
        # are the exception because they deliberately do not test the LAN.
        problem = None
        if network_attempts and network_sent == 0:
            problem = _socket_problem("send", failures[0][1] if failures else None)
        elif not explicit_targets and network_attempts == 0:
            problem = DiscoveryProblem(
                "network",
                "This computer has no active IPv4 interface that can send discovery traffic.",
                "Connect this computer to the same network as PiTrac, then search again.",
            )

        found: Dict[str, FoundEnclosure] = {}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, sender = sock.recvfrom(MAX_REPLY_BYTES)
            except socket.timeout:
                continue
            except OSError as exc:
                problem = _socket_problem("receive", exc)
                break
            enclosure = _parse(data, sender[0])
            if enclosure is not None:
                found[enclosure.device_id] = enclosure
        # Sorted by name so two enclosures are always listed in the same order
        # rather than in whichever order they happened to answer.
        ordered = sorted(found.values(), key=lambda item: (item.display_name, item.device_id))
        return DiscoveryResult(ordered, problem)
    finally:
        sock.close()


def _socket_problem(stage: str, exc: Optional[OSError]) -> DiscoveryProblem:
    detail = ": {}".format(exc) if exc else ""
    denied = bool(exc and getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM))
    if stage == "receive":
        return DiscoveryProblem(
            "receive",
            "A networking error occurred while waiting for PiTrac replies{}".format(detail),
            "Check the network connection and firewall, then search again.",
        )
    if denied or sys_platform_is_macos():
        return DiscoveryProblem(
            "permission",
            "This computer could not send discovery traffic{}. Local Network permission may be denied.".format(detail),
            "On macOS, open System Settings → Privacy & Security → Local Network and allow "
            "PiTrac Easy-Connect. On Windows or Linux, allow it through the firewall.",
        )
    return DiscoveryProblem(
        "network",
        "This computer could not send discovery traffic{}".format(detail),
        "Connect to the same network as PiTrac, check the firewall, then search again.",
    )


def sys_platform_is_macos() -> bool:
    import sys

    return sys.platform == "darwin"


def _is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def _dedupe(values: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


#: NetworkManager gives a shared connection the first of these that nothing else
#: is using: 10.42.0.1, and then 10.42.1.1 and so on.
SETUP_NETWORKS = ipaddress.IPv4Network("10.42.0.0/16")
USUAL_SETUP_ADDRESS = "10.42.0.1"


def setup_addresses(own: Optional[Sequence[str]] = None) -> List[str]:
    """Where an enclosure answers on its own Wi-Fi, judged from this computer's.

    A computer that has joined that Wi-Fi was given an address beside the
    enclosure's, so the enclosure's is the first in the same network. The usual
    one is always tried too. Whatever answers still has to prove which enclosure
    it is.
    """

    found = []
    for address in _own_addresses() if own is None else own:
        try:
            here = ipaddress.IPv4Address(address)
        except ValueError:
            continue
        if here in SETUP_NETWORKS:
            found.append(str(ipaddress.IPv4Network("{}/24".format(here), strict=False)[1]))
    return _dedupe([*found, USUAL_SETUP_ADDRESS])


def _own_addresses() -> List[str]:
    try:
        import psutil

        return [entry.address for entries in psutil.net_if_addrs().values()
                for entry in entries if entry.family == socket.AF_INET]
    except Exception:
        return []


def _network_broadcasts() -> List[str]:
    """Broadcast targets for every active, broadcast-capable IPv4 adapter."""

    targets = ["255.255.255.255"]
    try:
        import psutil
    except Exception:
        return targets

    try:
        addresses = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception:
        return targets

    for name, entries in addresses.items():
        state = stats.get(name)
        if state is not None and not state.isup:
            continue
        for entry in entries:
            if entry.family != socket.AF_INET or _is_loopback(entry.address):
                continue
            broadcast = entry.broadcast
            if not broadcast and entry.netmask:
                try:
                    broadcast = str(
                        ipaddress.IPv4Network(
                            "{}/{}".format(entry.address, entry.netmask), strict=False
                        ).broadcast_address
                    )
                except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                    continue
            # Point-to-point VPNs commonly expose a /32 address. Its computed
            # "broadcast" is the adapter's own address and must not be treated
            # as a LAN broadcast target.
            if broadcast and broadcast != entry.address:
                targets.append(broadcast)
    return _dedupe(targets)


def _port(value: Any, default: int = 0) -> Optional[int]:
    """A port from an advertisement, or None if it is not one.

    Anything can send a UDP packet to the discovery port. A reply carrying a
    port of "banana", or 99999, used to raise out of the whole search, so one
    bad packet on the network hid every real enclosure.
    """

    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 65535 else None


#: What a device id may contain. Discovery is unauthenticated -- anything on
#: the network can answer a probe and claim to be an enclosure -- and the id it
#: claims is used as a dictionary key and written into an element attribute by
#: both pages. A reply claiming an id of ``x" autofocus onfocus="..."`` was
#: confirmed to produce a button carrying a live event handler.
#:
#: The pages escape their output now, and this is the second lock: a
#: deliberately loose shape, so a future id format is not rejected here, but
#: nothing that could ever be markup.
_SAFE_DEVICE_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def _parse(data: bytes, address: str) -> Optional[FoundEnclosure]:
    try:
        payload = jsontext.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or not payload.get("deviceId"):
        return None
    if not _SAFE_DEVICE_ID.match(str(payload.get("deviceId", ""))):
        # Not an enclosure this program is willing to talk about.
        return None
    link_port = _port(payload.get("linkPort"))
    portal_port = _port(payload.get("portalPort"), default=80)
    if link_port is None or portal_port is None:
        # A reply that cannot say where to reach it is not an enclosure we can
        # do anything with. Discard it rather than let it stop the search.
        return None

    return FoundEnclosure(
        device_id=str(payload.get("deviceId", "")),
        display_name=str(payload.get("displayName", "PiTrac")),
        address=address,
        reported_address=str(payload.get("address") or ""),
        link_port=link_port,
        version=str(payload.get("version", "")),
        state=str(payload.get("state", "")),
        hostname=str(payload.get("hostname", "")),
        portal_port=portal_port,
        last_seen=time.time(),
    )

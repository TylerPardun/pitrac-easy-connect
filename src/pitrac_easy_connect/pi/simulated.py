"""A fake Raspberry Pi, good enough to test every way Wi-Fi setup can go wrong.

The failures that matter most in this product are the ones that leave a
nontechnical user with an unreachable enclosure: a mistyped password, a router
that never hands out an address, a guest network that blocks the PC, and the
power being pulled in the middle of the change. Reproducing those on real
hardware is slow and unreliable, so they are modelled here instead and driven
from the tests.

This backend is also what lets the whole Pi service run on a Mac during
development.
"""

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .backend import (
    SECURITY_ENTERPRISE,
    SECURITY_OPEN,
    SECURITY_PERSONAL,
    ActiveConnection,
    BackendError,
    CameraInfo,
    PiBackend,
    ServiceStatus,
    SystemFacts,
    WifiNetwork,
)
from .nmcli_backend import HOTSPOT_PROFILE, PROFILE_PREFIX


@dataclass
class FakeAccessPoint:
    """One network in the air around the fake enclosure."""

    ssid: str
    password: str = "correct-horse"
    security: str = SECURITY_PERSONAL
    signal: int = 70
    frequency_mhz: int = 2437
    hidden: bool = False
    #: The router associates the client but never completes DHCP.
    withhold_address: bool = False
    #: A guest network that blocks client-to-client traffic. The join succeeds;
    #: the Companion just never sees the enclosure.
    isolates_clients: bool = False
    #: A hotel-style network that wants a browser sign-in.
    captive_portal: bool = False


@dataclass
class SimulatedPi(PiBackend):
    access_points: List[FakeAccessPoint] = field(default_factory=list)
    country: str = ""
    model: str = "Raspberry Pi 5 Model B Rev 1.1"
    architecture: str = "aarch64"
    os_name: str = "Debian GNU/Linux 13 (trixie)"
    camera_count: int = 2
    temperature_c: float = 44.0
    throttled_flags: int = 0
    free_bytes: int = 45 * 1024**3
    total_bytes: int = 58 * 1024**3
    clock_synchronized: bool = True
    services: Dict[str, bool] = field(default_factory=lambda: {"pitrac-web.service": True})
    running_processes: List[str] = field(default_factory=lambda: ["pitrac_lm"])
    host_name: str = "pitrac"
    supports_checkpoints: bool = True
    #: Set by a test to make the next network operation raise, standing in for
    #: the power being removed part way through.
    fail_next_operation: Optional[str] = None

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._profiles: Dict[str, FakeAccessPoint] = {}
        self._hotspot: Optional[ActiveConnection] = None
        self._active: Optional[ActiveConnection] = None
        self._checkpoints: Dict[str, Optional[ActiveConnection]] = {}
        self._checkpoint_counter = 0
        self.published_mdns: Optional[Dict[str, object]] = None
        self.shutdown_called = False
        self.reboot_called = False
        self.restarted_services: List[str] = []

    # --- helpers used by tests -------------------------------------------

    def add_network(self, *args, **kwargs) -> FakeAccessPoint:
        access_point = FakeAccessPoint(*args, **kwargs)
        self.access_points.append(access_point)
        return access_point

    def _find(self, ssid: str) -> Optional[FakeAccessPoint]:
        for access_point in self.access_points:
            if access_point.ssid == ssid:
                return access_point
        return None

    def _trip(self, operation: str) -> None:
        if self.fail_next_operation == operation:
            self.fail_next_operation = None
            raise BackendError("simulated interruption during {}".format(operation))

    # --- Wireless ---------------------------------------------------------

    def wifi_country(self) -> str:
        return self.country

    def set_wifi_country(self, country: str) -> None:
        code = str(country).strip().upper()
        if len(code) != 2 or not code.isalpha():
            raise BackendError("A country is written as two letters, such as US")
        self.country = code

    def scan(self, rescan: bool = True) -> List[WifiNetwork]:
        self._trip("scan")
        with self._lock:
            active_ssid = self._active.ssid if self._active else ""
            return sorted(
                (
                    WifiNetwork(
                        ssid=access_point.ssid,
                        signal=access_point.signal,
                        security=access_point.security,
                        in_use=access_point.ssid == active_ssid,
                        frequency_mhz=access_point.frequency_mhz,
                    )
                    for access_point in self.access_points
                    if not access_point.hidden
                ),
                key=lambda item: item.signal,
                reverse=True,
            )

    def active_connection(self) -> Optional[ActiveConnection]:
        with self._lock:
            return self._hotspot or self._active

    def saved_profiles(self) -> List[str]:
        with self._lock:
            return sorted(self._profiles)

    def profile_name_for(self, ssid: str) -> str:
        return "{}{}".format(PROFILE_PREFIX, ssid)

    def connect(
        self, ssid: str, password: Optional[str], hidden: bool = False, timeout: float = 45.0
    ) -> ActiveConnection:
        self._trip("connect")
        access_point = self._find(ssid)
        if access_point is None:
            raise BackendError("network not found")
        if access_point.security == SECURITY_ENTERPRISE:
            raise BackendError("802.1X networks are not supported")
        if access_point.security != SECURITY_OPEN and password != access_point.password:
            raise BackendError("Secrets were required, but not provided")
        if access_point.withhold_address:
            raise BackendError("no address was assigned")

        with self._lock:
            self._hotspot = None
            profile = self.profile_name_for(ssid)
            self._profiles[profile] = access_point
            self._active = ActiveConnection(
                profile=profile,
                ssid=ssid,
                ipv4="10.0.0.201/24",
                gateway="10.0.0.1",
                is_hotspot=False,
            )
            return self._active

    def activate_profile(self, profile: str, timeout: float = 45.0) -> ActiveConnection:
        self._trip("activate")
        with self._lock:
            access_point = self._profiles.get(profile)
        if access_point is None:
            raise BackendError("no such profile")
        return self.connect(access_point.ssid, access_point.password)

    def forget_profile(self, profile: str) -> None:
        if not profile.startswith(PROFILE_PREFIX):
            raise BackendError("Easy Connect only removes profiles it created")
        with self._lock:
            self._profiles.pop(profile, None)
            if self._active and self._active.profile == profile:
                self._active = None

    def start_hotspot(self, ssid: str, password: str, timeout: float = 30.0) -> ActiveConnection:
        self._trip("hotspot")
        if len(password) < 8:
            raise BackendError("A hotspot password must be at least 8 characters")
        with self._lock:
            self._active = None
            self._hotspot = ActiveConnection(
                profile=HOTSPOT_PROFILE,
                ssid=ssid,
                ipv4="10.42.0.1/24",
                gateway="",
                is_hotspot=True,
            )
            return self._hotspot

    def stop_hotspot(self) -> None:
        with self._lock:
            self._hotspot = None

    # --- Checkpoints ------------------------------------------------------

    def create_checkpoint(self, rollback_seconds: int) -> Optional[str]:
        if not self.supports_checkpoints:
            return None
        with self._lock:
            self._checkpoint_counter += 1
            token = "/org/freedesktop/NetworkManager/Checkpoint/{}".format(self._checkpoint_counter)
            self._checkpoints[token] = self._hotspot or self._active
            return token

    def rollback_checkpoint(self, token: str) -> None:
        with self._lock:
            if token not in self._checkpoints:
                return
            restored = self._checkpoints.pop(token)
            if restored is None:
                self._active = None
                self._hotspot = None
            elif restored.is_hotspot:
                self._hotspot, self._active = restored, None
            else:
                self._active, self._hotspot = restored, None

    def destroy_checkpoint(self, token: str) -> None:
        with self._lock:
            self._checkpoints.pop(token, None)

    @property
    def open_checkpoints(self) -> List[str]:
        with self._lock:
            return sorted(self._checkpoints)

    def can_reach_gateway(self) -> Optional[bool]:
        with self._lock:
            active = self._active
        if active is None:
            return None
        access_point = self._find(active.ssid)
        if access_point is None:
            return None
        # An isolating network is perfectly healthy from the enclosure's side;
        # it just will not carry traffic between two devices on it.
        return True if access_point.isolates_clients else bool(active.gateway)

    # --- The rest of the machine -----------------------------------------

    def system_facts(self) -> SystemFacts:
        return SystemFacts(
            model=self.model,
            os_name=self.os_name,
            architecture=self.architecture,
            kernel="6.18.39+rpt-rpi-2712",
            temperature_c=self.temperature_c,
            throttled_flags=self.throttled_flags,
            free_bytes=self.free_bytes,
            total_bytes=self.total_bytes,
            uptime_seconds=180.0,
            clock_synchronized=self.clock_synchronized,
        )

    def cameras(self) -> List[CameraInfo]:
        return [CameraInfo(index=i, model="imx296") for i in range(self.camera_count)]

    def service_status(self, name: str) -> ServiceStatus:
        active = self.services.get(name)
        return ServiceStatus(
            name=name,
            present=active is not None,
            active=bool(active),
            detail="active" if active else "inactive",
        )

    def restart_service(self, name: str) -> None:
        self.restarted_services.append(name)
        self.services[name] = True

    def process_running(self, pattern: str) -> bool:
        return any(pattern in process for process in self.running_processes)

    def hostname(self) -> str:
        return self.host_name

    def set_hostname(self, hostname: str) -> None:
        self.host_name = hostname

    def publish_mdns_service(self, name: str, port: int, records: Dict[str, str]) -> None:
        self.published_mdns = {"name": name, "port": port, "records": dict(records)}

    def shutdown(self) -> None:
        self.shutdown_called = True

    def reboot(self) -> None:
        self.reboot_called = True


def home_network_pi(**kwargs) -> SimulatedPi:
    """A fake Pi surrounded by the mix of networks a real house has."""

    backend = SimulatedPi(**kwargs)
    backend.add_network("Ferndale", password="GoodPassword1", signal=82, frequency_mhz=5180)
    backend.add_network("Ferndale-Guest", password="guest", signal=74, isolates_clients=True)
    backend.add_network("Neighbour-2G", password="unknown", signal=41)
    backend.add_network("CoffeeShop", security=SECURITY_OPEN, signal=30, captive_portal=True)
    backend.add_network("Campus", security=SECURITY_ENTERPRISE, signal=55)
    backend.add_network("HiddenLab", password="secretlab", signal=60, hidden=True)
    return backend

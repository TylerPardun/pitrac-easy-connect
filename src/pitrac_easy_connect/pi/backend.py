"""The boundary between Easy Connect and the Raspberry Pi it runs on.

Everything that touches NetworkManager, systemd, the cameras, or the power
button goes through this interface. There are two implementations: the real one
built on ``nmcli`` and friends, and a simulated one used by the tests and by
development on a Mac.

Keeping the boundary this narrow is what makes the Wi-Fi state machine testable.
Losing a network connection is the failure that most needs testing and is the
one you least want to reproduce by hand on real hardware.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Wireless security as the setup page needs to reason about it, not as
# NetworkManager spells it.
SECURITY_OPEN = "open"
SECURITY_PERSONAL = "personal"  # WPA2/WPA3-Personal: one shared password
SECURITY_ENTERPRISE = "enterprise"  # 802.1X: not supported in this release
SECURITY_WEP = "wep"  # obsolete and not supported


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int
    security: str
    in_use: bool = False
    frequency_mhz: int = 0

    @property
    def band(self) -> str:
        if self.frequency_mhz >= 4900:
            return "5 GHz"
        if self.frequency_mhz:
            return "2.4 GHz"
        return ""

    @property
    def supported(self) -> bool:
        return self.security in (SECURITY_PERSONAL, SECURITY_OPEN)

    @property
    def bars(self) -> int:
        """Signal strength as one to four bars, which is what users understand."""

        if self.signal >= 75:
            return 4
        if self.signal >= 55:
            return 3
        if self.signal >= 35:
            return 2
        return 1

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ssid": self.ssid,
            "bars": self.bars,
            "band": self.band,
            "needsPassword": self.security != SECURITY_OPEN,
            "supported": self.supported,
            "security": self.security,
            "inUse": self.in_use,
        }


@dataclass(frozen=True)
class ActiveConnection:
    profile: str
    ssid: str
    ipv4: str
    gateway: str
    device: str = "wlan0"
    is_hotspot: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile,
            "ssid": self.ssid,
            "address": self.ipv4,
            "gateway": self.gateway,
            "isHotspot": self.is_hotspot,
        }


@dataclass(frozen=True)
class SystemFacts:
    model: str = ""
    os_name: str = ""
    architecture: str = ""
    kernel: str = ""
    temperature_c: Optional[float] = None
    throttled_flags: Optional[int] = None
    free_bytes: int = 0
    total_bytes: int = 0
    uptime_seconds: float = 0.0
    clock_synchronized: bool = True

    @property
    def is_supported_hardware(self) -> bool:
        return "Raspberry Pi 5" in self.model and self.architecture in ("aarch64", "arm64")

    @property
    def under_voltage_now(self) -> bool:
        return bool((self.throttled_flags or 0) & 0x1)

    @property
    def throttled_now(self) -> bool:
        return bool((self.throttled_flags or 0) & 0x4)

    @property
    def under_voltage_since_boot(self) -> bool:
        return bool((self.throttled_flags or 0) & 0x10000)

    @property
    def free_percent(self) -> float:
        if not self.total_bytes:
            return 100.0
        return 100.0 * self.free_bytes / self.total_bytes


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    present: bool
    active: bool
    detail: str = ""


@dataclass(frozen=True)
class CameraInfo:
    index: int
    model: str


class BackendError(RuntimeError):
    """A backend operation failed. The caller maps this to a user-facing code."""


class PiBackend:
    """What the Wi-Fi state machine and the self-test are allowed to ask for."""

    # --- Wireless ---------------------------------------------------------

    def wifi_country(self) -> str:
        raise NotImplementedError

    def set_wifi_country(self, country: str) -> None:
        raise NotImplementedError

    def scan(self, rescan: bool = True) -> List[WifiNetwork]:
        raise NotImplementedError

    def active_connection(self) -> Optional[ActiveConnection]:
        raise NotImplementedError

    def saved_profiles(self) -> List[str]:
        """Profile names Easy Connect created. Never includes netplan profiles."""

        raise NotImplementedError

    def connect(
        self, ssid: str, password: Optional[str], hidden: bool = False, timeout: float = 45.0
    ) -> ActiveConnection:
        raise NotImplementedError

    def activate_profile(self, profile: str, timeout: float = 45.0) -> ActiveConnection:
        raise NotImplementedError

    def forget_profile(self, profile: str) -> None:
        raise NotImplementedError

    def profile_name_for(self, ssid: str) -> str:
        """The profile name this backend would create for ``ssid``.

        Recovery after a power cut only has the network name to work from, so
        it needs to be able to name the profile that was being created.
        """

        raise NotImplementedError

    def start_hotspot(self, ssid: str, password: str, timeout: float = 30.0) -> ActiveConnection:
        raise NotImplementedError

    def stop_hotspot(self) -> None:
        raise NotImplementedError

    # --- Rollback safety net ---------------------------------------------

    def create_checkpoint(self, rollback_seconds: int) -> Optional[str]:
        """Ask NetworkManager to undo network changes if we stop responding.

        Returns an opaque token, or ``None`` when the platform cannot provide
        one. A missing checkpoint is not fatal: the state machine has its own
        journal and hotspot fallback. It is defence in depth, not the only
        defence.
        """

        raise NotImplementedError

    def rollback_checkpoint(self, token: str) -> None:
        raise NotImplementedError

    def destroy_checkpoint(self, token: str) -> None:
        raise NotImplementedError

    # --- The rest of the machine -----------------------------------------

    def can_reach_gateway(self) -> Optional[bool]:
        """Whether the router itself answers.

        This is what separates the two reasons a network change fails to be
        confirmed. If the router answers but no computer ever reached the
        enclosure, the network is working and is blocking devices from seeing
        each other, which is what a guest network does. ``None`` means the
        question could not be answered.
        """

        raise NotImplementedError

    def system_facts(self) -> SystemFacts:
        raise NotImplementedError

    def cameras(self) -> List[CameraInfo]:
        raise NotImplementedError

    def service_status(self, name: str) -> ServiceStatus:
        raise NotImplementedError

    def restart_service(self, name: str) -> None:
        raise NotImplementedError

    def process_running(self, pattern: str) -> bool:
        raise NotImplementedError

    def hostname(self) -> str:
        raise NotImplementedError

    def set_hostname(self, hostname: str) -> None:
        raise NotImplementedError

    def publish_mdns_service(self, name: str, port: int, records: Dict[str, str]) -> None:
        raise NotImplementedError

    def shutdown(self) -> None:
        raise NotImplementedError

    def reboot(self) -> None:
        raise NotImplementedError


def classify_security(nmcli_security: str) -> str:
    """Turn NetworkManager's security string into one of our four categories."""

    value = (nmcli_security or "").strip().upper()
    if not value or value == "--":
        return SECURITY_OPEN
    if "802.1X" in value or "EAP" in value:
        return SECURITY_ENTERPRISE
    if "WPA" in value or "SAE" in value:
        return SECURITY_PERSONAL
    if "WEP" in value:
        return SECURITY_WEP
    return SECURITY_ENTERPRISE

"""The real Raspberry Pi backend, built on nmcli, busctl, systemd and vcgencmd.

Two rules shape this file.

First, **netplan owns the profiles that shipped with the image.** On the target
Pi, ``/etc/NetworkManager/system-connections/`` is empty and the active Wi-Fi
profile is rendered by netplan at boot. Easy Connect therefore creates only its
own profiles, all prefixed with ``easyconnect-``, and never edits, deletes, or
re-renders a netplan profile. It may deactivate one while the setup hotspot runs
and bring it back afterwards.

Second, **no shell.** Every command is an argument list. SSIDs and passwords
routinely contain spaces, quotes, and non-ASCII characters, and they arrive from
a web form.
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..common.discovery import SERVICE_TYPE
from .backend import (
    ActiveConnection,
    BackendError,
    CameraInfo,
    PiBackend,
    ServiceStatus,
    SystemFacts,
    WifiNetwork,
    classify_security,
)

PROFILE_PREFIX = "easyconnect-"
HOTSPOT_PROFILE = PROFILE_PREFIX + "setup"
WIFI_DEVICE = "wlan0"
AVAHI_SERVICE_FILE = Path("/etc/avahi/services/pitrac-easy-connect.service")


#: Directories to search in addition to PATH. Tools like ``iw`` and
#: ``raspi-config`` live in sbin, which is not on an ordinary user's PATH and is
#: not guaranteed to be on a systemd unit's either. Missing one of these makes a
#: check silently report "not available" on a Pi where it is perfectly present.
_EXTRA_TOOL_DIRS = ("/usr/sbin", "/sbin", "/usr/local/sbin", "/usr/bin", "/bin")


def find_tool(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    for directory in _EXTRA_TOOL_DIRS:
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _run(
    command: Sequence[str], timeout: float = 30.0, check: bool = True
) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BackendError("{} is not installed".format(command[0])) from exc
    except subprocess.TimeoutExpired as exc:
        raise BackendError("{} did not finish in {:.0f}s".format(command[0], timeout)) from exc
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise BackendError(
            "{} failed: {}".format(" ".join(command[:3]), detail[-1] if detail else "no output")
        )
    return completed


def split_terse(line: str) -> List[str]:
    r"""Split one ``nmcli -t`` record.

    nmcli separates fields with ``:`` and escapes a literal colon or backslash
    inside a field as ``\:`` and ``\\``. Wi-Fi names legitimately contain
    colons, so a plain ``line.split(":")`` corrupts them.
    """

    fields: List[str] = []
    current: List[str] = []
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    fields.append("".join(current))
    return fields


class NmcliBackend(PiBackend):
    def __init__(self, device: str = WIFI_DEVICE, sudo: bool = False):
        self.device = device
        self._sudo = sudo

    def _nmcli(self, *args: str, timeout: float = 30.0, check: bool = True):
        command = ["nmcli", *args]
        if self._sudo:
            command = ["sudo", "-n", *command]
        return _run(command, timeout=timeout, check=check)

    # --- Wireless ---------------------------------------------------------

    def wifi_country(self) -> str:
        iw = find_tool("iw")
        if iw is None:
            return ""
        result = _run([iw, "reg", "get"], timeout=5, check=False)
        match = re.search(r"country\s+([A-Z]{2})", result.stdout or "")
        if match and match.group(1) != "00":
            return match.group(1)
        return ""

    def set_wifi_country(self, country: str) -> None:
        code = str(country).strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", code):
            raise BackendError("A country is written as two letters, such as US")
        # raspi-config persists the regulatory domain across reboots, which a
        # bare "iw reg set" does not. Fall back to iw when it is absent.
        raspi_config = find_tool("raspi-config")
        iw = find_tool("iw")
        if raspi_config:
            _run([raspi_config, "nonint", "do_wifi_country", code], timeout=30)
        elif iw:
            _run([iw, "reg", "set", code], timeout=10)
        else:
            raise BackendError("This system has no way to set the wireless country")

    def scan(self, rescan: bool = True) -> List[WifiNetwork]:
        result = self._nmcli(
            "-t",
            "-f",
            "SSID,SIGNAL,SECURITY,IN-USE,FREQ",
            "dev",
            "wifi",
            "list",
            "--rescan",
            "yes" if rescan else "no",
            timeout=45,
        )
        strongest: Dict[str, WifiNetwork] = {}
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            fields = split_terse(line)
            if len(fields) < 5:
                continue
            ssid = fields[0]
            if not ssid:
                continue  # a hidden network; it has to be typed in by name
            try:
                signal = int(fields[1])
            except ValueError:
                signal = 0
            frequency = 0
            match = re.search(r"(\d+)", fields[4])
            if match:
                frequency = int(match.group(1))
            network = WifiNetwork(
                ssid=ssid,
                signal=signal,
                security=classify_security(fields[2]),
                in_use=fields[3].strip() == "*",
                frequency_mhz=frequency,
            )
            # A router broadcasting on both bands appears twice. Show the
            # strongest, and keep the in-use flag from whichever entry has it.
            existing = strongest.get(ssid)
            if existing is None or network.signal > existing.signal:
                strongest[ssid] = network
            if existing is not None and existing.in_use and not strongest[ssid].in_use:
                strongest[ssid] = WifiNetwork(
                    strongest[ssid].ssid,
                    strongest[ssid].signal,
                    strongest[ssid].security,
                    True,
                    strongest[ssid].frequency_mhz,
                )
        return sorted(strongest.values(), key=lambda item: item.signal, reverse=True)

    def active_connection(self) -> Optional[ActiveConnection]:
        result = self._nmcli(
            "-t", "-f", "NAME,TYPE,DEVICE", "con", "show", "--active", timeout=15
        )
        profile = ""
        for line in result.stdout.splitlines():
            fields = split_terse(line)
            if len(fields) >= 3 and fields[1] == "802-11-wireless" and fields[2] == self.device:
                profile = fields[0]
                break
        if not profile:
            return None

        details = self._nmcli(
            "-t",
            "-f",
            "IP4.ADDRESS,IP4.GATEWAY,GENERAL.CONNECTION",
            "dev",
            "show",
            self.device,
            timeout=15,
            check=False,
        )
        address = ""
        gateway = ""
        for line in details.stdout.splitlines():
            fields = split_terse(line)
            if len(fields) < 2:
                continue
            if fields[0].startswith("IP4.ADDRESS") and not address:
                address = fields[1]
            elif fields[0] == "IP4.GATEWAY":
                gateway = fields[1] if fields[1] != "--" else ""

        ssid = self._profile_ssid(profile)
        return ActiveConnection(
            profile=profile,
            ssid=ssid,
            ipv4=address,
            gateway=gateway,
            device=self.device,
            is_hotspot=profile == HOTSPOT_PROFILE,
        )

    def _profile_ssid(self, profile: str) -> str:
        result = self._nmcli(
            "-t", "-f", "802-11-wireless.ssid", "con", "show", profile, timeout=15, check=False
        )
        for line in result.stdout.splitlines():
            fields = split_terse(line)
            if len(fields) >= 2 and fields[0] == "802-11-wireless.ssid":
                return fields[1]
        return ""

    def saved_profiles(self) -> List[str]:
        result = self._nmcli("-t", "-f", "NAME", "con", "show", timeout=15)
        return [
            name
            for name in (split_terse(line)[0] for line in result.stdout.splitlines() if line.strip())
            if name.startswith(PROFILE_PREFIX) and name != HOTSPOT_PROFILE
        ]

    def all_wifi_profiles(self) -> List[str]:
        result = self._nmcli("-t", "-f", "NAME,TYPE", "con", "show", timeout=15)
        found: List[str] = []
        for line in result.stdout.splitlines():
            fields = split_terse(line)
            if len(fields) >= 2 and fields[1] == "802-11-wireless" and fields[0] != HOTSPOT_PROFILE:
                found.append(fields[0])
        return found

    def known_ssids(self) -> List[str]:
        result = self._nmcli("-t", "-f", "NAME,TYPE", "con", "show", timeout=15)
        found: List[str] = []
        for line in result.stdout.splitlines():
            fields = split_terse(line)
            if len(fields) < 2 or fields[1] != "802-11-wireless":
                continue
            name = fields[0]
            if name == HOTSPOT_PROFILE:
                continue
            try:
                ssid = self._nmcli(
                    "-g", "802-11-wireless.ssid", "con", "show", name, timeout=10
                ).stdout.strip()
            except Exception:
                # One unreadable profile must not cost the whole list.
                continue
            if ssid:
                found.append(ssid)
        return found

    def profile_name_for(self, ssid: str) -> str:
        # Keep the name recognisable but safe as a filename and a CLI argument.
        slug = re.sub(r"[^A-Za-z0-9._-]", "_", ssid)[:48] or "network"
        return "{}{}".format(PROFILE_PREFIX, slug)

    def connect(
        self, ssid: str, password: Optional[str], hidden: bool = False, timeout: float = 45.0
    ) -> ActiveConnection:
        if not ssid:
            raise BackendError("A network name is required")
        profile = self.profile_name_for(ssid)
        self._nmcli("con", "delete", profile, timeout=15, check=False)

        add = [
            "con", "add",
            "type", "wifi",
            "con-name", profile,
            "ifname", self.device,
            "ssid", ssid,
            "connection.autoconnect", "yes",
            # A residence network should win over the setup hotspot, which is
            # only ever brought up deliberately.
            "connection.autoconnect-priority", "10",
        ]
        if hidden:
            add += ["802-11-wireless.hidden", "yes"]
        if password:
            add += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
        self._nmcli(*add, timeout=20)

        try:
            self._nmcli("con", "up", profile, timeout=timeout)
        except BackendError:
            self._nmcli("con", "delete", profile, timeout=15, check=False)
            raise

        connection = self._wait_for_address(profile, timeout=timeout)
        if connection is None:
            self._nmcli("con", "down", profile, timeout=15, check=False)
            raise BackendError("no address was assigned")
        return connection

    def _wait_for_address(self, profile: str, timeout: float) -> Optional[ActiveConnection]:
        deadline = time.monotonic() + min(timeout, 30.0)
        while time.monotonic() < deadline:
            connection = self.active_connection()
            if connection and connection.profile == profile and connection.ipv4:
                return connection
            time.sleep(1.0)
        return None

    def activate_profile(self, profile: str, timeout: float = 45.0) -> ActiveConnection:
        self._nmcli("con", "up", profile, timeout=timeout)
        connection = self.active_connection()
        if connection is None:
            raise BackendError("{} did not come up".format(profile))
        return connection

    def forget_profile(self, profile: str) -> None:
        if not profile.startswith(PROFILE_PREFIX):
            # Refusing here is the guard that keeps a "reset network" action
            # from deleting the netplan profile the image shipped with.
            raise BackendError("Easy-Connect only removes profiles it created")
        self._nmcli("con", "delete", profile, timeout=15)

    def start_hotspot(self, ssid: str, password: str, timeout: float = 30.0) -> ActiveConnection:
        if len(password) < 8:
            raise BackendError("A hotspot password must be at least 8 characters")
        self._nmcli("con", "delete", HOTSPOT_PROFILE, timeout=15, check=False)
        self._nmcli(
            "con", "add",
            "type", "wifi",
            "con-name", HOTSPOT_PROFILE,
            "ifname", self.device,
            "ssid", ssid,
            "connection.autoconnect", "no",
            "802-11-wireless.mode", "ap",
            # 2.4 GHz reaches further and every PC and phone supports it. The
            # setup network only carries a web form.
            "802-11-wireless.band", "bg",
            "ipv4.method", "shared",
            "ipv6.method", "ignore",
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.proto", "rsn",
            "wifi-sec.pairwise", "ccmp",
            "wifi-sec.group", "ccmp",
            "wifi-sec.psk", password,
            timeout=20,
        )
        self._nmcli("con", "up", HOTSPOT_PROFILE, timeout=timeout)
        connection = self.active_connection()
        if connection is None:
            raise BackendError("the setup hotspot did not start")
        return connection

    def stop_hotspot(self) -> None:
        self._nmcli("con", "down", HOTSPOT_PROFILE, timeout=20, check=False)

    # --- NetworkManager checkpoints --------------------------------------

    def create_checkpoint(self, rollback_seconds: int) -> Optional[str]:
        if find_tool("busctl") is None:
            return None
        # An empty device array means "every device". Flag 0x1 asks
        # NetworkManager to destroy the checkpoint automatically once it rolls
        # back, so a crashed Easy Connect still leaves a clean system.
        result = _run(
            [
                find_tool("busctl") or "busctl", "call",
                "org.freedesktop.NetworkManager",
                "/org/freedesktop/NetworkManager",
                "org.freedesktop.NetworkManager",
                "CheckpointCreate", "aouu", "0", str(int(rollback_seconds)), "1",
            ],
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            return None
        match = re.search(r'"(/org/freedesktop/NetworkManager/Checkpoint/\d+)"', result.stdout)
        return match.group(1) if match else None

    def rollback_checkpoint(self, token: str) -> None:
        _run(
            [
                find_tool("busctl") or "busctl", "call",
                "org.freedesktop.NetworkManager",
                "/org/freedesktop/NetworkManager",
                "org.freedesktop.NetworkManager",
                "CheckpointRollback", "o", token,
            ],
            timeout=60,
            check=False,
        )

    def destroy_checkpoint(self, token: str) -> None:
        _run(
            [
                find_tool("busctl") or "busctl", "call",
                "org.freedesktop.NetworkManager",
                "/org/freedesktop/NetworkManager",
                "org.freedesktop.NetworkManager",
                "CheckpointDestroy", "o", token,
            ],
            timeout=15,
            check=False,
        )

    def can_reach_gateway(self) -> Optional[bool]:
        connection = self.active_connection()
        gateway = connection.gateway if connection else ""
        if not gateway:
            return None
        # A refused or reset connection still proves the router answered, which
        # is the only thing being asked here.
        import socket

        try:
            with socket.create_connection((gateway, 80), timeout=2.0):
                return True
        except (ConnectionRefusedError, ConnectionResetError):
            return True
        except OSError:
            return False

    # --- The rest of the machine -----------------------------------------

    def system_facts(self) -> SystemFacts:
        model = _read_text("/proc/device-tree/model").replace("\x00", "").strip()
        os_name = ""
        for line in _read_text("/etc/os-release").splitlines():
            if line.startswith("PRETTY_NAME="):
                os_name = line.split("=", 1)[1].strip().strip('"')
                break

        temperature = None
        raw_temperature = _read_text("/sys/class/thermal/thermal_zone0/temp").strip()
        if raw_temperature.isdigit():
            temperature = int(raw_temperature) / 1000.0

        throttled = None
        vcgencmd = find_tool("vcgencmd")
        if vcgencmd:
            result = _run([vcgencmd, "get_throttled"], timeout=5, check=False)
            match = re.search(r"0x([0-9a-fA-F]+)", result.stdout or "")
            if match:
                throttled = int(match.group(1), 16)

        try:
            usage = shutil.disk_usage("/")
            free_bytes, total_bytes = usage.free, usage.total
        except OSError:
            free_bytes = total_bytes = 0

        uptime = 0.0
        raw_uptime = _read_text("/proc/uptime").split()
        if raw_uptime:
            try:
                uptime = float(raw_uptime[0])
            except ValueError:
                pass

        synchronized = True
        if find_tool("timedatectl"):
            result = _run(["timedatectl", "show", "-p", "NTPSynchronized"], timeout=5, check=False)
            synchronized = "yes" in (result.stdout or "").lower()

        return SystemFacts(
            model=model,
            os_name=os_name,
            architecture=os.uname().machine,
            kernel=os.uname().release,
            temperature_c=temperature,
            throttled_flags=throttled,
            free_bytes=free_bytes,
            total_bytes=total_bytes,
            uptime_seconds=uptime,
            clock_synchronized=synchronized,
        )

    def cameras(self) -> List[CameraInfo]:
        rpicam = find_tool("rpicam-hello")
        if rpicam is None:
            return []
        result = _run([rpicam, "--list-cameras"], timeout=20, check=False)
        cameras: List[CameraInfo] = []
        for line in (result.stdout or "").splitlines():
            match = re.match(r"\s*(\d+)\s*:\s*(\S+)", line)
            if match:
                cameras.append(CameraInfo(index=int(match.group(1)), model=match.group(2)))
        return cameras

    def service_status(self, name: str) -> ServiceStatus:
        present = _run(
            ["systemctl", "list-unit-files", name], timeout=10, check=False
        ).stdout.count(name) > 0
        state = _run(["systemctl", "is-active", name], timeout=10, check=False).stdout.strip()
        return ServiceStatus(name=name, present=present, active=state == "active", detail=state)

    def restart_service(self, name: str) -> None:
        command = ["systemctl", "restart", name]
        if self._sudo:
            command = ["sudo", "-n", *command]
        _run(command, timeout=60)

    def process_running(self, pattern: str) -> bool:
        return _run(["pgrep", "-f", pattern], timeout=10, check=False).returncode == 0

    def hostname(self) -> str:
        return _run(["hostnamectl", "--static"], timeout=10, check=False).stdout.strip()

    def set_hostname(self, hostname: str) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", hostname):
            raise BackendError("That hostname is not valid")
        command = ["hostnamectl", "set-hostname", hostname]
        if self._sudo:
            command = ["sudo", "-n", *command]
        _run(command, timeout=20)

    def publish_mdns_service(self, name: str, port: int, records: Dict[str, str]) -> None:
        """Advertise over mDNS by writing a static avahi service file.

        The target Pi runs avahi-daemon but does not have ``avahi-publish``
        installed. A file in ``/etc/avahi/services`` is picked up by the daemon
        without any extra package, and it survives a restart of Easy Connect.
        """

        entries = "".join(
            "\n      <txt-record>{}={}</txt-record>".format(_xml(key), _xml(value))
            for key, value in sorted(records.items())
        )
        document = (
            '<?xml version="1.0" standalone="no"?>\n'
            '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
            "<service-group>\n"
            "  <name replace-wildcards=\"no\">{name}</name>\n"
            "  <service>\n"
            "    <type>{service_type}</type>\n"
            "    <port>{port}</port>{records}\n"
            "  </service>\n"
            "</service-group>\n"
        ).format(
            name=_xml(name), service_type=SERVICE_TYPE, port=int(port), records=entries
        )
        try:
            AVAHI_SERVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
            AVAHI_SERVICE_FILE.write_text(document, encoding="utf-8")
        except OSError as exc:
            raise BackendError("could not publish the mDNS service: {}".format(exc)) from exc

    def shutdown(self) -> None:
        command = ["systemctl", "poweroff"]
        if self._sudo:
            command = ["sudo", "-n", *command]
        _run(command, timeout=20, check=False)

    def reboot(self) -> None:
        command = ["systemctl", "reboot"]
        if self._sudo:
            command = ["sudo", "-n", *command]
        _run(command, timeout=20, check=False)


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _xml(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

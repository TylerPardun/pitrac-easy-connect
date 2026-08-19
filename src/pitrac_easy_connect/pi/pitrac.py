"""Easy Connect's dealings with the PiTrac installation already on the Pi.

Easy Connect is a separate service. It does not build, patch, or link against
PiTrac; it reads PiTrac's state and writes four configuration values through the
same file PiTrac's own dashboard uses.

Those four values point PiTrac's simulator output at the local relay:

    gs_config.golf_simulator_interfaces.GSPro.kGSProConnectAddress = 127.0.0.1
    gs_config.golf_simulator_interfaces.GSPro.kGSProConnectPort    = 9210
    gs_config.golf_simulator_interfaces.E6.kE6ConnectAddress       = 127.0.0.1
    gs_config.golf_simulator_interfaces.E6.kE6ConnectPort          = 9248

They are written once, at install time, and never touched again — which is the
whole point of the relay. Moving to a new house changes nothing here.

``user_settings.json`` is shared with PiTrac's dashboard, so it is always merged
rather than replaced, and written atomically so an interrupted save cannot leave
PiTrac with a file it refuses to parse. The nesting matches what PiTrac's own
configuration manager builds from a dotted key.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..common.configstore import atomic_write_bytes
from ..models import Simulator

PITRAC_HOME = Path(os.path.expanduser("~/.pitrac"))
USER_SETTINGS = PITRAC_HOME / "config" / "user_settings.json"
CALIBRATION_DATA = PITRAC_HOME / "config" / "calibration_data.json"
PITRAC_WEB_SERVICE = "pitrac-web.service"
PITRAC_WEB_PORT = 8080


def dashboard_url(address: str = "") -> str:
    """Where PiTrac's own Launch Monitor dashboard lives.

    Easy Connect deliberately does not reproduce any of it. Shot data,
    calibration, and logs already have a good home; this just points there.
    """

    host = (address or "").split("/")[0]
    return "http://{}:{}".format(host, PITRAC_WEB_PORT) if host else ""
PITRAC_PROCESS = "pitrac_lm"

SIMULATOR_KEYS = {
    Simulator.GSPRO: (
        "gs_config.golf_simulator_interfaces.GSPro.kGSProConnectAddress",
        "gs_config.golf_simulator_interfaces.GSPro.kGSProConnectPort",
    ),
    Simulator.E6: (
        "gs_config.golf_simulator_interfaces.E6.kE6ConnectAddress",
        "gs_config.golf_simulator_interfaces.E6.kE6ConnectPort",
    ),
}

#: Calibration is worthless if it came from a different pair of cameras, so the
#: check looks for the intrinsics PiTrac's calibration wizard writes.
CALIBRATION_KEYS = (
    "gs_config.cameras.kCamera1CalibrationMatrix",
    "gs_config.cameras.kCamera2CalibrationMatrix",
)


def get_nested(document: Dict[str, Any], dotted_key: str) -> Any:
    value: Any = document
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def set_nested(document: Dict[str, Any], dotted_key: str, value: Any) -> bool:
    """Set a dotted key, creating the nesting PiTrac's config manager expects."""

    parts = dotted_key.split(".")
    current = document
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        elif not isinstance(current[part], dict):
            return False
        current = current[part]
    current[parts[-1]] = value
    return True


@dataclass(frozen=True)
class PitracStatus:
    settings_readable: bool
    measurement_running: bool
    web_active: bool
    calibrated: bool
    simulator_target: Dict[str, Any]
    relay_configured: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "measurementRunning": self.measurement_running,
            "webActive": self.web_active,
            "calibrated": self.calibrated,
            "simulatorTarget": self.simulator_target,
            "relayConfigured": self.relay_configured,
            "settingsReadable": self.settings_readable,
        }


class PitracInstallation:
    def __init__(
        self,
        settings_path: Path = USER_SETTINGS,
        calibration_path: Path = CALIBRATION_DATA,
    ):
        self.settings_path = Path(settings_path)
        self.calibration_path = Path(calibration_path)

    # --- Reading ----------------------------------------------------------

    def read_settings(self) -> Tuple[Dict[str, Any], bool]:
        """Return PiTrac's user settings and whether the file was usable.

        A missing file is normal — PiTrac runs on defaults until something
        overrides them — and counts as usable with empty contents. A file that
        exists but will not parse counts as unusable, because overwriting it
        would destroy settings the user made in PiTrac's own dashboard.
        """

        try:
            raw = self.settings_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}, True
        except OSError:
            return {}, False
        try:
            document = json.loads(raw)
        except ValueError:
            return {}, False
        return (document, True) if isinstance(document, dict) else ({}, False)

    def read_calibration(self) -> Dict[str, Any]:
        try:
            document = json.loads(self.calibration_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return document if isinstance(document, dict) else {}

    def is_calibrated(self) -> bool:
        calibration = self.read_calibration()
        if not calibration:
            return False
        return all(get_nested(calibration, key) for key in CALIBRATION_KEYS)

    def simulator_target(self, simulator: Simulator) -> Dict[str, Any]:
        settings, _readable = self.read_settings()
        address_key, port_key = SIMULATOR_KEYS[simulator]
        return {
            "address": get_nested(settings, address_key) or "",
            "port": get_nested(settings, port_key),
        }

    def points_at_relay(self, relay_ports: Dict[Simulator, int], host: str = "127.0.0.1") -> bool:
        settings, readable = self.read_settings()
        if not readable:
            return False
        for simulator, port in relay_ports.items():
            address_key, port_key = SIMULATOR_KEYS[simulator]
            if get_nested(settings, address_key) != host:
                return False
            try:
                configured = int(get_nested(settings, port_key) or 0)
            except (TypeError, ValueError):
                return False
            if configured != int(port):
                return False
        return True

    # --- Writing ----------------------------------------------------------

    def point_at_relay(
        self, relay_ports: Dict[Simulator, int], host: str = "127.0.0.1"
    ) -> List[str]:
        """Aim PiTrac's simulator output at the local relay. Returns keys changed."""

        settings, readable = self.read_settings()
        if not readable:
            raise OSError(
                "{} could not be read, so it will not be overwritten".format(self.settings_path)
            )

        changed: List[str] = []
        for simulator, port in relay_ports.items():
            address_key, port_key = SIMULATOR_KEYS[simulator]
            if get_nested(settings, address_key) != host:
                set_nested(settings, address_key, host)
                changed.append(address_key)
            if get_nested(settings, port_key) != int(port):
                set_nested(settings, port_key, int(port))
                changed.append(port_key)

        if changed:
            owner = self._intended_owner()
            payload = (json.dumps(settings, indent=2, sort_keys=True) + "\n").encode("utf-8")
            atomic_write_bytes(self.settings_path, payload)
            self._restore_owner(owner)
        return changed

    def _intended_owner(self) -> Optional[Tuple[int, int]]:
        """Who should own the settings file after we write it.

        Easy Connect runs as root so it can drive NetworkManager, but PiTrac's
        own dashboard runs as ``pitracuser``. If root created this file, the
        dashboard would silently lose the ability to save settings, so the
        existing owner — or the owner of the directory, when the file is new —
        is put back afterwards.
        """

        if not hasattr(os, "chown"):
            return None
        for candidate in (self.settings_path, self.settings_path.parent):
            try:
                info = candidate.stat()
            except OSError:
                continue
            return info.st_uid, info.st_gid
        return None

    def _restore_owner(self, owner: Optional[Tuple[int, int]]) -> None:
        if owner is None or os.geteuid() != 0:
            return
        for path in (
            self.settings_path,
            self.settings_path.with_name(self.settings_path.name + ".bak"),
        ):
            try:
                os.chown(path, owner[0], owner[1])
            except OSError:
                continue

    # --- Reporting --------------------------------------------------------

    def status(self, backend, relay_ports: Dict[Simulator, int]) -> PitracStatus:
        _settings, readable = self.read_settings()
        return PitracStatus(
            settings_readable=readable,
            measurement_running=backend.process_running(PITRAC_PROCESS),
            web_active=backend.service_status(PITRAC_WEB_SERVICE).active,
            calibrated=self.is_calibrated(),
            simulator_target={
                simulator.value: self.simulator_target(simulator) for simulator in SIMULATOR_KEYS
            },
            relay_configured=self.points_at_relay(relay_ports),
        )

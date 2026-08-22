"""Permanent identity for one PiTrac enclosure.

An enclosure's identity must not be its IP address, because that changes every
time it moves house. Instead each enclosure gets a random device ID the first
time Easy Connect starts, and keeps it for life. The ID drives the setup Wi-Fi
name, the ``.local`` hostname, and the owner card, so two enclosures on one
network never collide.

The setup hotspot password is also generated once per device. There is no
fleet-wide default password, and the hotspot is never open.
"""

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .configstore import ConfigStore

# Characters that survive being read off a printed card and typed on a phone.
# I, l, 1, O and 0 are omitted because people confuse them.
_UNAMBIGUOUS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

DEVICE_ID_LENGTH = 8
SETUP_PASSWORD_LENGTH = 12

#: NetworkManager's shared-address mode always puts the enclosure at this
#: address on its own hotspot, so this URL is correct on every enclosure and can
#: be printed before the device is ever powered on.
HOTSPOT_ADDRESS = "10.42.0.1"
HOTSPOT_SETUP_URL = "http://" + HOTSPOT_ADDRESS


def new_device_id() -> str:
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(DEVICE_ID_LENGTH))


def new_setup_password() -> str:
    # WPA2 requires at least 8 characters. Twelve unambiguous characters is
    # about 59 bits, which is far beyond what an offline handshake attack on a
    # hotspot that only exists during setup needs.
    return "".join(secrets.choice(_UNAMBIGUOUS) for _ in range(SETUP_PASSWORD_LENGTH))


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    display_name: str
    hostname: str
    setup_ssid: str
    setup_password: str
    hardware_profile: str

    @property
    def short_id(self) -> str:
        """The four characters shown next to a name when several are on screen."""

        return self.device_id[-4:]

    @property
    def recovery_address(self) -> str:
        """Where to reach this enclosure by name, as it actually answers.

        The generated ``pitrac-<id>.local`` name is only real if the installer
        was allowed to rename the machine, and by default it is not. Printing
        it regardless put an address on the owner card that does not resolve --
        on the very card somebody reads when nothing else is working. So the
        machine's own hostname wins when there is one.
        """

        return "http://{}.local".format(self.effective_hostname)

    @property
    def effective_hostname(self) -> str:
        import socket

        try:
            actual = socket.gethostname().split(".")[0].strip()
        except OSError:
            actual = ""
        return actual.lower() if actual else self.hostname

    def as_dict(self, include_secrets: bool = False) -> Dict[str, Any]:
        value = {
            "deviceId": self.device_id,
            "shortId": self.short_id,
            "displayName": self.display_name,
            "hostname": self.hostname,
            "setupSsid": self.setup_ssid,
            "recoveryAddress": self.recovery_address,
            "hardwareProfile": self.hardware_profile,
        }
        if include_secrets:
            value["setupPassword"] = self.setup_password
        return value

    def owner_card(self) -> str:
        """The text printed on the card that ships inside the enclosure."""

        return "\n".join(
            [
                "PiTrac enclosure: {}".format(self.display_name),
                "Device ID: {}".format(self.device_id),
                "",
                "If PiTrac cannot join a network it creates its own setup signal.",
                "",
                "  Setup Wi-Fi name:     {}".format(self.setup_ssid),
                "  Setup Wi-Fi password: {}".format(self.setup_password),
                "  Setup page:           {}".format(HOTSPOT_SETUP_URL),
                "  Backup address:       {}".format(self.recovery_address),
                "",
                "Keep this card. The password is unique to this enclosure and",
                "is the only way back in if it cannot reach your network.",
            ]
        )


class IdentityStore:
    """Creates the identity once, then returns the same one forever."""

    def __init__(self, path: Path, hardware_profile: str = "v3"):
        self.hardware_profile = hardware_profile
        self._store = ConfigStore(
            path,
            defaults={
                "deviceId": "",
                "displayName": "",
                "setupPassword": "",
                "hardwareProfile": hardware_profile,
            },
            schema_version=1,
            secret=True,
        )
        self._ensure_created()

    def _ensure_created(self) -> None:
        values = self._store.all()
        changes: Dict[str, Any] = {}
        if not values.get("deviceId"):
            changes["deviceId"] = new_device_id()
        if not values.get("setupPassword"):
            changes["setupPassword"] = new_setup_password()
        if not values.get("displayName"):
            device_id = changes.get("deviceId") or values["deviceId"]
            changes["displayName"] = "PiTrac {}".format(device_id[-4:])
        if changes:
            self._store.update(changes)

    @property
    def identity(self) -> DeviceIdentity:
        values = self._store.all()
        device_id = values["deviceId"]
        return DeviceIdentity(
            device_id=device_id,
            display_name=values["displayName"],
            hostname="pitrac-{}".format(device_id.lower()),
            setup_ssid="PiTrac-{}".format(device_id),
            setup_password=values["setupPassword"],
            hardware_profile=values.get("hardwareProfile", self.hardware_profile),
        )

    def rename(self, display_name: str) -> DeviceIdentity:
        cleaned = " ".join(str(display_name).split())
        if not 1 <= len(cleaned) <= 40:
            raise ValueError("Choose a name between 1 and 40 characters")
        if any(character in cleaned for character in "\r\n\t"):
            raise ValueError("A name cannot contain line breaks")
        self._store.set("displayName", cleaned)
        return self.identity

    def restore(self, section: Dict[str, Any]) -> DeviceIdentity:
        """Adopt a saved identity, so a rebuilt card is the same enclosure again.

        This is what keeps a printed owner card correct after the memory card is
        replaced. Every field has to be present and sane, or nothing is changed:
        a half-restored identity would leave the enclosure answering to a name
        whose password no longer works.
        """

        device_id, setup_password, display_name = self.validate(section)

        self._store.update(
            {
                "deviceId": device_id,
                "setupPassword": setup_password,
                "displayName": display_name or "PiTrac {}".format(device_id[-4:]),
                "hardwareProfile": str(section.get("hardwareProfile") or self.hardware_profile),
            }
        )
        return self.identity

    @staticmethod
    def validate(section: Dict[str, Any]):
        """Check a saved identity without applying it.

        Separate from ``restore`` so a caller can find out whether a whole
        backup is usable before it changes anything.
        """

        device_id = str(section.get("deviceId", "")).strip().upper()
        setup_password = str(section.get("setupPassword", ""))
        display_name = " ".join(str(section.get("displayName", "")).split())

        if not device_id or not all(character in _ID_ALPHABET for character in device_id):
            raise ValueError("The backup does not contain a usable device ID")
        if len(device_id) != DEVICE_ID_LENGTH:
            raise ValueError("The backup's device ID is not the right length")
        if not 8 <= len(setup_password) <= 63:
            # 63 is the longest a WPA2 passphrase can be. A longer one would be
            # saved and then rejected by the radio, which is worse than saying
            # so now.
            raise ValueError("The backup does not contain a usable setup password")
        if len(display_name) > 60:
            raise ValueError("The backup's name for this enclosure is too long")
        return device_id, setup_password, display_name

    def regenerate_setup_password(self) -> DeviceIdentity:
        self._store.set("setupPassword", new_setup_password())
        return self.identity

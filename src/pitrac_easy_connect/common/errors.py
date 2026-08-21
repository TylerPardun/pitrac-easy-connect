"""The stable user-facing error catalogue.

Every failure a user can see has a permanent code such as ``PT-NET-004``. The
code appears on screen, in the support report, and in the beginner guide, so a
person can describe a problem precisely without reading a log file.

Each entry answers the three questions the product requirements demand of an
error message: what failed, what is still safe, and exactly what to do next.
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    failed: str
    still_safe: str
    next_step: str

    def as_dict(self, detail: Optional[str] = None) -> Dict[str, str]:
        value = {
            "code": self.code,
            "failed": self.failed,
            "stillSafe": self.still_safe,
            "nextStep": self.next_step,
        }
        if detail:
            value["detail"] = detail
        return value


class EasyConnectError(Exception):
    """An error that carries a catalogue entry a user can act on."""

    def __init__(self, info: ErrorInfo, detail: str = ""):
        super().__init__("{}: {}".format(info.code, detail or info.failed))
        self.info = info
        self.detail = detail

    def as_dict(self) -> Dict[str, str]:
        return self.info.as_dict(self.detail)


_CATALOGUE: Dict[str, ErrorInfo] = {}


def _define(code: str, failed: str, still_safe: str, next_step: str) -> ErrorInfo:
    info = ErrorInfo(code, failed, still_safe, next_step)
    _CATALOGUE[code] = info
    return info


def lookup(code: str) -> Optional[ErrorInfo]:
    return _CATALOGUE.get(code)


def catalogue() -> Dict[str, ErrorInfo]:
    return dict(_CATALOGUE)


# Network and Wi-Fi provisioning -------------------------------------------

NET_WRONG_PASSWORD = _define(
    "PT-NET-001",
    "The Wi-Fi password was not accepted by that network.",
    "Your previous network and all your settings were kept. PiTrac put its own setup signal back.",
    "Rejoin the PiTrac setup signal and enter the password again. Watch for capital letters.",
)
NET_NOT_FOUND = _define(
    "PT-NET-002",
    "That network name was not found nearby.",
    "Nothing was changed. PiTrac is still using its setup signal.",
    "Move PiTrac closer to the router, or choose the network from the list instead of typing it.",
)
NET_NO_ADDRESS = _define(
    "PT-NET-003",
    "PiTrac joined the network but the router never gave it an address.",
    "Your previous network was kept and the setup signal is available again.",
    "Restart your router, then try again. If it keeps failing, use Direct Mode.",
)
NET_ISOLATED = _define(
    "PT-NET-004",
    "PiTrac joined the network, but that network blocks devices from talking to each other.",
    "Your settings and calibration were kept, and PiTrac went back to what worked before.",
    "This is usually a guest network, or a network that needs a web sign-in. Choose your "
    "normal home network, or use Direct Mode.",
)

# PT-NET-005 was a separate code for captive portals. It was removed because
# nothing could detect one, so it was documented but never shown. A captive
# portal now produces PT-NET-004, which has the same remedy.
NET_ENTERPRISE = _define(
    "PT-NET-006",
    "That network uses a business login that this release does not support.",
    "Nothing was changed.",
    "Use Direct Mode, or choose a home network that uses a single shared password.",
)
NET_COUNTRY_REQUIRED = _define(
    "PT-NET-007",
    "PiTrac does not know which country it is in, so it cannot use Wi-Fi legally yet.",
    "Nothing was changed.",
    "Choose your country on the setup page. This only has to be done once.",
)
NET_HOTSPOT_FAILED = _define(
    "PT-NET-008",
    "PiTrac could not start its own setup signal.",
    "Saved networks, pairings, and calibration were kept.",
    "Unplug PiTrac, wait ten seconds, and power it on again. If it repeats, use the recovery steps in the guide.",
)
NET_CONFIRM_TIMEOUT = _define(
    "PT-NET-009",
    "The new network connected, but this computer never confirmed it could reach PiTrac.",
    "PiTrac restored the connection it had before and kept every setting.",
    "Make sure this computer is on the same network, then try again.",
)
NET_INTERRUPTED = _define(
    "PT-NET-010",
    "A network change was interrupted, probably by a power cut.",
    "PiTrac rolled back to the last connection that worked.",
    "Try the network change again. Leave the power connected while it runs.",
)

NET_INVALID_DETAILS = _define(
    "PT-NET-011",
    "That network name or password cannot be used.",
    "Nothing was changed. PiTrac is still on the network it was using.",
    "Wi-Fi names are up to 32 characters and passwords up to 63. Check for stray "
    "line breaks pasted in from somewhere else.",
)
NET_COUNTRY_INVALID = _define(
    "PT-NET-012",
    "That is not a country PiTrac recognises.",
    "Nothing was changed.",
    "Choose your country from the list on the setup page.",
)

# Pairing and ownership -----------------------------------------------------

PAIR_NOT_ACCEPTING = _define(
    "PT-PAIR-001",
    "PiTrac is not letting new computers connect right now.",
    "No computer was given access.",
    "On the PiTrac setup page, open Advanced and press Pair another computer, "
    "then try again within five minutes.",
)
PAIR_EXCHANGE_LOST = _define(
    "PT-PAIR-002",
    "That connection attempt did not finish in time.",
    "No computer was given access.",
    "Press Connect again.",
)
PAIR_RATE_LIMITED = _define(
    "PT-PAIR-003",
    "Too many connection attempts were refused.",
    "No computer was given access and your settings are untouched.",
    "Wait a few minutes, then try once more.",
)
PAIR_NOT_PAIRED = _define(
    "PT-PAIR-004",
    "This computer is not paired with that PiTrac.",
    "Nothing was changed on the enclosure.",
    "In Easy-Connect, press Search and choose that PiTrac to connect again.",
)
PAIR_REVOKED = _define(
    "PT-PAIR-005",
    "This computer's access was removed from that PiTrac.",
    "Nothing was changed on the enclosure.",
    "Ask the owner to press Pair another computer on the PiTrac setup page.",
)

# Enclosure hardware and services ------------------------------------------

PI_NO_CAMERA = _define(
    "PT-PI-001",
    "PiTrac cannot see the cameras it needs to measure a shot.",
    "Your networks, pairings, and calibration were kept.",
    "Power PiTrac off, check that both camera ribbon cables are fully seated, and power it on again.",
)
PI_NO_CALIBRATION = _define(
    "PT-PI-002",
    "The cameras are connected but have not been calibrated.",
    "Networking and pairing are working normally.",
    "Run the calibration steps in the guide before playing.",
)
PI_MEASURE_STOPPED = _define(
    "PT-PI-003",
    "The PiTrac measurement program is not running.",
    "Your settings, calibration, and pairings were kept.",
    "Press Restart PiTrac on the maintenance screen.",
)
PI_WEB_STOPPED = _define(
    "PT-PI-004",
    "The PiTrac dashboard service is not running.",
    "Nothing was lost. Easy-Connect is still reachable.",
    "Press Restart PiTrac on the maintenance screen, then reload the dashboard.",
)
PI_LOW_STORAGE = _define(
    "PT-PI-005",
    "The memory card is nearly full.",
    "PiTrac is still running, but updates and shot images are paused.",
    "Open the maintenance screen and remove old shot images, or fit a larger card.",
)
PI_OVERHEAT = _define(
    "PT-PI-006",
    "PiTrac is running hot enough that it has slowed itself down.",
    "No settings were lost.",
    "Improve airflow around the enclosure and keep it out of direct sun.",
)
PI_UNDERVOLT = _define(
    "PT-PI-007",
    "PiTrac is not getting enough power.",
    "No settings were lost, but measurements may be unreliable.",
    "Use the supplied power supply plugged directly into a wall outlet, not a hub or extension.",
)
PI_CLOCK_WRONG = _define(
    "PT-PI-008",
    "PiTrac's clock is wrong, so it cannot safely check downloads.",
    "Play and setup still work normally.",
    "Connect PiTrac to a network with internet access for a minute so it can set its clock.",
)
PI_CONFIG_CORRUPT = _define(
    "PT-PI-009",
    "A settings file was damaged, most likely by a power cut.",
    "PiTrac restored the last good copy of that file.",
    "Check your simulator choice on the setup page. Everything else was recovered.",
)
PI_NO_MODELS = _define(
    "PT-PI-011",
    "PiTrac's ball-detection models are not installed.",
    "Everything else is working; PiTrac just cannot recognise a ball yet.",
    "The models come from PiTracLM and are licensed to you directly by them. "
    "Open the PiTrac setup page and follow the step for installing them.",
)
PI_UNSUPPORTED_HARDWARE = _define(
    "PT-PI-010",
    "This is not a supported Raspberry Pi model or operating system for this release.",
    "Nothing was changed.",
    "Easy-Connect needs a Raspberry Pi 5 running 64-bit Raspberry Pi OS. See the guide.",
)

# Companion and the link between the PC and the enclosure -------------------

LINK_NOT_FOUND = _define(
    "PT-LINK-001",
    "This computer could not find any PiTrac on the network.",
    "Nothing was changed on the enclosure.",
    "Check that PiTrac has power and that this computer is on the same network, then press Search again.",
)
LINK_LOST = _define(
    "PT-LINK-002",
    "The connection to PiTrac was lost.",
    "Your settings and calibration are safe on the enclosure.",
    "Wait a few seconds while it reconnects. If it does not, check that PiTrac still has power.",
)
LINK_VERSION_MISMATCH = _define(
    "PT-LINK-003",
    "The PiTrac enclosure and this computer are running versions that cannot work together.",
    "Nothing was changed and no shots were sent.",
    "Install the update on the side the screen names. The versions are listed on the maintenance screen.",
)
LINK_NO_COMPUTER = _define(
    "PT-LINK-005",
    "No paired computer is connected to PiTrac yet.",
    "Everything on the enclosure is working and nothing was changed.",
    "Open PiTrac Easy-Connect on your Windows PC. It will find this enclosure and connect.",
)
LINK_PORTAL_UNREACHABLE = _define(
    "PT-LINK-006",
    "PiTrac was found, but its setup page did not answer.",
    "Nothing was changed on the enclosure.",
    "Wait a few seconds and try again. If it repeats, restart PiTrac by unplugging it, "
    "waiting ten seconds, and plugging it back in.",
)
LINK_BUSY = _define(
    "PT-LINK-004",
    "Another computer is already connected to that PiTrac.",
    "Nothing was changed.",
    "Close Easy-Connect on the other computer, or remove it from the trusted list on the maintenance screen.",
)

# Simulators ----------------------------------------------------------------

SIM_NOT_RUNNING = _define(
    "PT-SIM-001",
    "The golf simulator is not accepting connections on this computer.",
    "PiTrac is healthy and no shots were lost.",
    "Start the simulator and open its launch-monitor or Open Connect screen, then check again.",
)
SIM_NOT_ARMED = _define(
    "PT-SIM-002",
    "The simulator is running but is not ready to receive a shot.",
    "PiTrac is healthy and no shots were lost.",
    "In the simulator, step onto the tee so it asks for a shot, then check again.",
)
SIM_REJECTED_SHOT = _define(
    "PT-SIM-003",
    "The simulator received the shot but did not accept it.",
    "PiTrac is healthy. The shot was not scored.",
    "Confirm the simulator is set to an external launch monitor, then send another test shot.",
)
SIM_NO_RESPONSE = _define(
    "PT-SIM-004",
    "The simulator did not answer in time.",
    "PiTrac is healthy and nothing was changed.",
    "Restart the simulator, wait for its main screen, then check the connection again.",
)
SIM_BAD_RESPONSE = _define(
    "PT-SIM-005",
    "The simulator sent a reply Easy-Connect does not understand.",
    "No shot was scored and nothing was changed.",
    "Check that the simulator version is one this release supports. The versions are in the guide.",
)

# Configuration and storage -------------------------------------------------

CFG_WRITE_FAILED = _define(
    "PT-CFG-001",
    "A setting could not be saved.",
    "The previous setting is still in place and still valid.",
    "Check free space on the maintenance screen, then try again.",
)
CFG_SCHEMA_NEWER = _define(
    "PT-CFG-002",
    "These settings were written by a newer version of Easy-Connect.",
    "The settings file was left untouched.",
    "Update Easy-Connect on this enclosure, then open this screen again.",
)
CFG_BACKUP_INVALID = _define(
    "PT-CFG-003",
    "That backup file is damaged or was changed after it was made.",
    "Your current settings and calibration were not touched.",
    "Use a different backup file. A backup made by this enclosure is the safest choice.",
)
CFG_BACKUP_WRONG_DEVICE = _define(
    "PT-CFG-004",
    "That backup was made by a different PiTrac enclosure.",
    "Your current settings and calibration were not touched.",
    "Restoring calibration from another enclosure would give wrong shot data. Use this enclosure's own backup.",
)

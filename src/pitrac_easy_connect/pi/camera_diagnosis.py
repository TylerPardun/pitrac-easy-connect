"""Why a camera is missing, from what the Pi itself already knows.

"0 of 2 cameras detected" is true and useless: reseating cables, editing
config.txt and reinstalling camera software are different jobs, and only one of
them is the fix. The Pi has the evidence to tell them apart, at four levels:

1. config.txt     -- whether the Pi was told to look for cameras at all.
                     With ``camera_auto_detect=1`` (the default) the firmware
                     asks each connector at power-on and loads a camera driver
                     only for the ones that answer.
2. device tree    -- which camera drivers were loaded at boot, from that
                     detection or from an explicit ``dtoverlay=`` line.
3. kernel         -- whether a loaded driver then found its camera, or gave up
                     ("failed to read chip id", error -121 or -5).
4. rpicam-hello   -- whether the camera software can use a camera the kernel
                     has.

The first level that fails is where the cause is. ``gather`` reads them;
``diagnose`` decides, and is a pure function so every branch can be tested
without a Pi.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

#: Camera sensors on Raspberry Pi camera modules and the ones PiTrac supports.
SENSOR = re.compile(r"\b(imx\d{3}|ov\d{4})\b", re.IGNORECASE)
#: Kernel lines about cameras worth showing. Ordinary chatter is left out.
KERNEL_CAMERA = re.compile(r"imx\d{3}|ov\d{4}|rp1-cfe|unicam", re.IGNORECASE)
KERNEL_FAILURE = re.compile(
    r"fail|error|err |-121|-110|-5\b|-19\b|timed out|no response|probe of .* failed",
    re.IGNORECASE,
)
CONFIG_PATHS = ("/boot/firmware/config.txt", "/boot/config.txt")
DEVICE_TREE = "/proc/device-tree"
VIDEO4LINUX = "/sys/class/video4linux"
#: How many kernel lines to keep as evidence.
KERNEL_LINES_KEPT = 8


@dataclass
class CameraEvidence:
    required: int = 2
    #: What rpicam-hello listed, and what it said when it listed nothing.
    listed: int = 0
    rpicam_installed: bool = True
    rpicam_message: str = ""
    #: config.txt, the lines that apply to a Pi 5.
    config_found: bool = False
    auto_detect: bool = True
    overlays: List[str] = field(default_factory=list)
    #: Sensor drivers the device tree enabled at boot.
    expected_sensors: List[str] = field(default_factory=list)
    #: Sensors a driver actually found and registered.
    bound_sensors: List[str] = field(default_factory=list)
    kernel_lines: List[str] = field(default_factory=list)
    kernel_readable: bool = True

    def as_dict(self) -> Dict[str, object]:
        return {
            "required": self.required,
            "listed": self.listed,
            "rpicamInstalled": self.rpicam_installed,
            "rpicamMessage": self.rpicam_message,
            "configFound": self.config_found,
            "autoDetect": self.auto_detect,
            "overlays": list(self.overlays),
            "expectedSensors": list(self.expected_sensors),
            "boundSensors": list(self.bound_sensors),
            "kernelLines": list(self.kernel_lines),
        }


@dataclass(frozen=True)
class Diagnosis:
    #: A stable key for the cause, for tests and for anyone reading a report.
    cause: str
    #: What is wrong, in a sentence.
    finding: str
    #: What to do about it.
    fix: str

    def as_dict(self) -> Dict[str, str]:
        return {"cause": self.cause, "finding": self.finding, "fix": self.fix}


CABLE_FIX = (
    "Power off. At both ends of each ribbon, lift the latch, push the cable fully in "
    "with the contacts facing the way the Raspberry Pi camera guide shows, and close "
    "the latch. A Pi 5 needs the 22-pin to 15-pin Pi 5 camera cable; a 15-to-15 cable "
    "does not fit its connectors. Then swap cables between the cameras to see whether "
    "the fault follows the cable or the camera."
)


def diagnose(evidence: CameraEvidence) -> Diagnosis:
    """The first level at which the cameras go missing."""

    need = evidence.required
    if evidence.listed >= need:
        return Diagnosis("ok", "All cameras are working.", "")

    if not evidence.rpicam_installed:
        return Diagnosis(
            "no-camera-software",
            "The camera software (rpicam-apps) is not installed, so no camera can be checked.",
            "Install PiTrac again with its installer, which installs the camera software.",
        )

    expected = len(evidence.expected_sensors)
    bound = len(evidence.bound_sensors)
    failures = [line for line in evidence.kernel_lines if KERNEL_FAILURE.search(line)]

    # Level 4: the kernel has the cameras; the camera software cannot use them.
    if bound >= need or (bound > evidence.listed and bound > 0):
        return Diagnosis(
            "camera-software",
            "The Pi has {} camera(s) working at the hardware level, but the camera software "
            "lists {}.{}".format(
                bound, evidence.listed,
                " It said: " + evidence.rpicam_message if evidence.rpicam_message else "",
            ),
            "Restart PiTrac in case another program is holding the cameras. If that does not "
            "help, update the Pi's software and the camera apps (rpicam-apps, libcamera).",
        )

    # Level 3: a driver was loaded for a camera, and the camera did not answer it.
    if expected > bound:
        return Diagnosis(
            "camera-not-answering",
            "The Pi is set to use {} camera(s) ({}), but {} did not answer when it started"
            "{}.".format(
                expected, ", ".join(evidence.expected_sensors), expected - bound,
                " (the kernel reported: " + failures[-1] + ")" if failures else "",
            ),
            CABLE_FIX,
        )

    # Level 1-2: no driver was loaded at all.
    if evidence.config_found and not evidence.auto_detect and not evidence.overlays:
        return Diagnosis(
            "not-configured",
            "config.txt turns camera detection off (camera_auto_detect=0) and names no "
            "camera, so the Pi never looks for one.",
            "In /boot/firmware/config.txt set camera_auto_detect=1, or add "
            "dtoverlay=imx296,cam0 and dtoverlay=imx296,cam1, then restart the Pi.",
        )
    if evidence.auto_detect:
        return Diagnosis(
            "nothing-answered-at-power-on",
            "When the Pi started it asked both camera connectors for a camera, and {} "
            "answered. This is a connection problem, not a software one.".format(
                "none" if expected == 0 else "only {}".format(expected)
            ),
            CABLE_FIX,
        )
    return Diagnosis(
        "overlay-not-loaded",
        "config.txt names a camera ({}), but the Pi did not load it.".format(
            ", ".join(evidence.overlays)
        ),
        "Check the dtoverlay line in /boot/firmware/config.txt is spelled right and is not "
        "inside a [pi4] or other section that does not apply, then restart the Pi.",
    )


# --- Reading the evidence on a real Pi -----------------------------------


def parse_config(text: str) -> Dict[str, object]:
    """camera_auto_detect and camera overlays from the parts of config.txt a Pi 5 reads."""

    auto_detect = True
    overlays: List[str] = []
    applies = True
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        section = re.fullmatch(r"\[(.+)\]", line)
        if section:
            name = section.group(1).strip().lower()
            applies = name in ("all", "pi5") or name.startswith("pi5")
            continue
        if not applies:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().lower(), value.strip()
        if key == "camera_auto_detect":
            auto_detect = value != "0"
        elif key == "dtoverlay" and SENSOR.search(value.split(",", 1)[0]):
            overlays.append(value)
    return {"autoDetect": auto_detect, "overlays": overlays}


def device_tree_sensors(root: str = DEVICE_TREE) -> List[str]:
    """Camera sensors the device tree enabled at boot."""

    found: List[str] = []
    if not os.path.isdir(root):
        return found
    for directory, _dirs, files in os.walk(root):
        if "compatible" not in files:
            continue
        try:
            compatible = Path(directory, "compatible").read_bytes()
        except OSError:
            continue
        match = SENSOR.search(compatible.decode("latin-1"))
        if not match or not re.search(rb"sony,|ovti,", compatible):
            continue
        status = b"okay"
        if "status" in files:
            try:
                status = Path(directory, "status").read_bytes().strip(b"\0").strip()
            except OSError:
                pass
        if status in (b"okay", b"ok"):
            found.append(match.group(1).lower())
    return found


def bound_sensors(root: str = VIDEO4LINUX) -> List[str]:
    """Sensors a driver found and registered (v4l2 sub-devices named after them)."""

    found: List[str] = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return found
    for entry in entries:
        try:
            name = Path(root, entry, "name").read_text().strip()
        except OSError:
            continue
        match = SENSOR.search(name)
        if match:
            found.append(name)
    return found


def gather(
    run: Callable[[List[str], float], "tuple"],
    find_tool: Callable[[str], Optional[str]],
    listed: int,
    required: int = 2,
    config_paths=CONFIG_PATHS,
    device_tree: str = DEVICE_TREE,
    video4linux: str = VIDEO4LINUX,
) -> CameraEvidence:
    """Read every level. ``run(command, timeout)`` returns (returncode, stdout, stderr)."""

    evidence = CameraEvidence(required=required, listed=listed)

    rpicam = find_tool("rpicam-hello")
    evidence.rpicam_installed = rpicam is not None
    if rpicam is not None and listed < required:
        try:
            _code, out, err = run([rpicam, "--list-cameras"], 20.0)
            said = " ".join((err or out or "").split())
            evidence.rpicam_message = said[:300]
        except Exception:
            pass

    for path in config_paths:
        try:
            text = Path(path).read_text(errors="replace")
        except OSError:
            continue
        parsed = parse_config(text)
        evidence.config_found = True
        evidence.auto_detect = bool(parsed["autoDetect"])
        evidence.overlays = list(parsed["overlays"])
        break

    evidence.expected_sensors = device_tree_sensors(device_tree)
    evidence.bound_sensors = bound_sensors(video4linux)

    lines: List[str] = []
    for command in (["journalctl", "-k", "-b", "-o", "cat", "--no-pager"], ["dmesg"]):
        if find_tool(command[0]) is None:
            continue
        try:
            code, out, _err = run(command, 15.0)
        except Exception:
            continue
        if code == 0 and out:
            lines = [line.strip() for line in out.splitlines() if KERNEL_CAMERA.search(line)]
            break
    else:
        evidence.kernel_readable = False
    evidence.kernel_lines = lines[-KERNEL_LINES_KEPT:]
    return evidence

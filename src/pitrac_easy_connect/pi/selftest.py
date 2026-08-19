"""The checks that stand behind the words READY TO PLAY.

A launch monitor that says it is ready and then does nothing when a ball is
struck is worse than one that says it is not ready. So readiness is not a flag
that gets set when things go well; it is recomputed from these checks, and any
one of the critical ones failing takes it away immediately.

Three outcomes are distinguished on purpose:

``pass``         the check ran and was satisfied
``fail``         the check ran and was not satisfied, with a code and a fix
``warn``         worth showing, but play can continue
``unavailable``  the check could not run on this hardware

``unavailable`` exists so that a check which cannot be performed is never
counted as a pass. On the Pi this project targets, the camera checks are the
ones that matter: an enclosure that is still being assembled must say the
cameras are missing, not quietly leave them out of the total.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..common.errors import (
    PI_CLOCK_WRONG,
    PI_LOW_STORAGE,
    PI_NO_CALIBRATION,
    PI_NO_CAMERA,
    PI_OVERHEAT,
    PI_UNDERVOLT,
    PI_UNSUPPORTED_HARDWARE,
    PI_WEB_STOPPED,
    PI_MEASURE_STOPPED,
    ErrorInfo,
)
from ..common.states import State

PASS = "pass"
FAIL = "fail"
WARN = "warn"
UNAVAILABLE = "unavailable"

#: Below this, an update cannot be staged and shot images stop being written.
LOW_STORAGE_BYTES = 2 * 1024**3
LOW_STORAGE_PERCENT = 5.0
WARM_CELSIUS = 75.0
HOT_CELSIUS = 82.0
REQUIRED_CAMERAS = 2


@dataclass(frozen=True)
class CheckResult:
    key: str
    title: str
    status: str
    detail: str = ""
    error: Optional[ErrorInfo] = None
    critical: bool = False

    @property
    def blocks_play(self) -> bool:
        """A critical check has to actually pass. Anything else blocks play.

        Not just ``fail``: a critical check that could only warn, or could not
        run at all, has not established the thing readiness depends on. The
        simulator check is the one this matters most for — connected but with no
        acknowledged test shot is exactly the state that must not be sold as
        READY TO PLAY.
        """

        return self.critical and self.status != PASS

    def as_dict(self) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "critical": self.critical,
        }
        if self.error is not None:
            value["error"] = self.error.as_dict()
        return value


@dataclass
class SelfTestReport:
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def blocking(self) -> List[CheckResult]:
        return [check for check in self.checks if check.blocks_play]

    @property
    def ready(self) -> bool:
        return not self.blocking

    @property
    def first_problem(self) -> Optional[CheckResult]:
        blocking = self.blocking
        if blocking:
            return blocking[0]
        for check in self.checks:
            if check.status in (FAIL, WARN):
                return check
        return None

    def as_dict(self) -> Dict[str, Any]:
        problem = self.first_problem
        return {
            "ready": self.ready,
            "checks": [check.as_dict() for check in self.checks],
            "summary": {
                "passed": sum(1 for c in self.checks if c.status == PASS),
                "failed": sum(1 for c in self.checks if c.status == FAIL),
                "warnings": sum(1 for c in self.checks if c.status == WARN),
                "unavailable": sum(1 for c in self.checks if c.status == UNAVAILABLE),
            },
            "firstProblem": problem.as_dict() if problem else None,
        }


class SelfTest:
    """Runs every check. Each one is independent and cannot break the others."""

    def __init__(
        self,
        backend,
        pitrac,
        relay_ports: Dict[Any, int],
        network_status: Callable[[], Dict[str, Any]],
        companion_connected: Callable[[], bool],
        simulator_status: Callable[[], Optional[Dict[str, Any]]],
        config_problems: Callable[[], List[str]],
        relay_listening: Optional[Callable[[], bool]] = None,
    ):
        self.backend = backend
        self.pitrac = pitrac
        self.relay_ports = relay_ports
        self.network_status = network_status
        self.companion_connected = companion_connected
        self.simulator_status = simulator_status
        self.config_problems = config_problems
        self.relay_listening = relay_listening

    def run(self) -> SelfTestReport:
        report = SelfTestReport()
        for check in (
            self._hardware,
            self._storage,
            self._temperature,
            self._power,
            self._clock,
            self._configuration,
            self._cameras,
            self._calibration,
            self._pitrac_web,
            self._pitrac_measurement,
            self._pitrac_target,
            self._network,
            self._companion,
            self._simulator,
        ):
            try:
                report.checks.append(check())
            except Exception as exc:
                # A check that throws is a check that did not run. It must not
                # be recorded as a pass, and it must not stop the others.
                report.checks.append(
                    CheckResult(
                        key=check.__name__.lstrip("_"),
                        title=check.__name__.lstrip("_").replace("_", " ").title(),
                        status=UNAVAILABLE,
                        detail="This check could not run: {}".format(exc),
                    )
                )
        return report

    # --- The machine ------------------------------------------------------

    def _hardware(self) -> CheckResult:
        facts = self.backend.system_facts()
        if facts.is_supported_hardware:
            return CheckResult(
                "hardware", "Raspberry Pi model", PASS, "{} · {}".format(facts.model, facts.os_name)
            )
        return CheckResult(
            "hardware",
            "Raspberry Pi model",
            FAIL,
            "{} ({})".format(facts.model or "unknown model", facts.architecture),
            PI_UNSUPPORTED_HARDWARE,
            critical=True,
        )

    def _storage(self) -> CheckResult:
        facts = self.backend.system_facts()
        gigabytes = facts.free_bytes / 1024**3
        if facts.free_bytes < LOW_STORAGE_BYTES or facts.free_percent < LOW_STORAGE_PERCENT:
            return CheckResult(
                "storage",
                "Memory card space",
                FAIL,
                "{:.1f} GB free".format(gigabytes),
                PI_LOW_STORAGE,
                critical=True,
            )
        return CheckResult("storage", "Memory card space", PASS, "{:.1f} GB free".format(gigabytes))

    def _temperature(self) -> CheckResult:
        facts = self.backend.system_facts()
        if facts.temperature_c is None:
            return CheckResult(
                "temperature", "Temperature", UNAVAILABLE, "No temperature sensor was found"
            )
        reading = "{:.0f} °C".format(facts.temperature_c)
        if facts.throttled_now or facts.temperature_c >= HOT_CELSIUS:
            return CheckResult("temperature", "Temperature", FAIL, reading, PI_OVERHEAT, critical=True)
        if facts.temperature_c >= WARM_CELSIUS:
            return CheckResult("temperature", "Temperature", WARN, reading, PI_OVERHEAT)
        return CheckResult("temperature", "Temperature", PASS, reading)

    def _power(self) -> CheckResult:
        facts = self.backend.system_facts()
        if facts.throttled_flags is None:
            return CheckResult("power", "Power supply", UNAVAILABLE, "Power reporting is not available")
        if facts.under_voltage_now:
            return CheckResult(
                "power", "Power supply", FAIL, "Not enough power right now", PI_UNDERVOLT, critical=True
            )
        if facts.under_voltage_since_boot:
            return CheckResult(
                "power", "Power supply", WARN, "Low power was recorded earlier", PI_UNDERVOLT
            )
        return CheckResult("power", "Power supply", PASS, "Steady")

    def _clock(self) -> CheckResult:
        facts = self.backend.system_facts()
        if facts.clock_synchronized:
            return CheckResult("clock", "Clock", PASS, "Set correctly")
        # Play does not need the clock. Verifying a signed download does.
        return CheckResult("clock", "Clock", WARN, "Not set from the internet yet", PI_CLOCK_WRONG)

    def _configuration(self) -> CheckResult:
        problems = self.config_problems()
        if not problems:
            return CheckResult("configuration", "Saved settings", PASS, "All settings files are valid")
        from ..common.errors import PI_CONFIG_CORRUPT

        return CheckResult(
            "configuration",
            "Saved settings",
            WARN,
            "Recovered from a backup copy: {}".format(", ".join(problems)),
            PI_CONFIG_CORRUPT,
        )

    # --- PiTrac itself ----------------------------------------------------

    def _cameras(self) -> CheckResult:
        cameras = self.backend.cameras()
        if len(cameras) >= REQUIRED_CAMERAS:
            return CheckResult(
                "cameras",
                "Cameras",
                PASS,
                "{} cameras detected".format(len(cameras)),
            )
        return CheckResult(
            "cameras",
            "Cameras",
            FAIL,
            "{} of {} cameras detected".format(len(cameras), REQUIRED_CAMERAS),
            PI_NO_CAMERA,
            critical=True,
        )

    def _calibration(self) -> CheckResult:
        if self.pitrac.is_calibrated():
            return CheckResult("calibration", "Camera calibration", PASS, "Calibration data found")
        return CheckResult(
            "calibration",
            "Camera calibration",
            FAIL,
            "No calibration data has been saved",
            PI_NO_CALIBRATION,
            critical=True,
        )

    def _pitrac_web(self) -> CheckResult:
        from .pitrac import PITRAC_WEB_SERVICE

        status = self.backend.service_status(PITRAC_WEB_SERVICE)
        if not status.present:
            return CheckResult(
                "pitracWeb", "PiTrac dashboard", UNAVAILABLE, "The dashboard service is not installed"
            )
        if status.active:
            return CheckResult("pitracWeb", "PiTrac dashboard", PASS, "Running")
        return CheckResult("pitracWeb", "PiTrac dashboard", FAIL, status.detail, PI_WEB_STOPPED)

    def _pitrac_measurement(self) -> CheckResult:
        from .pitrac import PITRAC_PROCESS

        if self.backend.process_running(PITRAC_PROCESS):
            return CheckResult("pitracMeasurement", "PiTrac measurement", PASS, "Running")
        return CheckResult(
            "pitracMeasurement",
            "PiTrac measurement",
            FAIL,
            "The measurement program is not running",
            PI_MEASURE_STOPPED,
            critical=True,
        )

    def _pitrac_target(self) -> CheckResult:
        from ..common.errors import CFG_WRITE_FAILED

        # Both halves have to hold. PiTrac pointed at a port nothing is
        # listening on loses every shot silently, which is the worst possible
        # way for this to fail.
        if self.relay_listening is not None and not self.relay_listening():
            return CheckResult(
                "pitracTarget",
                "Shot delivery",
                FAIL,
                "Easy Connect is not listening for shots",
                CFG_WRITE_FAILED,
                critical=True,
            )
        if not self.pitrac.points_at_relay(self.relay_ports):
            return CheckResult(
                "pitracTarget",
                "Shot delivery",
                FAIL,
                "PiTrac is not pointed at Easy Connect",
                CFG_WRITE_FAILED,
                critical=True,
            )
        return CheckResult(
            "pitracTarget", "Shot delivery", PASS, "PiTrac is sending shots to Easy Connect"
        )

    # --- The path to the simulator ---------------------------------------

    def _network(self) -> CheckResult:
        status = self.network_status()
        connection = status.get("connection")
        if not connection:
            return CheckResult(
                "network", "Network", FAIL, "PiTrac is not on any network", critical=True
            )
        if connection.get("isHotspot"):
            label = "Direct Mode" if status.get("directMode") else "Setup signal"
            return CheckResult(
                "network",
                "Network",
                PASS if status.get("directMode") else WARN,
                "{} · {}".format(label, connection.get("ssid", "")),
            )
        return CheckResult("network", "Network", PASS, "Connected to {}".format(connection.get("ssid", "")))

    def _companion(self) -> CheckResult:
        if self.companion_connected():
            return CheckResult("companion", "Your computer", PASS, "Connected to Easy Connect")
        from ..common.errors import LINK_NO_COMPUTER

        return CheckResult(
            "companion",
            "Your computer",
            FAIL,
            "No paired computer is connected",
            LINK_NO_COMPUTER,
            critical=True,
        )

    def _simulator(self) -> CheckResult:
        status = self.simulator_status()
        if status is None:
            return CheckResult(
                "simulator",
                "Golf simulator",
                UNAVAILABLE,
                "Connect a computer to check the simulator",
                critical=True,
            )
        from ..common.errors import SIM_NOT_RUNNING, lookup

        if status.get("ready"):
            return CheckResult(
                "simulator",
                "Golf simulator",
                PASS,
                "{} accepted a test shot".format(status.get("simulatorLabel", "The simulator")),
            )
        if status.get("connected"):
            return CheckResult(
                "simulator",
                "Golf simulator",
                WARN,
                "{} is connected but no test shot has been accepted".format(
                    status.get("simulatorLabel", "The simulator")
                ),
                critical=True,
            )
        info = lookup(str(status.get("errorCode", ""))) or SIM_NOT_RUNNING
        return CheckResult(
            "simulator",
            "Golf simulator",
            FAIL,
            status.get("message", "") or info.failed,
            info,
            critical=True,
        )


def state_for(report: SelfTestReport, network: Dict[str, Any], companion: bool) -> State:
    """Turn a report into the one word the user sees."""

    if report.ready:
        return State.READY_TO_PLAY

    blocking = {check.key for check in report.blocking}
    connection = network.get("connection") or {}

    if network.get("awaitingConfirmation"):
        return State.CONNECTING

    # "Setup required" is about not being reachable yet, so it only applies
    # while no computer has managed to connect. Once one has — even over the
    # enclosure's own hotspot — setup is over, and the honest thing to report is
    # whatever is actually still wrong.
    if not companion:
        if not connection:
            return State.SETUP_REQUIRED
        if connection.get("isHotspot") and not network.get("directMode"):
            return State.SETUP_REQUIRED

    if blocking & {"hardware", "cameras", "calibration", "pitracMeasurement", "pitracTarget"}:
        return State.RECOVERY_REQUIRED
    if blocking & {"companion"}:
        return State.SETUP_REQUIRED
    if blocking & {"simulator"}:
        return State.SIMULATOR_ACTION_REQUIRED
    return State.RECOVERY_REQUIRED

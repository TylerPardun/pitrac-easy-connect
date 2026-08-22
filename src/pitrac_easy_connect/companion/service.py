"""The Companion: what runs on the Windows simulator PC.

Holds four things together and reports them as one chain, because the whole
point of this product is that a failure names the hop it happened at instead of
saying "disconnected":

    1. PiTrac is measuring        (reported by the enclosure)
    2. The enclosure is linked    (this computer's connection to it)
    3. The simulator is connected (this computer to GSPro or E6)
    4. A test shot was accepted   (the only proof the whole path works)

Everything the Companion stores about an enclosure is scoped to that enclosure's
device ID, so a second PiTrac is a second entry rather than a conflict.
"""

import platform
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import __version__
from ..common import discovery, link
from ..common import pairing_exchange as exchange
from ..common.configstore import ConfigStore
from ..common.errors import (
    LINK_NOT_FOUND,
    PAIR_EXCHANGE_LOST,
    SIM_NOT_RUNNING,
    EasyConnectError,
    lookup,
)
from ..common.states import State
from ..common.updates import Updater
from ..models import TEST_SHOT, Simulator
from .link_client import CompanionLinkClient
from . import shotlog
from .rangeplay import RangeSession
from .shotlog import ShotLog
from .simulator_session import SimulatorSession


def default_config_path() -> Path:
    import os

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    return base / "pitrac-easy-connect" / "companion.json"


def default_computer_name() -> str:
    try:
        return platform.node() or "Windows PC"
    except Exception:
        return "Windows PC"


class CompanionService:
    def __init__(
        self,
        config_path: Optional[Path] = None,
        simulator_ports: Optional[Dict[Simulator, int]] = None,
        simulator_host: str = "127.0.0.1",
        version: str = __version__,
        discovery_port: int = discovery.DISCOVERY_PORT,
        computer_name: Optional[str] = None,
    ):
        self.version = version
        self.simulator_host = simulator_host
        self.discovery_port = discovery_port
        self.computer_name = computer_name or default_computer_name()
        # Always hold a port for every simulator. A caller that overrides only
        # one must not leave the other unmapped, or switching to it later fails
        # with a lookup error instead of a message.
        self.simulator_ports = {simulator: simulator.default_port for simulator in Simulator}
        self.simulator_ports.update(simulator_ports or {})
        self.store = ConfigStore(
            config_path or default_config_path(),
            defaults={
                "simulator": Simulator.GSPRO.value,
                "enclosures": {},
                "activeDeviceId": "",
                #: Set once the owner has been walked through setup. Until then
                #: the app leads them a step at a time instead of presenting a
                #: window full of things to click.
                "setupComplete": False,
            },
            schema_version=1,
            secret=True,
        )
        self._lock = threading.RLock()
        self._link: Optional[CompanionLinkClient] = None
        self._session: Optional[SimulatorSession] = None
        self._found: List[discovery.FoundEnclosure] = []
        self._test_shot_accepted = False
        self._last_simulator_error: Optional[Dict[str, str]] = None
        self._last_shot_at: Optional[float] = None
        self._shots_delivered = 0
        self._shots_lost = 0
        self._pi_status: Dict[str, Any] = {}
        #: The practice range. In memory only: a session is a bucket of balls.
        self.range = RangeSession()
        self._raw_shots: List[Dict[str, Any]] = []
        self.shots = ShotLog(
            (config_path or default_config_path()).with_name("shots.json")
        )
        self.updates = Updater(version)
        # Off the startup path, and silent on failure: a GitHub outage must not
        # stop anyone playing golf.
        self.updates.check_in_background()

    # --- Simulator selection ---------------------------------------------

    @property
    def simulator(self) -> Simulator:
        return Simulator(self.store.get("simulator", Simulator.GSPRO.value))

    def select_simulator(self, name: str) -> Dict[str, Any]:
        try:
            simulator = Simulator(str(name))
        except ValueError as exc:
            raise ValueError("Only GSPro and E6 Connect are supported") from exc
        with self._lock:
            self.store.set("simulator", simulator.value)
            self._test_shot_accepted = False
            self._last_simulator_error = None
            if self._session is not None:
                self._session.close()
                self._session = None
        self.connect_simulator()
        return self.status()

    # --- Finding an enclosure --------------------------------------------

    def search(self, timeout: float = 2.0) -> List[Dict[str, Any]]:
        found = discovery.discover(timeout=timeout, port=self.discovery_port)
        with self._lock:
            self._found = found
            known = self.store.get("enclosures") or {}
        return [
            {**enclosure.as_dict(), "paired": enclosure.device_id in known}
            for enclosure in found
        ]

    def _found_by_id(self, device_id: str) -> Optional[discovery.FoundEnclosure]:
        with self._lock:
            for enclosure in self._found:
                if enclosure.device_id == device_id:
                    return enclosure
        return None

    # --- Pairing ----------------------------------------------------------

    def pair(self, device_id: str, portal_port: Optional[int] = None) -> Dict[str, Any]:
        """Ask an enclosure to connect, and store the secret it hands back.

        There is no code to type. The enclosure decides whether to accept — it
        does while nothing is paired to it, and otherwise only in a window its
        owner opened. The secret is derived from a key exchange rather than
        received, so it is never carried over the network. See
        ``common.pairing_exchange``.
        """

        enclosure = self._found_by_id(device_id)
        if enclosure is None:
            # The caller may not have searched through this object, or the list
            # may be stale. Look again before refusing.
            self.search(timeout=3.0)
            enclosure = self._found_by_id(device_id)
        if enclosure is None:
            raise EasyConnectError(LINK_NOT_FOUND, "that enclosure was not found on this network")

        # The enclosure says where its setup page is; only fall back to the
        # default when an older enclosure did not advertise one.
        port = portal_port or enclosure.portal_port or 80
        base = "http://{}:{}".format(enclosure.address, port)
        hello = _post(base + "/api/pair-hello", None)
        private, public = exchange.client_start()
        key = exchange.shared_key(hello["serverPublic"], private)

        result = _post(
            base + "/api/pair",
            {
                "sessionId": hello["sessionId"],
                "clientPublic": public,
                "computerName": self.computer_name,
            },
        )

        expected = exchange.proof(key, hello["serverPublic"], public, "server")
        if not exchange.verify_proof(expected, result.get("serverProof", "")):
            # The device answered but could not prove it ran the same exchange.
            raise EasyConnectError(
                PAIR_EXCHANGE_LOST, "that device could not prove it is your PiTrac"
            )

        secret = exchange.unmask_secret(key, result["maskedSecret"])
        with self._lock:
            enclosures = dict(self.store.get("enclosures") or {})
            enclosures[device_id] = {
                "pairingId": result["pairingId"],
                "secret": secret,
                "displayName": enclosure.display_name,
                "address": enclosure.address,
                "linkPort": enclosure.link_port,
                "pairedAt": time.time(),
            }
            self.store.update({"enclosures": enclosures, "activeDeviceId": device_id})

        self.connect(device_id)
        return {"deviceId": device_id, "displayName": enclosure.display_name}

    # --- What the launch monitor actually sent -----------------------------

    #: How many raw shot messages to hold. In memory only: this is a window
    #: onto what is arriving now, not a record.
    RAW_SHOTS = 10

    def _keep_raw(self, payload: Dict[str, Any]) -> None:
        import copy

        with self._lock:
            self._raw_shots.append({"at": time.time(), "message": copy.deepcopy(payload)})
            del self._raw_shots[: max(0, len(self._raw_shots) - self.RAW_SHOTS)]

    def raw_shots(self) -> Dict[str, Any]:
        """The last few messages exactly as the launch monitor sent them."""

        with self._lock:
            recent = list(self._raw_shots)
        odd = [
            entry for entry in recent
            if str(entry["message"].get("Units", "") or "").strip().lower()
            not in ("", shotlog.EXPECTED_UNITS)
        ]
        return {
            "shots": recent,
            "expectedUnits": shotlog.EXPECTED_UNITS,
            "unitsUnexpected": bool(odd),
            "declaredUnits": sorted({
                str(e["message"].get("Units", "")) for e in recent
                if e["message"].get("Units")
            }),
        }

    # --- The practice range ------------------------------------------------

    def range_status(self) -> Dict[str, Any]:
        return self.range.status()

    def clear_range(self) -> Dict[str, Any]:
        return self.range.clear()

    def set_range_conditions(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "conditions": self.range.set_conditions(
                pressure_pa=arguments.get("pressurePa"),
                temperature_c=arguments.get("temperatureC"),
                relative_humidity=arguments.get("relativeHumidity"),
            )
        }

    def range_demo_shot(self) -> Dict[str, Any]:
        """Put one plausible shot on the range, so it can be seen working.

        Nothing is sent to a simulator and nothing is written to the shot log:
        this is a drawing, not a measurement, and must never be mistaken for
        one in the history.
        """

        import random

        club, speed, launch, spin = random.choice([
            ("Driver", 167.0, 10.9, 2686),
            ("5 iron", 132.0, 12.1, 5280),
            ("7 iron", 120.0, 16.3, 7097),
            ("Pitching wedge", 102.0, 24.2, 9304),
        ])
        wobble = random.uniform(-1.0, 1.0)
        shot = self.range.record(
            {
                "speed": speed * random.uniform(0.96, 1.03),
                "launch": launch + wobble,
                "direction": random.uniform(-2.5, 2.5),
                "backSpin": spin * random.uniform(0.9, 1.1),
                "sideSpin": random.uniform(-900, 900),
            },
            club,
        )
        return {"shot": shot, "demo": True}

    def finish_setup(self, done: bool = True) -> Dict[str, Any]:
        """Mark the guided setup as over, or send the owner back through it."""

        self.store.set("setupComplete", bool(done))
        return {"setupComplete": bool(done)}

    def forget(self, device_id: str) -> Dict[str, Any]:
        """Give up this computer's access to an enclosure, on both sides.

        Dropping only the local copy would leave the enclosure still trusting
        this computer's secret — so "unpair" would not actually remove access,
        and a stale entry would pile up every time someone did it. Telling the
        enclosure needs the link that is about to be closed, so it happens
        first, and a failure is not fatal: the local half still goes.
        """

        with self._lock:
            record = (self.store.get("enclosures") or {}).get(device_id) or {}
        pairing_id = record.get("pairingId")
        if pairing_id and device_id == self.store.get("activeDeviceId"):
            try:
                self.command("revokeComputer", {"pairingId": pairing_id})
            except EasyConnectError:
                # Not connected, or the enclosure is off. The enclosure keeps
                # the entry; its owner can remove it from the setup page.
                pass

        with self._lock:
            enclosures = dict(self.store.get("enclosures") or {})
            enclosures.pop(device_id, None)
            active = self.store.get("activeDeviceId")
            self.store.update(
                {
                    "enclosures": enclosures,
                    "activeDeviceId": "" if active == device_id else active,
                }
            )
        self.disconnect()
        return self.status()

    @property
    def paired_enclosures(self) -> Dict[str, Any]:
        return self.store.get("enclosures") or {}

    # --- Connecting -------------------------------------------------------

    def connect(self, device_id: str = "") -> Dict[str, Any]:
        with self._lock:
            device_id = device_id or self.store.get("activeDeviceId") or ""
            record = (self.store.get("enclosures") or {}).get(device_id)
        if record is None:
            raise EasyConnectError(LINK_NOT_FOUND, "this computer is not paired with that PiTrac")

        # Discovery is authoritative for the address; the stored one is only a
        # fallback for when the beacon is blocked.
        enclosure = self._found_by_id(device_id)
        if enclosure is None:
            self.search(timeout=3.0)
            enclosure = self._found_by_id(device_id)
        host = enclosure.address if enclosure else record.get("address", "")
        port = (enclosure.link_port if enclosure else 0) or record.get("linkPort") or link.LINK_PORT
        if not host:
            raise EasyConnectError(LINK_NOT_FOUND, "no address is known for that PiTrac")

        self.disconnect()
        client = CompanionLinkClient(
            host,
            int(port),
            record["pairingId"],
            record["secret"],
            self.version,
            self.computer_name,
            on_shot=self._forward_shot,
            on_state=self._on_link_state,
            on_enclosure_status=self._on_enclosure_status,
        )
        with self._lock:
            self._link = client
            self.store.update({"activeDeviceId": device_id})
        client.start()
        self.connect_simulator()
        return self.status()

    def disconnect(self) -> None:
        with self._lock:
            client, self._link = self._link, None
        if client is not None:
            client.stop()

    def _on_enclosure_status(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._pi_status = dict(payload)

    def _on_link_state(self) -> None:
        client = self._link
        if client is not None and client.connected:
            self._report_simulator_state()

    # --- The simulator on this computer -----------------------------------

    def connect_simulator(self) -> bool:
        simulator = self.simulator
        with self._lock:
            session = self._session
            if session is not None and session.simulator is not simulator:
                session.close()
                session = None
            if session is None:
                session = SimulatorSession(
                    simulator,
                    self.simulator_host,
                    self.simulator_ports[simulator],
                    on_message=self._on_simulator_message,
                )
                self._session = session

        connected = session.ensure_connected()
        if not connected:
            self._last_simulator_error = SIM_NOT_RUNNING.as_dict(session.last_error)
        else:
            self._last_simulator_error = None
        self._report_simulator_state()
        return connected

    def _on_simulator_message(self, payload: Dict[str, Any]) -> None:
        # The simulator tells the launch monitor when the player changes club.
        # That message is already going past, so the club comes for free.
        try:
            self.shots.note_simulator_message(payload)
        except Exception:
            pass
        client = self._link
        if client is not None:
            client.send_simulator_message(payload)

    def _forward_shot(self, sequence: int, simulator: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """A shot arriving from the enclosure. Deliver it now or lose it honestly."""

        session = self._session
        if session is None or not session.connected:
            if not self.connect_simulator():
                with self._lock:
                    self._shots_lost += 1
                # The golfer hit a ball and PiTrac measured it. That the
                # simulator is not running is a fact about the simulator, not
                # about the shot, so it is kept and drawn like any other. The
                # other failure path already did this; this one did not, and a
                # shot hit while GSPro was closed disappeared entirely.
                self._record_shot(payload, simulator, delivered=False)
                self._report_simulator_state()
                return {
                    "accepted": False,
                    "code": SIM_NOT_RUNNING.code,
                    "message": SIM_NOT_RUNNING.failed,
                }
            session = self._session

        seen_before = getattr(session, "messages_seen", 0)
        try:
            session.send(payload)
            # A write to a socket whose peer has gone away succeeds: it lands
            # in the kernel buffer and the reset arrives afterwards. Reporting
            # on the write alone means the first shot after a simulator crash
            # is announced as delivered when nobody received it, and the
            # golfer is told their shot counted when it did not. Give the
            # reader a moment to notice, and believe it if it does.
            self._settle_delivery(session, seen_before)
            if not session.connected:
                raise OSError("the simulator closed the connection")
        except OSError as exc:
            with self._lock:
                self._shots_lost += 1
                self._last_simulator_error = SIM_NOT_RUNNING.as_dict(str(exc))
            self._record_shot(payload, simulator, delivered=False)
            self._report_simulator_state()
            return {"accepted": False, "code": SIM_NOT_RUNNING.code, "message": str(exc)}

        with self._lock:
            self._shots_delivered += 1
            self._last_shot_at = time.time()
        self._record_shot(payload, simulator, delivered=True)
        return {"accepted": True, "message": "delivered to {}".format(self.simulator.label)}

    def _record_shot(self, payload: Dict[str, Any], simulator: str, delivered: bool) -> None:
        """Keep the shot, with the club. Never let logging break shot delivery.

        The range is fed from here too, so a shot appears on it whether or not
        a simulator was listening. Both are wrapped: a shot that reached the
        golfer's simulator must not be reported as failed because something
        downstream of delivery raised.
        """

        # Keep the last few shots exactly as they arrived. Every assumption
        # downstream -- field names, units, which way a positive angle points --
        # was made against the protocol and a stand-in, not against a real
        # launch monitor. When one is finally attached, this is what says
        # whether those assumptions were right.
        try:
            self._keep_raw(payload)
        except Exception:
            pass
        try:
            shot = self.shots.record(
                payload, simulator or self.simulator.value, delivered=delivered
            )
        except Exception:
            return
        try:
            self.range.record(shot.ball, shot.club)
        except Exception:
            pass

    #: How long to wait after writing a shot for the connection to prove it is
    #: still there. Short: a golf shot is in the air for seconds, and half of
    #: one is invisible next to being told a lie about it.
    DELIVERY_CONFIRM_SECONDS = 0.5
    DELIVERY_POLL_SECONDS = 0.05

    def _settle_delivery(self, session, seen_before: int) -> None:
        """Wait just long enough to know whether the shot really landed.

        Exits the moment the simulator says anything back, which is the normal
        case and takes milliseconds. Only a simulator that acknowledges nothing
        costs the full wait, and only a dead one reaches the end of it.
        """

        deadline = time.monotonic() + self.DELIVERY_CONFIRM_SECONDS
        while time.monotonic() < deadline:
            if not session.connected:
                return
            if session.messages_seen != seen_before:
                return
            time.sleep(self.DELIVERY_POLL_SECONDS)

    def check_simulator(self) -> Dict[str, Any]:
        self.connect_simulator()
        return self.status()

    def send_test_shot(self) -> Dict[str, Any]:
        """Send one deliberate shot. The user is warned before this is called."""

        if not self.connect_simulator():
            with self._lock:
                self._test_shot_accepted = False
            return self.status()

        outcome = self._session.send_test_shot(TEST_SHOT)
        with self._lock:
            self._test_shot_accepted = bool(outcome.get("accepted"))
            if outcome.get("accepted"):
                self._last_simulator_error = None
            else:
                info = lookup(str(outcome.get("code", ""))) or SIM_NOT_RUNNING
                self._last_simulator_error = info.as_dict()
        self._report_simulator_state()
        return self.status()

    def _report_simulator_state(self) -> None:
        client = self._link
        if client is None or not client.connected:
            return
        client.send_simulator_status(self.simulator_status())

    # --- Reporting --------------------------------------------------------

    def simulator_status(self) -> Dict[str, Any]:
        with self._lock:
            session = self._session
            accepted = self._test_shot_accepted
            error = dict(self._last_simulator_error) if self._last_simulator_error else None
        connected = bool(session and session.connected)
        return {
            "simulator": self.simulator.value,
            "simulatorLabel": self.simulator.label,
            "connected": connected,
            "ready": connected and accepted,
            "testShotAccepted": accepted,
            "message": (error or {}).get("failed", "")
            if error
            else ("Connected" if connected else "Not checked yet"),
            "errorCode": (error or {}).get("code", ""),
        }

    def chain(self) -> List[Dict[str, Any]]:
        """The four hops, in order, each either done or the first thing to fix."""

        client = self._link
        linked = bool(client and client.connected)
        pi = client.device if linked else {}
        pi_status = self._pi_status if linked else {}
        simulator = self.simulator_status()

        # Only the enclosure knows whether its cameras are attached, its
        # calibration is present, and its measurement program is running, so
        # this step is answered from the enclosure's own self-test.
        measuring, measuring_detail = self._enclosure_measuring(linked, pi_status)
        steps = [
            {
                "key": "pitrac",
                "title": "PiTrac is measuring",
                "ok": measuring,
                "detail": measuring_detail,
            },
            {
                "key": "link",
                "title": "PiTrac is connected to this computer",
                "ok": linked,
                "detail": (
                    "Connected to {}".format(pi.get("displayName", "PiTrac"))
                    if linked
                    else "Not connected"
                ),
            },
            {
                "key": "simulator",
                "title": "{} is connected".format(self.simulator.label),
                "ok": simulator["connected"],
                "detail": simulator["message"],
            },
            {
                "key": "testShot",
                "title": "A test shot was accepted",
                "ok": simulator["ready"],
                "detail": (
                    "{} accepted a shot".format(self.simulator.label)
                    if simulator["ready"]
                    else "Not confirmed yet"
                ),
            },
        ]
        for step in steps:
            step["blocking"] = not step["ok"]
        return steps

    #: Enclosure self-test checks this computer cannot evaluate for itself.
    ENCLOSURE_CHECKS = ("hardware", "cameras", "calibration", "pitracMeasurement", "pitracTarget")

    def _enclosure_measuring(self, linked: bool, pi_status: Dict[str, Any]):
        """Whether the enclosure says it can actually measure a shot."""

        if not linked:
            return False, "Not connected to PiTrac"

        report = pi_status.get("selfTest")
        if not report:
            # The enclosure pushes its state on connecting; until it arrives,
            # this is genuinely unknown and must not be shown as fine.
            return False, "Waiting for the enclosure"

        failing = [
            check
            for check in report.get("checks", [])
            if check.get("key") in self.ENCLOSURE_CHECKS and check.get("status") != "pass"
        ]
        if failing:
            return False, failing[0].get("detail") or failing[0].get("title", "")
        return True, "The launch monitor is running"

    def state(self) -> State:
        """The one word shown on this computer, derived from the chain.

        The chain is the single source of truth, so the headline can never
        disagree with the steps printed underneath it. In particular this cannot
        say READY TO PLAY while the enclosure is reporting that it has no
        cameras — which is exactly the stale readiness this product exists to
        avoid.
        """

        client = self._link
        if client is None:
            return State.SETUP_REQUIRED
        if not client.connected:
            return State.CONNECTING if client.last_error is None else State.SETUP_REQUIRED

        steps = {step["key"]: step["ok"] for step in self.chain()}
        if all(steps.values()):
            return State.READY_TO_PLAY
        if not steps.get("link", False):
            return State.SETUP_REQUIRED
        if not steps.get("pitrac", False):
            return State.RECOVERY_REQUIRED
        if not steps.get("simulator", False):
            return State.SIMULATOR_ACTION_REQUIRED
        # Everything works except an acknowledged test shot.
        return State.CONNECTED

    def enclosure_status(self, refresh: bool = False) -> Dict[str, Any]:
        client = self._link
        if client is None or not client.connected:
            return {}
        if refresh:
            try:
                reply = client.call("status", timeout=10)
                if reply and reply.get("ok"):
                    with self._lock:
                        self._pi_status = reply.get("data") or {}
            except (link.LinkError, link.LinkClosed, TimeoutError):
                pass
        with self._lock:
            return dict(self._pi_status)

    def command(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Ask the enclosure to do something on the user's behalf."""

        client = self._link
        if client is None or not client.connected:
            raise EasyConnectError(LINK_NOT_FOUND, "not connected to PiTrac")
        reply = client.call(name, arguments or {})
        if reply is None:
            raise EasyConnectError(LINK_NOT_FOUND, "PiTrac did not answer")
        if not reply.get("ok"):
            info = reply.get("error") or {}
            found = lookup(str(info.get("code", "")))
            raise EasyConnectError(
                found or LINK_NOT_FOUND, str(info.get("failed", "that request failed"))
            )
        return reply.get("data") or {}

    def status(self) -> Dict[str, Any]:
        client = self._link
        state = self.state()
        with self._lock:
            delivered, lost, last_shot = self._shots_delivered, self._shots_lost, self._last_shot_at
            pi_status = dict(self._pi_status)
        chain = self.chain()
        blocking = next((step for step in chain if step["blocking"]), None)

        # The enclosure's relay counts every shot PiTrac sent, including the
        # ones that never reached this computer. Prefer its numbers so a user is
        # never told nothing was lost when something was.
        relay = pi_status.get("relay") or {}
        if relay:
            shots = {
                "delivered": relay.get("shotsForwarded", delivered),
                "lost": relay.get("shotsFailed", lost),
                "lastAt": last_shot,
                "countedBy": "enclosure",
            }
        else:
            shots = {"delivered": delivered, "lost": lost, "lastAt": last_shot,
                     "countedBy": "this computer"}
        return {
            "version": self.version,
            "computerName": self.computer_name,
            "state": state.value,
            "headline": state.headline,
            "detail": state.detail,
            "ready": state is State.READY_TO_PLAY,
            "simulator": self.simulator.value,
            "simulatorLabel": self.simulator.label,
            "simulatorStatus": self.simulator_status(),
            "chain": chain,
            "nextStep": blocking["title"] if blocking else "",
            "link": client.status() if client else {"connected": False},
            "enclosure": pi_status,
            "pairedEnclosures": [
                {"deviceId": key, "displayName": value.get("displayName", "PiTrac")}
                for key, value in sorted(self.paired_enclosures.items())
            ],
            "activeDeviceId": self.store.get("activeDeviceId", ""),
            "setupComplete": bool(self.store.get("setupComplete")),
            "dashboardUrl": self._dashboard_url(),
            "update": self._update_status(),
            "shotLog": self.shots.status(),
            "shots": shots,
        }

    def _update_status(self) -> Dict[str, Any]:
        """What is installed here and on the enclosure, and whether either is behind."""

        with self._lock:
            enclosure_version = (self._pi_status or {}).get("version", "")
        status = self.updates.check().as_dict()
        status["enclosureVersion"] = enclosure_version
        # The two halves are meant to move together. Saying so is more useful
        # than letting someone update one and wonder why the other complains.
        status["versionsMatch"] = (
            not enclosure_version or enclosure_version == self.version
        )
        return status

    def check_for_updates(self) -> Dict[str, Any]:
        return self.updates.check(force=True).as_dict()

    def apply_update(self) -> Dict[str, Any]:
        return self.updates.apply()

    def _dashboard_url(self) -> str:
        """PiTrac's own dashboard, for anyone who wants the raw shot data."""

        from ..pi.pitrac import dashboard_url

        with self._lock:
            reported = (self._pi_status or {}).get("dashboardUrl")
        if reported:
            return reported
        client = self._link
        return dashboard_url(client.host) if client else ""

    def set_club(self, club: str) -> Dict[str, Any]:
        return {"club": self.shots.set_club(club)}

    def clear_shots(self) -> Dict[str, Any]:
        self.shots.clear()
        return self.shots.status()

    def cameras(self) -> Dict[str, Any]:
        """Camera detection, straight from PiTrac. Nothing here interprets it."""

        import json
        import urllib.error
        import urllib.request

        base = self._dashboard_url()
        if not base:
            return {"available": False, "message": "Not connected to PiTrac."}
        try:
            with urllib.request.urlopen(base + "/api/cameras/detect", timeout=8) as response:
                detected = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError, OSError) as exc:
            return {"available": False, "message": "PiTrac did not answer: {}".format(exc)}
        detected["available"] = True
        detected["dashboardUrl"] = base
        return detected

    def close(self) -> None:
        self.disconnect()
        with self._lock:
            session, self._session = self._session, None
        if session is not None:
            session.close()


def _post(url: str, body: Optional[Dict[str, Any]], timeout: float = 10.0) -> Dict[str, Any]:
    import json
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"X-PiTrac-Portal": "1"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data is not None else "GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except Exception:
            payload = {}
        info = payload.get("error") or {}
        found = lookup(str(info.get("code", "")))
        raise EasyConnectError(
            found or PAIR_EXCHANGE_LOST, str(info.get("failed", "PiTrac refused that request"))
        ) from error
    except urllib.error.URLError as error:
        # The enclosure was found, so this is not "no PiTrac on the network" —
        # it answered discovery but its setup page did not answer this request.
        from ..common.errors import LINK_PORTAL_UNREACHABLE

        raise EasyConnectError(
            LINK_PORTAL_UNREACHABLE, "{} at {}".format(error.reason, url)
        ) from error

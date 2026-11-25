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

import os
import platform
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import __version__
from ..common import jsontext
from ..common import discovery, link
from ..common import pairing_exchange as exchange
from ..common.configstore import ConfigStore
from ..common.errors import (
    LINK_BUSY,
    LINK_DEVICE_MISMATCH,
    LINK_DEVICE_REPLACED,
    LINK_NOT_FOUND,
    PAIR_EXCHANGE_LOST,
    PAIR_NOT_PAIRED,
    PAIR_RATE_LIMITED,
    PAIR_REVOKED,
    CFG_WRITE_FAILED,
    SIM_FORMAT_MISMATCH,
    SIM_NOT_RUNNING,
    EasyConnectError,
    lookup,
)
from ..common import release_manifest
from ..common.states import State
from ..common.updates import (
    DEVELOPMENT,
    SOURCE,
    DesktopReleaseUpdater,
    DesktopUpdateState,
    UpdateStatus,
    Updater,
    coordinate_update,
)
from ..common.versions import compare
from ..models import TEST_SHOT, PlayMode, Simulator
from . import clubs as caddie
from . import self_update
from .link_client import CompanionLinkClient
from . import shotlog
from .rangeplay import RangeSession
from .shotlog import ShotLog
from .simulator_session import SimulatorSession

#: Desktop update states a passive background/status check may move between.
#: Once a real download/install is under way (or has finished, successfully
#: or not), only that operation's own code may change the state -- a stale
#: background check landing mid-download must not overwrite "downloading"
#: back to "available."
_PASSIVE_DESKTOP_UPDATE_STATES = frozenset(
    {
        DesktopUpdateState.IDLE,
        DesktopUpdateState.CHECKING,
        DesktopUpdateState.UP_TO_DATE,
        DesktopUpdateState.AVAILABLE,
        DesktopUpdateState.CHECK_FAILED,
    }
)

#: How often the background thread re-checks while the app stays open, on
#: top of the passive cache-expiry-on-poll that already happens whenever
#: /api/status is read after the cache window elapses. Having both means the
#: periodic check the requirements ask for does not depend on the window
#: being actively polled.
PERIODIC_DESKTOP_UPDATE_CHECK_SECONDS = 20 * 60


def default_config_path() -> Path:
    import os

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    return base / "pitrac-easy-connect" / "companion.json"


#: Which specific link/pairing failure code maps to which distinct state, so
#: the headline names the actual problem instead of a generic "setup
#: required" that tells the user to go check Wi-Fi provisioning that was
#: never the issue.
_CODE_STATES: Dict[str, State] = {
    PAIR_NOT_PAIRED.code: State.PAIRING_REQUIRED,
    PAIR_REVOKED.code: State.PAIRING_REVOKED,
    LINK_DEVICE_MISMATCH.code: State.SAVED_PI_RESET,
    LINK_DEVICE_REPLACED.code: State.SAVED_PI_RESET,
    LINK_BUSY.code: State.ANOTHER_COMPUTER_CONNECTED,
    PAIR_RATE_LIMITED.code: State.RATE_LIMITED,
}


def _state_for_code(code: Optional[str]) -> State:
    return _CODE_STATES.get(code or "", State.SETUP_REQUIRED)


def default_computer_name() -> str:
    try:
        return platform.node() or "This computer"
    except Exception:
        return "This computer"


#: Where an enclosure answers on its own setup hotspot.
SETUP_ADDRESS = "10.42.0.1"

#: How long to wait for an enclosure to do something. A radio needs longer.
COMMAND_TIMEOUT = 20.0
COMMAND_TIMEOUTS = {
    "scanNetworks": 60.0, "joinNetwork": 150.0, "setDirectMode": 90.0, "resetNetwork": 90.0,
}


class CompanionService:
    def __init__(
        self,
        config_path: Optional[Path] = None,
        simulator_ports: Optional[Dict[Simulator, int]] = None,
        simulator_host: str = "127.0.0.1",
        version: str = __version__,
        discovery_port: int = discovery.DISCOVERY_PORT,
        computer_name: Optional[str] = None,
        search_seconds: float = 2.0,
        research_seconds: float = 3.0,
        discovery_targets: Optional[List[str]] = None,
        periodic_update_check_seconds: float = PERIODIC_DESKTOP_UPDATE_CHECK_SECONDS,
        startup_update_check: bool = True,
        desktop_relaunch_arguments: Optional[List[str]] = None,
    ):
        self.version = version
        self._desktop_relaunch_arguments = list(desktop_relaunch_arguments or [])
        self.simulator_host = simulator_host
        self.discovery_port = discovery_port
        #: How long a search listens for enclosures announcing themselves, and
        #: how long the second look takes when an enclosure is asked for by an
        #: id that is not in the current list. Real values on a real network;
        #: the tests turn them down, because a route that answers in three
        #: seconds cannot be exercised three hundred times.
        self.search_seconds = search_seconds
        self.research_seconds = research_seconds
        # Production discovers every active IPv4 interface. Tests and local
        # simulators can opt into loopback explicitly so a hosted runner's
        # routing table or macOS Local Network policy cannot affect them.
        self.discovery_targets = discovery_targets
        #: The app starts the HTTP service before pywebview creates the OS
        #: window. Do not call that interval native: build checks query this
        #: field specifically to catch a backend that never opened.
        self._window_lifecycle = "starting"
        self._window_detail: Optional[str] = None
        self._window_activator: Optional[Callable[[], None]] = None
        self._fullscreen_switch: Optional[Callable[[bool], None]] = None
        self._window_closer: Optional[Callable[[], None]] = None
        self._pending_window_activation = False
        self._window_activation_requests = 0
        self._window_activation_completed = 0
        self._window_activation_error: Optional[str] = None
        self.computer_name = computer_name or default_computer_name()
        # Always hold a port for every simulator. A caller that overrides only
        # one must not leave the other unmapped, or switching to it later fails
        # with a lookup error instead of a message.
        self.simulator_ports = {simulator: simulator.default_port for simulator in Simulator}
        self.simulator_ports.update(simulator_ports or {})
        self.store = ConfigStore(
            config_path or default_config_path(),
            defaults={
                "simulator": PlayMode.LOCAL.value,
                # The caddie: which clubs there are, and whether it chooses.
                "bag": list(caddie.DEFAULT_BAG),
                "autoClub": True,
                "enclosures": {},
                "activeDeviceId": "",
                # An update spans a desktop replacement and restart. Keeping
                # its exact target here lets the new desktop copy continue the
                # same transaction instead of chasing a newer release midway.
                "updateTarget": "",
                "updateTag": "",
                "updateTransactionId": "",
                "updateAssetSha256": "",
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
        # A search that started earlier but finishes later than a more recent
        # one must not win the race and overwrite the fresher result.
        self._search_generation = 0
        self._search_in_progress = False
        # Set when connect() fails before a CompanionLinkClient could even be
        # built (for example LINK_DEVICE_REPLACED, discovered before opening
        # a socket). Auto-reconnect at startup runs on a background thread
        # and swallows exceptions so it cannot crash the app, so without this
        # the failure would otherwise vanish with nothing to show for it.
        self._last_connect_error: Optional[Dict[str, str]] = None
        self._last_connect_error_device_id: str = ""
        self._test_shot_accepted = False
        self._last_simulator_error: Optional[Dict[str, str]] = None
        #: Why the last swing could not be saved, until one can be.
        self._capture_error = ""
        self._last_shot_at: Optional[float] = None
        self._shots_delivered = 0
        self._shots_lost = 0
        self._pi_status: Dict[str, Any] = {}
        self._was_linked = False
        #: What the enclosure was last told, to know when that stops being true.
        self._reported_simulator: Optional[Dict[str, Any]] = None
        self._pending_update_target = str(self.store.get("updateTarget", "") or "")
        #: The practice range. In memory only: a session is a bucket of balls.
        self.range = RangeSession()
        self.range.set_target(self.store.get("rangeTarget", self.range.target))
        #: Whether PiTrac can see a ball. None until it has said.
        self._ball_detected: Optional[bool] = None
        self._raw_shots: List[Dict[str, Any]] = []
        #: E6 sends the measurements before the instruction to hit, so they
        #: wait here until the swing is taken. Abandoned measurements must
        #: never be attached to a later swing, so they are cleared whenever
        #: the link or the simulator changes, and expire on their own.
        self._pending_ball: Dict[str, Any] = {}
        self._pending_ball_at: float = 0.0
        self.shots = ShotLog(
            (config_path or default_config_path()).with_name("shots.json")
        )
        self._follow_the_caddie()
        self.updates = Updater(version)
        # Determined once: whether this process is a git checkout does not
        # change while it runs, and re-deriving it on every status poll would
        # mean a git subprocess call every few seconds. DEVELOPMENT is
        # grouped with SOURCE, not treated as packaged: a dirty checkout must
        # stay left alone (Updater already refuses to touch it), not be
        # offered a packaged build to install over itself.
        self._install_kind = self.updates.kind()
        self._uses_git_updater = self._install_kind in (SOURCE, DEVELOPMENT)
        desktop_machine = None
        if not self._uses_git_updater and getattr(sys, "frozen", False):
            try:
                desktop_machine = self_update.packaged_architecture(
                    executable=Path(sys.executable), expected_version=version
                )
            except self_update.SelfUpdateError:
                # A loose copy or damaged manifest must not stop the app from
                # opening. Strict preflight still refuses every mutation; host
                # architecture is the best read-only check fallback available.
                desktop_machine = None
        self.desktop_updates: Optional[DesktopReleaseUpdater] = (
            None
            if self._uses_git_updater
            else DesktopReleaseUpdater(version, machine=desktop_machine)
        )
        self._desktop_update_state = DesktopUpdateState.IDLE
        self._desktop_update_detail = ""
        self._desktop_update_available_version = ""
        self._last_desktop_status = UpdateStatus(
            version, self._install_kind, detail="Update check has not finished yet."
        )
        self._staged_install: Optional[self_update.InstalledApp] = None
        self._staged_target_version = ""
        self._desktop_transaction_root: Optional[Path] = None
        self._desktop_journal_path: Optional[Path] = None
        self._desktop_archive_path: Optional[Path] = None
        self._desktop_asset_digest = ""
        self._desktop_asset_name = ""
        self._desktop_release_tag = ""
        self._desktop_downloaded_bytes = 0
        self._desktop_download_total: Optional[int] = None
        self._desktop_cancel = threading.Event()
        self._desktop_operation_generation = 0
        self._update_check_in_progress = False
        self._check_last_install_result()
        if self.desktop_updates is not None:
            # Startup is the one moment nothing of ours is part-way through
            # building a transaction, so it is where journal-less debris --
            # an interrupted download, or a manual package this process is
            # not offering -- can be discarded safely.
            self_update.prune_transactions(remove_debris=True)
        self._update_check_stop = threading.Event()
        # Off the startup path, and silent on failure: a GitHub outage must not
        # stop anyone playing golf. Checked once immediately and then on a
        # timer for as long as the app stays open -- the immediate check
        # alone is what a v0.4.4 process left running would have relied on,
        # and it goes stale the moment a new release ships while it is idle.
        if startup_update_check:
            self._schedule_update_check()
        if not self._uses_git_updater:
            if periodic_update_check_seconds > 0:
                threading.Thread(
                    target=self._periodic_update_check_loop,
                    args=(periodic_update_check_seconds,),
                    daemon=True,
                ).start()

    # --- Simulator selection ---------------------------------------------

    @property
    def mode(self) -> PlayMode:
        try:
            return PlayMode(self.store.get("simulator", PlayMode.LOCAL.value))
        except ValueError:
            # Something an earlier release offered and this one does not.
            return PlayMode.LOCAL

    @property
    def simulator(self) -> Optional[Simulator]:
        return self.mode.simulator

    def _on_link_state(self) -> None:
        """Something about the link changed. Called for every status it pushes.

        So this only acts on arriving and leaving. Answering each push with
        this computer's own state made the enclosure run its self-test and push
        again, thousands of times a second for as long as a computer was
        connected, on a machine that is trying to time a golf ball.
        """

        client = self._link
        connected = client is not None and client.connected
        with self._lock:
            arrived = connected and not self._was_linked
            self._was_linked = connected
            if not connected:
                # The enclosure has gone. Anything half-sent belongs to a swing
                # that will never be completed.
                self._forget_pending_ball()
                self._ball_detected = None
        if not arrived:
            return
        self._report_simulator_state()
        if self.mode is PlayMode.LOCAL:
            self._tell_pitrac_the_club()

    def select_simulator(self, name: str) -> Dict[str, Any]:
        try:
            mode = PlayMode(str(name))
        except ValueError as exc:
            raise ValueError("Choose Local Range or GSPro") from exc
        leaving_local = self.mode is PlayMode.LOCAL and mode is not PlayMode.LOCAL
        with self._lock:
            self.store.set("simulator", mode.value)
            self._test_shot_accepted = False
            self._last_simulator_error = None
            # Measurements gathered for the previous simulator's protocol have
            # nothing to do with the new one.
            self._forget_pending_ball()
            if self._session is not None:
                self._session.close()
                self._session = None
        if leaving_local:
            # GSPro will say which club is in hand when it connects. Until it
            # does, PiTrac should not go on measuring putts.
            self._tell_pitrac_the_club("")
        if mode is PlayMode.LOCAL:
            self._follow_the_caddie()
            self._tell_pitrac_the_club()
            self._report_simulator_state()
        else:
            self.connect_simulator()
        return self.status()

    def play_modes(self) -> List[Dict[str, Any]]:
        """What can be chosen, and why one cannot be used on this computer."""

        on_windows_only = "" if sys.platform == "win32" else "GSPro runs only on Windows."
        return [
            {"value": PlayMode.LOCAL.value, "label": PlayMode.LOCAL.label, "note": ""},
            {"value": PlayMode.GSPRO.value, "label": PlayMode.GSPRO.label,
             "note": on_windows_only},
        ]

    def reveal_downloaded_update(self) -> Dict[str, Any]:
        """Reveal only this process's verified manual-update package.

        The page supplies no path.  The backend reads the path retained by the
        failed automatic-install transaction, resolves it beneath the private
        update-state directory, and then asks Finder/File Explorer to select
        that local file.  This deliberately cannot open a URL or an arbitrary
        path chosen by page script.
        """

        with self._lock:
            archive = self._desktop_archive_path
            state = self._desktop_update_state
        if archive is None or state is not DesktopUpdateState.PREFLIGHT_FAILED:
            return {
                "revealed": False,
                "path": "",
                "detail": "No verified update package is waiting to be shown.",
            }
        try:
            supplied = Path(archive)
            if supplied.is_symlink():
                raise OSError("the saved package is a symbolic link")
            resolved = supplied.resolve(strict=True)
            state_root = self_update.staging_dir().resolve(strict=True)
            if not resolved.is_file() or state_root not in resolved.parents:
                raise OSError("the saved package is outside the update-state directory")
        except OSError as exc:
            return {
                "revealed": False,
                "path": str(archive),
                "detail": "The verified update package could not be located safely: {}.".format(exc),
            }

        system = platform.system()
        if system == "Darwin":
            command = ["/usr/bin/open", "-R", str(resolved)]
        elif system == "Windows":
            command = ["explorer.exe", "/select,{}".format(resolved)]
        else:
            return {
                "revealed": False,
                "path": str(resolved),
                "detail": "Desktop update packages are only distributed for macOS and Windows.",
            }
        try:
            done = subprocess.run(command, capture_output=True, timeout=15, check=False)
            revealed = done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            revealed = False
        return {
            "revealed": revealed,
            "path": str(resolved),
            "detail": (
                "The verified update package is selected in your file manager."
                if revealed else
                "The file manager could not be opened. Use the exact saved path shown here."
            ),
        }

    def set_window_state(self, state: str, detail: Optional[str] = None) -> None:
        if state not in {"starting", "native", "headless", "failed"}:
            raise ValueError("unknown window lifecycle state: {}".format(state))
        with self._lock:
            self._window_lifecycle = state
            self._window_detail = detail

    def window_state(self) -> Dict[str, Any]:
        with self._lock:
            state = self._window_lifecycle
            detail = self._window_detail
        return {"state": state, "detail": detail}

    def register_window_activator(self, activator: Callable[[], None]) -> None:
        """Attach the native window after pywebview has created it.

        Keep the activation path tolerant of a request arriving before the
        native backend registers its callback. Remembering one pending request
        means the first window is raised as soon as it exists.
        """

        with self._lock:
            self._window_activator = activator
            pending = self._pending_window_activation
            self._pending_window_activation = False
            request_number = self._window_activation_requests
        if pending:
            self._dispatch_window_activation(activator, request_number)

    def register_window_closer(self, closer: Callable[[], None]) -> None:
        with self._lock:
            self._window_closer = closer

    def close_native_window(self) -> None:
        with self._lock:
            closer = self._window_closer
        if closer is not None:
            closer()

    def activate_window(self) -> Dict[str, Any]:
        """Queue this process's native window to be raised for a second launch."""

        with self._lock:
            self._window_activation_requests += 1
            activator = self._window_activator
            count = self._window_activation_requests
            if activator is None:
                self._pending_window_activation = True
                return {"activated": False, "queued": True}
        # Window APIs marshal work onto the OS GUI thread. Never make the
        # authenticated loopback response wait for that handoff: a second app
        # launch must exit immediately even when a desktop backend is busy.
        self._dispatch_window_activation(activator, count)
        return {"activated": False, "queued": True, "requests": count}

    def _dispatch_window_activation(
        self, activator: Callable[[], None], request_number: int
    ) -> None:
        def dispatch() -> None:
            try:
                activator()
            except Exception as exc:
                with self._lock:
                    self._window_activation_error = "{}: {}".format(
                        type(exc).__name__, exc
                    )
            else:
                with self._lock:
                    self._window_activation_completed = max(
                        self._window_activation_completed, request_number
                    )
                    self._window_activation_error = None

        threading.Thread(
            target=dispatch, name="pitrac-window-activation", daemon=True
        ).start()

    def window_activation_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "requests": self._window_activation_requests,
                "completed": self._window_activation_completed,
                "error": self._window_activation_error,
            }

    @property
    def window_activation_requests(self) -> int:
        with self._lock:
            return self._window_activation_requests

    # --- Finding an enclosure --------------------------------------------

    def _search(self, timeout: Optional[float] = None) -> discovery.DiscoveryResult:
        if timeout is None:
            timeout = self.search_seconds
        with self._lock:
            self._search_generation += 1
            generation = self._search_generation
            self._search_in_progress = True
        try:
            result = discovery.discover(
                timeout=timeout,
                port=self.discovery_port,
                broadcast_to=self.discovery_targets,
            )
            with self._lock:
                # A slower, earlier-started search finishing after a faster,
                # later one must not clobber the fresher result with a stale
                # one.
                if generation == self._search_generation:
                    self._found = list(result.enclosures)
            return result
        finally:
            with self._lock:
                if generation == self._search_generation:
                    self._search_in_progress = False

    def search(self, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        """Compatibility wrapper for callers that only need enclosures."""

        result = self._search(timeout)
        known = self.store.get("enclosures") or {}
        return [
            {**enclosure.as_dict(), "paired": enclosure.device_id in known}
            for enclosure in result.enclosures
        ]

    def search_payload(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        result = self._search(timeout)
        known = self.store.get("enclosures") or {}
        return {
            "enclosures": [
                {**enclosure.as_dict(), "paired": enclosure.device_id in known}
                for enclosure in result.enclosures
            ],
            "problem": result.problem.as_dict() if result.problem else None,
            "searchInProgress": self._search_in_progress,
        }

    def _found_by_id(self, device_id: str) -> Optional[discovery.FoundEnclosure]:
        with self._lock:
            for enclosure in self._found:
                if enclosure.device_id == device_id:
                    return enclosure
        return None

    def _found_at_address(self, address: str) -> Optional[discovery.FoundEnclosure]:
        if not address:
            return None
        with self._lock:
            for enclosure in self._found:
                if enclosure.address == address:
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
            self.search(timeout=self.research_seconds)
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
                "hostname": enclosure.hostname,
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
        known = caddie.known_carries(self.shots.everything())
        distances = caddie.carries(known)
        bag = self.bag
        return dict(
            self.range.status(),
            club=self.shots.club,
            autoClub=self.auto_club,
            suggested=caddie.suggest(self.range.target, bag, distances),
            # GSPro says which club is in hand while it is the one being played.
            clubIsOurs=self.mode is PlayMode.LOCAL,
            ballDetected=self._ball_detected,
            clubs=[
                {"club": club, "carry": round(distances[club]), "measured": club in known,
                 "inBag": club in bag}
                for club in caddie.CLUBS
            ],
        )

    def clear_range(self) -> Dict[str, Any]:
        self.range.clear()
        return self.range_status()

    def register_fullscreen(self, switch: Callable[[bool], None]) -> None:
        self._fullscreen_switch = switch

    def set_fullscreen(self, on: bool) -> Dict[str, Any]:
        """Fill the screen with the app's own window, or give it back."""

        switch = self._fullscreen_switch
        if switch is None:
            return {"fullscreen": False}
        # Off the request thread: the window belongs to another one, and
        # waiting on it from here is how the two end up waiting on each other.
        threading.Thread(target=switch, args=(bool(on),), daemon=True).start()
        return {"fullscreen": bool(on)}

    @property
    def bag(self) -> List[str]:
        return caddie.clean_bag(self.store.get("bag"))

    @property
    def auto_club(self) -> bool:
        return self.mode is PlayMode.LOCAL and bool(self.store.get("autoClub", True))

    def set_range_target(self, yards: Any) -> Dict[str, Any]:
        self.store.set("rangeTarget", self.range.set_target(yards))
        self._follow_the_caddie()
        return self.range_status()

    def choose_range_club(self, club: str) -> Dict[str, Any]:
        if club not in caddie.CLUBS:
            raise ValueError("That is not a club")
        self.set_club(club)
        return self.range_status()

    def set_auto_club(self, on: bool) -> Dict[str, Any]:
        self.store.set("autoClub", bool(on))
        self._follow_the_caddie()
        return self.range_status()

    def set_bag(self, names: Any) -> Dict[str, Any]:
        self.store.set("bag", caddie.clean_bag(names if isinstance(names, list) else None))
        self._follow_the_caddie()
        return self.range_status()

    def _follow_the_caddie(self) -> None:
        """Change to the suggested club, when asked to choose automatically.

        Only when something the player did calls for it. Re-deciding after
        every shot would change the club in their hands because their average
        moved by a yard.
        """

        if not self.auto_club:
            return
        distances = caddie.carries(caddie.known_carries(self.shots.everything()))
        club = caddie.suggest(self.range.target, self.bag, distances)
        if club and club != self.shots.club:
            self.shots.set_club(club)
            self._tell_pitrac_the_club()

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
        self._last_connect_error = None
        self._last_connect_error_device_id = ""
        return self.status()

    def remove_local(self, device_id: str) -> Dict[str, Any]:
        """Remove a saved pairing from this computer only.

        Unlike ``forget``, this never assumes the enclosure is reachable and
        never attempts to revoke anything remotely — it exists for exactly
        the case ``forget`` cannot handle: a saved pairing for a PiTrac that
        was wiped, replaced, or is simply not answering right now. The
        enclosure keeps its own record of this computer, if it still exists,
        until its owner removes it from the setup page.
        """

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
            was_active = active == device_id
        if was_active:
            self.disconnect()
            self._last_connect_error = None
            self._last_connect_error_device_id = ""
        return self.status()

    @property
    def paired_enclosures(self) -> Dict[str, Any]:
        return self.store.get("enclosures") or {}

    # --- Connecting -------------------------------------------------------

    def connect(self, device_id: str = "") -> Dict[str, Any]:
        # A fresh attempt supersedes whatever a previous one recorded here.
        # Kept separate from client.last_error because these raise before a
        # CompanionLinkClient exists to hold one.
        self._last_connect_error = None
        self._last_connect_error_device_id = ""
        with self._lock:
            device_id = device_id or self.store.get("activeDeviceId") or ""
            record = (self.store.get("enclosures") or {}).get(device_id)
        if record is None:
            error = EasyConnectError(LINK_NOT_FOUND, "this computer is not paired with that PiTrac")
            self._last_connect_error = error.as_dict()
            self._last_connect_error_device_id = device_id
            raise error

        # Discovery is authoritative for the address; the stored one is only a
        # fallback for when the beacon is blocked.
        enclosure = self._found_by_id(device_id)
        if enclosure is None:
            self.search(timeout=self.research_seconds)
            enclosure = self._found_by_id(device_id)
        if enclosure is None:
            # Discovery did not vouch for this device id. If it instead found
            # a *different* device id sitting at the saved address, that is
            # authoritative evidence the saved address no longer belongs to
            # this PiTrac (wiped, reset, or replaced) — do not fall back to
            # it. A saved address remains a usable fallback only when nothing
            # contradicts it.
            saved_address = record.get("address", "")
            collision = self._found_at_address(saved_address)
            if collision is not None and collision.device_id != device_id:
                error = EasyConnectError(
                    LINK_DEVICE_REPLACED,
                    "expected {}, found {} at {}".format(
                        device_id, collision.device_id, saved_address
                    ),
                )
                self._last_connect_error = error.as_dict()
                self._last_connect_error_device_id = device_id
                raise error
        host = enclosure.address if enclosure else record.get("address", "")
        port = (enclosure.link_port if enclosure else 0) or record.get("linkPort") or link.LINK_PORT
        if not host:
            error = EasyConnectError(LINK_NOT_FOUND, "no address is known for that PiTrac")
            self._last_connect_error = error.as_dict()
            self._last_connect_error_device_id = device_id
            raise error

        hostname = (enclosure.hostname if enclosure else "") or record.get("hostname", "")
        candidates = [host]
        if hostname:
            candidates.append(hostname)
            if "." not in hostname:
                candidates.append(hostname + ".local")
        else:
            # Records written before hostname persistence still have a stable
            # device id from which every enclosure hostname is derived.
            candidates.append("pitrac-{}.local".format(device_id.lower()))
        # Where every enclosure is while it is being its own Wi-Fi. Which
        # enclosure answers there is checked like any other address.
        candidates.append(SETUP_ADDRESS)
        candidates = list(dict.fromkeys(candidate for candidate in candidates if candidate))

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
            fallback_hosts=candidates[1:],
            expected_device_id=device_id,
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
            self._was_linked = False
        if client is not None:
            client.stop()

    def _on_enclosure_status(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._pi_status = dict(payload)
            stale = self._reported_simulator
        # A simulator that closes does not say so to anyone, so each of the
        # enclosure's regular reports is a chance to notice. Only if something
        # changed: this must never answer a report with nothing new.
        if stale is not None and self.simulator_status() != stale:
            self._report_simulator_state()

    # --- The simulator on this computer -----------------------------------

    def connect_simulator(self) -> bool:
        simulator = self.simulator
        if simulator is None:
            self._report_simulator_state()
            return False
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

        counts = self._is_swing(simulator, payload)
        self._note_the_ball(payload, counts)
        if self.mode is PlayMode.LOCAL:
            return self._capture_locally(simulator, payload)

        if simulator and simulator != self.simulator.value:
            # What travels over the link is one simulator's own protocol, and
            # nothing here translates it. Sending GSPro's messages to anything
            # else would be noise at best.
            with self._lock:
                self._shots_lost += counts
                self._last_simulator_error = SIM_FORMAT_MISMATCH.as_dict()
            self._record_shot(payload, simulator, delivered=False)
            self._report_simulator_state()
            return {
                "accepted": False,
                "code": SIM_FORMAT_MISMATCH.code,
                "message": SIM_FORMAT_MISMATCH.failed,
            }

        session = self._session
        if session is None or not session.connected:
            if not self.connect_simulator():
                with self._lock:
                    self._shots_lost += counts
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
            acknowledged = self._settle_delivery(session, seen_before)
            if not session.connected:
                raise OSError("the simulator closed the connection")
        except OSError as exc:
            with self._lock:
                self._shots_lost += counts
                self._last_simulator_error = SIM_NOT_RUNNING.as_dict(str(exc))
            self._record_shot(payload, simulator, delivered=False)
            self._report_simulator_state()
            return {"accepted": False, "code": SIM_NOT_RUNNING.code, "message": str(exc)}

        with self._lock:
            self._shots_delivered += counts
            if counts:
                self._last_shot_at = time.time()
        self._record_shot(payload, simulator, delivered=True)
        # "Acknowledged" means the simulator answered after this shot was sent.
        # It is not correlated to *this* shot -- neither protocol carries an id
        # to match on -- so it is reported as what it is rather than dressed up
        # as proof the shot was scored.
        return {
            "accepted": True,
            "acknowledged": acknowledged,
            "message": "{} to {}".format(
                "delivered" if acknowledged else "sent", self.simulator.label),
        }

    def _note_the_ball(self, payload: Dict[str, Any], swing: bool) -> None:
        options = payload.get("ShotDataOptions")
        if swing:
            self._ball_detected = False
        elif isinstance(options, dict) and "LaunchMonitorBallDetected" in options:
            self._ball_detected = bool(options["LaunchMonitorBallDetected"])

    def _capture_locally(self, simulator: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Keep a shot for the range here. Nothing else has to be running."""

        if not self._is_swing(simulator, payload):
            # PiTrac sends these when it connects and as balls come and go, and
            # forgets the club whenever its connection drops.
            self._tell_pitrac_the_club()
            return {"accepted": True, "message": ""}

        captured = self._record_shot(payload, simulator, delivered=None)
        with self._lock:
            if captured:
                self._shots_delivered += 1
                self._last_shot_at = time.time()
            else:
                self._shots_lost += 1
        self._report_simulator_state()
        if not captured:
            return {"accepted": False, "code": CFG_WRITE_FAILED.code,
                    "message": CFG_WRITE_FAILED.failed}
        return {"accepted": True, "acknowledged": True, "message": "recorded on the Local Range"}

    def _is_swing(self, simulator: str, payload: Dict[str, Any]) -> bool:
        """Whether this message is a ball being hit, rather than a heartbeat."""

        from ..pi.relay import is_shot_message

        return is_shot_message(self._protocol(simulator), payload)

    @staticmethod
    def _protocol(simulator: str) -> Simulator:
        try:
            return Simulator(simulator)
        except ValueError:
            return Simulator.GSPRO

    def _tell_pitrac_the_club(self, club: Optional[str] = None) -> None:
        """Say which club is in hand, as GSPro would.

        PiTrac measures a putt with different camera and strobe settings, and
        the only thing that tells it to is a simulator. On the Local Range this
        is the simulator.
        """

        client = self._link
        if client is None:
            return
        client.send_simulator_message({
            "Code": 201,
            "Message": "Easy-Connect player information",
            "Player": {"Club": shotlog.simulator_club(self.shots.club if club is None else club)},
        })

    def _record_shot(
        self, payload: Dict[str, Any], simulator: str, delivered: Optional[bool]
    ) -> bool:
        """Keep the shot, with the club. Never let logging break shot delivery.

        Returns whether it was saved. One that could not be is still drawn: a
        full disk is no reason to lose the flight as well as the record.

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
        # Not every message is a golf shot. GSPro sends heartbeats, and E6
        # needs several messages per swing -- ball data, club data, then
        # SendShot. Recording all of them turned one E6 swing into four
        # history entries and every GSPro heartbeat into a blank one. The
        # relay already knows the difference; this now asks it.
        ball = self._ball_for_history(simulator, payload)
        if ball is None:
            return False

        flown = None
        try:
            flown = self.range.record(ball, self.shots.club)
        except Exception:
            pass
        saved = True
        try:
            self.shots.record(
                payload,
                PlayMode.LOCAL.value if delivered is None else simulator or self.mode.value,
                delivered=delivered, ball=ball, flight=flown,
            )
            self._capture_error = ""
        except Exception as exc:
            saved = False
            self._capture_error = str(exc) or exc.__class__.__name__
        return saved

    def _ball_for_history(self, simulator: str, payload: Dict[str, Any]):
        """The ball data for a completed swing, or None if this is not one.

        E6 sends the numbers in one message and the instruction to hit in
        another, so the numbers are held until the swing is actually taken.
        """

        from .shotlog import ball_from_shot

        measured = ball_from_shot(payload)
        if measured:
            with self._lock:
                self._pending_ball = measured
                self._pending_ball_at = time.monotonic()

        if not self._is_swing(simulator, payload):
            return None

        with self._lock:
            held = self._pending_ball
            if held and time.monotonic() - self._pending_ball_at > self.PENDING_BALL_SECONDS:
                # Measurements this old belong to a swing that never completed.
                held = {}
            ball = measured or held
            self._forget_pending_ball()
        return ball or {}

    #: How long measurements may wait for the instruction to hit before they
    #: are treated as belonging to an abandoned swing. A real sequence arrives
    #: within milliseconds.
    PENDING_BALL_SECONDS = 30.0

    def _forget_pending_ball(self) -> None:
        self._pending_ball = {}
        self._pending_ball_at = 0.0

    #: How long to wait after writing a shot for the connection to prove it is
    #: still there. Short: a golf shot is in the air for seconds, and half of
    #: one is invisible next to being told a lie about it.
    DELIVERY_CONFIRM_SECONDS = 0.5
    DELIVERY_POLL_SECONDS = 0.05

    def _settle_delivery(self, session, seen_before: int) -> bool:
        """Wait just long enough to know whether the shot really landed.

        Exits the moment the simulator says anything back, which is the normal
        case and takes milliseconds. Only a simulator that acknowledges nothing
        costs the full wait, and only a dead one reaches the end of it.
        """

        deadline = time.monotonic() + self.DELIVERY_CONFIRM_SECONDS
        while time.monotonic() < deadline:
            if not session.connected:
                return False
            if session.messages_seen != seen_before:
                return True
            time.sleep(self.DELIVERY_POLL_SECONDS)
        # Still connected, but it said nothing. The shot went out; whether it
        # was taken is not something this can honestly claim.
        return False

    def check_simulator(self) -> Dict[str, Any]:
        if self.mode is PlayMode.LOCAL:
            # The one thing that can be wrong here is saving, so save something.
            try:
                self.shots.set_club(self.shots.club)
                self._capture_error = ""
            except Exception as exc:
                self._capture_error = str(exc) or exc.__class__.__name__
        self.connect_simulator()
        return self.status()

    def send_test_shot(self) -> Dict[str, Any]:
        """Send one deliberate shot. The user is warned before this is called."""

        if self.mode is PlayMode.LOCAL:
            raise ValueError("The Local Range has no simulator to send a test shot to")
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
        status = self.simulator_status()
        with self._lock:
            self._reported_simulator = status
        client.send_simulator_status(status)

    # --- Reporting --------------------------------------------------------

    def simulator_status(self) -> Dict[str, Any]:
        if self.mode is PlayMode.LOCAL:
            error = self._capture_error
            return {
                "simulator": self.mode.value,
                "simulatorLabel": self.mode.label,
                # Nothing has to be opened or connected to, so the only way
                # this is not ready is if shots cannot be saved.
                "connected": True,
                "ready": not error,
                "local": True,
                "testShotAccepted": False,
                "message": (
                    "Shots cannot be saved: {}".format(error) if error
                    else "Recording on this computer"
                ),
                "errorCode": CFG_WRITE_FAILED.code if error else "",
            }
        with self._lock:
            session = self._session
            accepted = self._test_shot_accepted
            error = dict(self._last_simulator_error) if self._last_simulator_error else None
        connected = bool(session and session.connected)
        return {
            "simulator": self.mode.value,
            "simulatorLabel": self.mode.label,
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
        steps: List[Dict[str, Any]] = [
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
        ]
        if self.mode is PlayMode.LOCAL:
            steps.append({
                "key": "capture",
                "title": "Shots are being recorded",
                "ok": simulator["ready"],
                "detail": simulator["message"],
            })
        else:
            steps += [{
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
            }]
        for step in steps:
            step["blocking"] = not step["ok"]
        return steps

    #: Enclosure self-test checks this computer cannot evaluate for itself.
    ENCLOSURE_CHECKS = (
        "hardware", "cameras", "pitracWeb", "calibration", "strobe",
        "pitracMeasurement", "pitracTarget",
    )

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
            if self._last_connect_error is not None:
                return _state_for_code(self._last_connect_error.get("code"))
            return State.SETUP_REQUIRED
        if not client.connected:
            if client.last_error is None:
                return State.CONNECTING
            return _state_for_code(client.last_error.get("code"))

        steps = {step["key"]: step["ok"] for step in self.chain()}
        if all(steps.values()):
            return State.READY_TO_PLAY
        if not steps.get("link", False):
            return State.SETUP_REQUIRED
        if not steps.get("pitrac", False):
            return State.RECOVERY_REQUIRED
        if not steps.get("capture", True):
            return State.RECOVERY_REQUIRED
        if not steps.get("simulator", True):
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
        reply = client.call(
            name, arguments or {}, timeout=COMMAND_TIMEOUTS.get(name, COMMAND_TIMEOUT)
        )
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
            # Explicit lifecycle, so "server started" cannot be mistaken for
            # "the operating-system window exists".
            "window": self.window_state(),
            "state": state.value,
            "headline": state.headline,
            "detail": state.detail,
            "ready": state is State.READY_TO_PLAY,
            "simulator": self.mode.value,
            "simulatorLabel": self.mode.label,
            "playModes": self.play_modes(),
            "simulatorStatus": self.simulator_status(),
            "chain": chain,
            "nextStep": blocking["title"] if blocking else "",
            "link": client.status() if client else {
                "connected": False,
                "lastError": dict(self._last_connect_error) if self._last_connect_error else None,
                "lastErrorDeviceId": self._last_connect_error_device_id,
            },
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

    # --- Desktop self-update ------------------------------------------

    def _active_desktop_updater(self):
        """Which checker owns the desktop-version half of the coordinated
        plan: the git-pull path for a source or development checkout, or
        the packaged release checker for everything else."""

        return self.updates if self._uses_git_updater else self.desktop_updates

    def _periodic_update_check_loop(self, interval: float) -> None:
        wait_for = interval
        while not self._update_check_stop.wait(wait_for):
            self._schedule_update_check()
            failed = bool(self.desktop_updates and self.desktop_updates.last_check_failed)
            wait_for = min(interval, 5 * 60) if failed else interval

    def _schedule_update_check(self, force: bool = False) -> bool:
        """Schedule the only network-capable check path and return immediately."""
        with self._lock:
            if self._update_check_in_progress:
                return False
            self._update_check_in_progress = True
            if self._desktop_update_state in _PASSIVE_DESKTOP_UPDATE_STATES:
                self._desktop_update_state = DesktopUpdateState.CHECKING
                self._desktop_update_detail = "Checking for updates…"

        def work() -> None:
            try:
                status = self._active_desktop_updater().check(force=force)
                self._on_desktop_update_checked(status)
            finally:
                with self._lock:
                    self._update_check_in_progress = False

        threading.Thread(target=work, daemon=True).start()
        return True

    def _on_desktop_update_checked(self, status: UpdateStatus) -> None:
        with self._lock:
            self._last_desktop_status = status
            self._desktop_update_available_version = status.latest
            if self._desktop_update_state not in _PASSIVE_DESKTOP_UPDATE_STATES:
                # A download, verification, or install is in progress (or
                # just finished) -- a background check landing in the middle
                # of that must not stomp on it.
                return
            if status.available:
                self._desktop_update_state = DesktopUpdateState.AVAILABLE
            elif self.desktop_updates is not None and self.desktop_updates.last_check_failed:
                self._desktop_update_state = DesktopUpdateState.CHECK_FAILED
            else:
                self._desktop_update_state = DesktopUpdateState.UP_TO_DATE
            self._desktop_update_detail = status.detail

    def _check_last_install_result(self) -> None:
        """Read once at startup: did the process that just exited hand off
        to a helper that installed and relaunched this one?"""

        if self.desktop_updates is None:
            return
        result = self_update.read_and_clear_last_result()
        if result is None:
            return
        self._apply_install_result(result)
        self_update.prune_transactions()

    def _apply_install_result(self, result: Dict[str, Any]) -> None:
        """Apply one helper result to the running app's persistent status."""

        detail = str(result.get("detail") or "")
        with self._lock:
            if not result.get("success"):
                self._desktop_update_state = (
                    DesktopUpdateState.ROLLED_BACK
                    if result.get("rolledBack") else DesktopUpdateState.INSTALL_FAILED
                )
                self._desktop_update_detail = detail or "The update could not be installed."
            elif "could not restart" in detail:
                self._desktop_update_state = DesktopUpdateState.RESTART_REQUIRED
                self._desktop_update_detail = detail
            else:
                self._desktop_update_state = DesktopUpdateState.UP_TO_DATE
                self._desktop_update_detail = detail or "Updated to {}.".format(self.version)

    def watch_install_result(self, journal_path: Path, timeout: float = 90.0) -> None:
        """Receive the helper result in this restarted process, without another restart."""

        expected = Path(journal_path)

        def watch() -> None:
            deadline = time.monotonic() + timeout
            result_path = expected.parent / "result.json"
            while time.monotonic() < deadline:
                try:
                    result = jsontext.loads(result_path.read_text(encoding="utf-8"))
                    journal = self_update.load_journal(expected)
                    if result.get("transactionId") != journal["transactionId"]:
                        raise ValueError("the install result identifies another transaction")
                    self._apply_install_result(result)
                    global_result = self_update.read_and_clear_last_result()
                    if (
                        global_result is not None
                        and global_result.get("transactionId") != result.get("transactionId")
                    ):
                        # Another transaction's result is never silently
                        # consumed. Put its exact data back atomically.
                        self_update._atomic_json(
                            self_update.staging_dir() / "last-install-result.json",
                            global_result,
                        )
                    self_update.prune_transactions()
                    return
                except (OSError, ValueError, self_update.SelfUpdateError):
                    time.sleep(0.2)

        threading.Thread(target=watch, daemon=True).start()

    def _reset_desktop_operation_locked(self) -> Optional[Path]:
        old_transaction = self._desktop_transaction_root
        self._staged_install = None
        self._staged_target_version = ""
        self._desktop_transaction_root = None
        self._desktop_journal_path = None
        self._desktop_archive_path = None
        self._desktop_asset_digest = ""
        self._desktop_asset_name = ""
        self._desktop_release_tag = ""
        self._desktop_downloaded_bytes = 0
        self._desktop_download_total = None
        self._desktop_operation_generation += 1
        return old_transaction

    def _desktop_update_payload(self) -> Dict[str, Any]:
        with self._lock:
            manual_package = (
                self._desktop_archive_path
                if self._desktop_update_state is DesktopUpdateState.PREFLIGHT_FAILED else None
            )
            return {
                "state": self._desktop_update_state.value,
                "installedVersion": self.version,
                "availableVersion": self._desktop_update_available_version,
                "detail": self._desktop_update_detail,
                "stagedReady": self._staged_install is not None,
                "stagedTargetVersion": self._staged_target_version,
                "transactionId": (
                    self._desktop_transaction_root.name.removeprefix("transaction-")
                    if self._desktop_transaction_root else str(self.store.get("updateTransactionId", "") or "")
                ),
                "downloadedBytes": self._desktop_downloaded_bytes,
                "downloadTotalBytes": self._desktop_download_total,
                "downloadProgress": (
                    self._desktop_downloaded_bytes / self._desktop_download_total
                    if self._desktop_download_total else None
                ),
                "canCancel": self._desktop_update_state in (
                    DesktopUpdateState.DOWNLOADING,
                    DesktopUpdateState.VERIFYING,
                    DesktopUpdateState.STAGING,
                ),
                # Use the same canonical path the reveal operation returns.
                # On macOS /var is a symlink to /private/var; presenting one
                # spelling and returning the other makes the UI look as if a
                # different file was selected even though it was not.
                "savedPackagePath": (
                    str(manual_package.resolve()) if manual_package else ""
                ),
                "revealAction": (
                    "Reveal in Finder" if platform.system() == "Darwin"
                    else "Show in File Explorer" if platform.system() == "Windows"
                    else "Show downloaded file"
                ),
            }

    def trigger_update_check(self) -> None:
        """A fresh, non-blocking check, safe to call whenever it is useful --
        at startup once the window is actually usable, in particular, so a
        check that raced ahead of the window is not the only one that ever
        runs. A cache hit makes this a no-op; force is deliberately not used
        here, so this never fights a check already legitimately in flight."""

        self._schedule_update_check()

    def download_desktop_update(self) -> Dict[str, Any]:
        """Start the background download-verify-stage sequence.

        Returns immediately; progress is read back from status()'s
        ``update.desktop`` object, the same way the rest of the app already
        polls for everything else.
        """

        if self.desktop_updates is None:
            return {
                "started": False,
                "detail": "This copy updates itself with git pull; there is nothing to download.",
            }
        with self._lock:
            if self._desktop_update_state in (
                DesktopUpdateState.DOWNLOADING,
                DesktopUpdateState.VERIFYING,
                DesktopUpdateState.STAGING,
                DesktopUpdateState.READY_TO_RESTART,
                DesktopUpdateState.INSTALLING,
            ):
                return {"started": False, "detail": "An update is already being prepared."}
            old_transaction = self._reset_desktop_operation_locked()
            operation = self._desktop_operation_generation
            self._desktop_update_state = DesktopUpdateState.DOWNLOADING
            self._desktop_update_detail = "Preparing the exact selected release…"
            self._desktop_cancel = threading.Event()
        if old_transaction is not None:
            try:
                self_update.discard_unstarted_transaction(old_transaction)
            except self_update.SelfUpdateError:
                pass
        threading.Thread(
            target=self._download_desktop_update_worker,
            args=(operation,), daemon=True,
        ).start()
        return {"started": True}

    def cancel_desktop_update(self) -> Dict[str, Any]:
        with self._lock:
            if self._desktop_update_state not in (
                DesktopUpdateState.DOWNLOADING,
                DesktopUpdateState.VERIFYING,
                DesktopUpdateState.STAGING,
            ):
                return {"cancelled": False, "detail": "No desktop update is being prepared."}
            self._desktop_cancel.set()
            self._desktop_update_detail = "Cancelling the desktop update…"
        return {"cancelled": True}

    def _fail_desktop_update(self, state: DesktopUpdateState, detail: str,
                             operation: Optional[int] = None) -> None:
        with self._lock:
            if (
                operation is not None
                and operation != self._desktop_operation_generation
            ):
                return
            self._desktop_update_state = state
            self._desktop_update_detail = detail

    def _download_desktop_update_worker(self, operation: int) -> None:
        transaction_root = None
        try:
            checked = self.desktop_updates.cached_status()
            if not checked.available:
                checked = self.desktop_updates.check(force=True)
            if not checked.available:
                state = (
                    DesktopUpdateState.CHECK_FAILED
                    if self.desktop_updates.last_check_failed
                    else DesktopUpdateState.UP_TO_DATE
                )
                self._fail_desktop_update(state, checked.detail, operation)
                return
            if not checked.can_apply:
                self._fail_desktop_update(
                    DesktopUpdateState.DOWNLOAD_FAILED, checked.detail, operation
                )
                return

            tag = str(checked.latest or "")
            release = self.desktop_updates.release_for_tag(tag)
            asset = self.desktop_updates.asset_name()
            url = self.desktop_updates.asset_download_url(release, asset)
            if not url:
                self._fail_desktop_update(
                    DesktopUpdateState.DOWNLOAD_FAILED,
                    "That release has no {} package to download.".format(asset),
                    operation,
                )
                return
            # Authenticate the release's own description of itself before
            # anything in it is believed -- including the digest below, which
            # otherwise arrives from the same listing as the URL it describes.
            try:
                manifest = self.desktop_updates.signed_manifest(release, tag)
            except release_manifest.ManifestError as exc:
                self._fail_desktop_update(
                    DesktopUpdateState.VERIFY_FAILED, str(exc), operation
                )
                return
            if manifest is not None:
                refusal = release_manifest.check_desktop_supported(
                    manifest, version=self.version,
                    system=self.desktop_updates.system,
                    machine=self.desktop_updates.machine,
                )
                if refusal:
                    self._fail_desktop_update(
                        DesktopUpdateState.DOWNLOAD_FAILED, refusal, operation
                    )
                    return
                signed_asset = release_manifest.desktop_asset_for(
                    manifest, self.desktop_updates.system, self.desktop_updates.machine,
                )
                if signed_asset != asset:
                    self._fail_desktop_update(
                        DesktopUpdateState.VERIFY_FAILED,
                        "Version {} signs {} for this computer, not {}.".format(
                            release_manifest.declared_version(manifest), signed_asset, asset
                        ),
                        operation,
                    )
                    return
            expected = self.desktop_updates.expected_sha256(release, asset, manifest)
            if not expected:
                self._fail_desktop_update(
                    DesktopUpdateState.VERIFY_FAILED,
                    "That release publishes no checksum for its package, so it was not downloaded.",
                    operation,
                )
                return

            transaction_root = self_update.new_transaction_dir()
            with self._lock:
                if operation != self._desktop_operation_generation:
                    self_update.discard_unstarted_transaction(transaction_root)
                    return
                self._desktop_transaction_root = transaction_root
            try:
                def progress(written, total):
                    with self._lock:
                        if operation != self._desktop_operation_generation:
                            return
                        self._desktop_downloaded_bytes = written
                        self._desktop_download_total = total
                        self._desktop_update_detail = (
                            "Downloaded {} of {} bytes.".format(written, total)
                            if total else "Downloaded {} bytes.".format(written)
                        )
                path = self.desktop_updates.download(
                    url, transaction_root, cancel_event=self._desktop_cancel, progress=progress
                )
            except InterruptedError:
                self_update.discard_unstarted_transaction(transaction_root)
                with self._lock:
                    self._desktop_transaction_root = None
                self._fail_desktop_update(
                    DesktopUpdateState.CANCELLED,
                    "The download was cancelled. The installed application was not changed.",
                    operation,
                )
                return
            except Exception as exc:
                try:
                    self_update.discard_unstarted_transaction(transaction_root)
                except self_update.SelfUpdateError:
                    pass
                self._fail_desktop_update(
                    DesktopUpdateState.DOWNLOAD_FAILED,
                    "The download did not finish: {}".format(exc),
                    operation,
                )
                return

            with self._lock:
                if operation != self._desktop_operation_generation:
                    return
                self._desktop_update_state = DesktopUpdateState.VERIFYING
                self._desktop_update_detail = "Verifying the release SHA-256…"
                self._desktop_archive_path = path
            if not self.desktop_updates.verify(path, expected):
                self_update.discard_unstarted_transaction(transaction_root)
                self._fail_desktop_update(
                    DesktopUpdateState.VERIFY_FAILED,
                    "The download did not match the checksum this release publishes, "
                    "so it was not installed.",
                    operation,
                )
                return

            target_version = str(checked.latest or "").lstrip("v")
            if self._desktop_cancel.is_set():
                raise InterruptedError("the update was cancelled")
            with self._lock:
                if operation != self._desktop_operation_generation:
                    return
                self._desktop_update_state = DesktopUpdateState.STAGING
                self._desktop_update_detail = "Validating the packaged application…"
            try:
                staged = self_update.stage_update(
                    path, transaction_root, target_version,
                    system=self.desktop_updates.system, machine=self.desktop_updates.machine,
                )
            except self_update.SelfUpdateError as exc:
                self_update.discard_unstarted_transaction(transaction_root)
                self._fail_desktop_update(
                    DesktopUpdateState.VERIFY_FAILED, str(exc), operation
                )
                return
            if self._desktop_cancel.is_set():
                raise InterruptedError("the update was cancelled")

            # Persist the exact verified target before the desktop can exit.
            txid = transaction_root.name.removeprefix("transaction-")
            self._remember_update_target(
                target_version, tag=tag, transaction_id=txid, asset_sha256=expected
            )
            try:
                if os.environ.get("PITRAC_FAILURE_INJECT_PREFLIGHT") == "1":
                    raise self_update.SelfUpdateError(
                        "automatic replacement refusal injected by packaged CI"
                    )
                journal_path = self_update.prepare_transaction(
                    archive_path=path,
                    staged=staged,
                    install_root=self_update.current_install_root(system=self.desktop_updates.system),
                    installed_version=self.version,
                    target_version=target_version,
                    expected_tag=tag,
                    asset_name=asset,
                    asset_sha256=expected,
                    transaction_root=transaction_root,
                    system=self.desktop_updates.system,
                    machine=self.desktop_updates.machine,
                    running_executable=(Path(sys.executable) if getattr(sys, "frozen", False) else None),
                    relaunch_arguments=self._desktop_relaunch_arguments,
                )
            except self_update.SelfUpdateError as exc:
                self_update.retain_manual_package(transaction_root, path)
                self._fail_desktop_update(
                    DesktopUpdateState.PREFLIGHT_FAILED,
                    "Automatic installation was refused: {} The verified package is saved at {}."
                    .format(exc, path),
                    operation,
                )
                return
            if self._desktop_cancel.is_set():
                self_update.abort_prepared_transaction(journal_path)
                with self._lock:
                    self._desktop_transaction_root = None
                self._fail_desktop_update(
                    DesktopUpdateState.CANCELLED,
                    "The update was cancelled. The installed application was not changed.",
                    operation,
                )
                return

            with self._lock:
                if operation != self._desktop_operation_generation:
                    return
                self._staged_install = staged
                self._staged_target_version = target_version
                self._desktop_journal_path = journal_path
                self._desktop_asset_digest = expected
                self._desktop_asset_name = asset
                self._desktop_release_tag = tag
                self._desktop_update_state = DesktopUpdateState.READY_TO_RESTART
                self._desktop_update_detail = "Version {} is verified and ready to install.".format(
                    target_version
                )
        except Exception as exc:
            if isinstance(exc, InterruptedError):
                if transaction_root is not None:
                    try:
                        self_update.discard_unstarted_transaction(transaction_root)
                    except Exception:
                        pass
                self._fail_desktop_update(
                    DesktopUpdateState.CANCELLED,
                    "The update was cancelled. The installed application was not changed.",
                    operation,
                )
                return
            self._fail_desktop_update(
                DesktopUpdateState.DOWNLOAD_FAILED,
                "The update could not be prepared: {}".format(exc),
                operation,
            )

    def install_and_restart(self) -> Dict[str, Any]:
        """Hand off to the helper, then exit so it can perform the swap.

        The window close this triggers goes through the same path
        ``/api/quit`` already uses -- there is no separate shutdown
        mechanism to keep in sync.
        """

        with self._lock:
            staged = self._staged_install
            target = self._staged_target_version
            journal_path = self._desktop_journal_path
            state = self._desktop_update_state
            expected_tag = self._desktop_release_tag
            expected_asset = self._desktop_asset_name
            expected_digest = self._desktop_asset_digest
            transaction_root = self._desktop_transaction_root
        if (
            state is not DesktopUpdateState.READY_TO_RESTART
            or staged is None
            or journal_path is None
            or transaction_root is None
        ):
            return {"applied": False, "detail": "No verified update is ready to install yet."}

        try:
            journal = self_update.load_journal(journal_path)
            transaction_id = transaction_root.name.removeprefix("transaction-")
            exact = (
                journal["phase"] == "prepared"
                and journal["transactionId"] == transaction_id
                and journal["targetVersion"] == target
                and journal["expectedReleaseTag"] == expected_tag == "v" + target
                and journal["assetName"] == expected_asset
                and secrets.compare_digest(journal["assetSha256"], expected_digest)
                and Path(journal["stagingPath"]).resolve() == staged.install_root.resolve()
                and str(self.store.get("updateTransactionId", "") or "") == transaction_id
            )
            if not exact:
                raise self_update.SelfUpdateError(
                    "the active update fields do not agree with the verified journal"
                )
            with self._lock:
                if self._desktop_update_state is not DesktopUpdateState.READY_TO_RESTART:
                    raise self_update.SelfUpdateError(
                        "the update is no longer ready to restart"
                    )
                self._desktop_update_state = DesktopUpdateState.INSTALLING
            self_update.spawn_helper(journal_path, wait_pid=os.getpid())
        except Exception as exc:
            detail = "The installer could not be started: {}".format(exc)
            self._fail_desktop_update(DesktopUpdateState.INSTALL_FAILED, detail)
            return {"applied": False, "detail": detail}

        threading.Timer(0.4, self.close_native_window).start()
        return {
            "applied": True,
            "detail": "Installing {} and restarting.".format(target),
            "needsRestart": True,
        }

    def _update_status(self, force: bool = False) -> Dict[str, Any]:
        """Return the last known state immediately; this never performs I/O."""

        with self._lock:
            linked = bool(self._link and self._link.connected)
            pending_target = self._pending_update_target
            enclosure_version = (
                (self._pi_status or {}).get("version", "") if linked else ""
            )
            checked = self._last_desktop_status
        status = checked.as_dict()
        status["enclosureVersion"] = enclosure_version
        # The two halves are meant to move together. Saying so is more useful
        # than letting someone update one and wonder why the other complains.
        status["versionsMatch"] = (
            not enclosure_version or enclosure_version == self.version
        )
        plan = coordinate_update(checked, enclosure_version, pending_target)
        status["coordination"] = plan.as_dict()
        status["desktop"] = self._desktop_update_payload()
        # Forget the saved plan once it is finished -- either both halves
        # reached it, or this desktop moved past it and it has been ignored.
        # Only the first case used to clear it, so an overtaken plan was read
        # again on every check and kept blocking.
        if pending_target and (plan.synchronized or plan.discard_pending):
            self._remember_update_target("")
        return status

    def check_for_updates(self) -> Dict[str, Any]:
        started = self._schedule_update_check(force=True)
        status = self._update_status()
        status["checkStarted"] = started
        return status

    def apply_update(self) -> Dict[str, Any]:
        if self._uses_git_updater:
            return self.updates.apply()
        return self.install_and_restart()

    def prepare_update(self, target_tag: str) -> Dict[str, Any]:
        """Persist the release selected before the desktop is replaced."""

        target = str(target_tag or "").strip().lstrip("v")
        current = self._update_status()
        plan = current.get("coordination") or {}
        if (
            plan.get("phase") != "desktop-update-required"
            or compare(str(plan.get("targetVersion") or ""), target) != 0
        ):
            return {
                "prepared": False,
                "detail": plan.get("detail") or "That release is not the current update target.",
                "coordination": plan,
            }
        self._remember_update_target(target)
        return {
            "prepared": True,
            "targetVersion": target,
            "detail": (
                "Update target {} is saved. Install it and restart the desktop app; the Pi "
                "will remain unchanged until then."
            ).format(target),
        }

    def _remember_update_target(self, target: str, *, tag: str = "",
                                transaction_id: str = "", asset_sha256: str = "") -> None:
        with self._lock:
            self._pending_update_target = str(target or "")
        self.store.update({
            "updateTarget": self._pending_update_target,
            "updateTag": str(tag or "") if target else "",
            "updateTransactionId": str(transaction_id or "") if target else "",
            "updateAssetSha256": str(asset_sha256 or "") if target else "",
        })

    def apply_pi_update(self, target_tag: str) -> Dict[str, Any]:
        """Start the Pi half only after the desktop is already at that release."""

        target = str(target_tag or "").strip().lstrip("v")
        current = self._update_status()
        plan = current.get("coordination") or {}
        if (
            plan.get("phase") != "pi-update-required"
            or compare(str(plan.get("targetVersion") or ""), target) != 0
        ):
            return {
                "started": False,
                "applied": False,
                "detail": plan.get("detail") or "The ordered update plan did not permit this.",
                "coordination": plan,
            }

        exact_tag = "v" + target
        found = self.command("checkForUpdates", {"targetTag": exact_tag})
        if (
            compare(str(found.get("latest") or ""), exact_tag) != 0
            or not found.get("available")
            or not found.get("canApply")
        ):
            return {
                "started": False,
                "applied": False,
                "detail": found.get("detail") or "PiTrac cannot install that exact release.",
                "targetVersion": target,
            }

        self._remember_update_target(target)
        try:
            result = self.command("applyUpdate", {"targetTag": exact_tag})
        except EasyConnectError:
            client = self._link
            if client is not None and client.connected:
                self._remember_update_target("")
                raise
            # systemd restarts the Pi service from inside the command. The
            # command socket normally disappears before a reply can arrive.
            result = {"applied": True}
        if not result.get("applied"):
            self._remember_update_target("")
            return {**result, "started": False, "targetVersion": target}
        return {
            **result,
            "started": True,
            "targetVersion": target,
            "detail": (
                "PiTrac is restarting into {}. Success will be confirmed only after it "
                "reconnects and reports the same version as this app."
            ).format(target),
        }

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
        chosen = self.shots.set_club(club)
        if self.mode is PlayMode.LOCAL:
            # Choosing one is also how to say "stop choosing for me".
            self.store.set("autoClub", False)
            self._tell_pitrac_the_club()
        return {"club": chosen}

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
                detected = jsontext.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError, OSError) as exc:
            return {"available": False, "message": "PiTrac did not answer: {}".format(exc)}
        detected["available"] = True
        detected["dashboardUrl"] = base
        return detected

    def close(self) -> None:
        self._update_check_stop.set()
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
            return jsontext.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            payload = jsontext.loads(error.read().decode("utf-8"))
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

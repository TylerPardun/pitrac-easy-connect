"""The Easy Connect service that runs on the enclosure.

Owns the boot sequence, holds the pieces together, and answers both the setup
page and the paired Companion from one place so the two can never disagree
about what state the enclosure is in.

The boot sequence is ordered so that the enclosure is reachable as early as
possible. Networking is recovered before anything else, because an enclosure
nobody can reach cannot be told about any other problem it has.
"""

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import __version__
from ..common import discovery, link
from ..common.configstore import ConfigStore
from ..common.errors import EasyConnectError, LINK_LOST
from ..common.identity import IdentityStore
from ..common.states import State
from ..common import updates as updates_module
from ..common.updates import ArchiveUpdater, Updater
from ..models import Simulator
from .backend import BackendError, PiBackend
from .backup import BackupManager
from .link_server import CompanionLinkServer, CompanionSession
from .pairing import PairingManager
from . import ml_models
from .pitrac import PitracInstallation
from .relay import DEFAULT_RELAY_PORTS, ShotRelay
from .selftest import SelfTest, state_for
from .wifi import WifiProvisioner

DEFAULT_STATE_DIR = Path("/var/lib/pitrac-easy-connect")
POLL_SECONDS = 2.0


@dataclass
class ServicePaths:
    root: Path = DEFAULT_STATE_DIR

    @property
    def identity(self) -> Path:
        return self.root / "device.json"

    @property
    def settings(self) -> Path:
        return self.root / "settings.json"

    @property
    def network(self) -> Path:
        return self.root / "network.json"

    @property
    def pairings(self) -> Path:
        return self.root / "pairings.json"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def downloads(self) -> Path:
        """Where Companion builds live, to be handed to the owner's PC."""

        return self.root / "companion"


class PiService:
    def __init__(
        self,
        backend: PiBackend,
        paths: Optional[ServicePaths] = None,
        pitrac: Optional[PitracInstallation] = None,
        relay_ports: Optional[Dict[Simulator, int]] = None,
        link_port: int = link.LINK_PORT,
        discovery_port: int = discovery.DISCOVERY_PORT,
        portal_port: int = 80,
        version: str = __version__,
        manage_hostname: bool = True,
        models_dir=None,
        #: How long boot waits for the radio before deciding the saved
        #: network is gone. Tests pass 0 so they do not wait for real.
        boot_grace: Optional[float] = None,
    ):
        self.backend = backend
        self.paths = paths or ServicePaths()
        self.version = version
        self.portal_port = portal_port
        self.manage_hostname = manage_hostname
        self.paths.root.mkdir(parents=True, exist_ok=True)

        self.identity_store = IdentityStore(self.paths.identity)
        self.identity = self.identity_store.identity
        self.settings = ConfigStore(
            self.paths.settings,
            defaults={"simulator": Simulator.GSPRO.value, "setupCompleted": False},
            schema_version=1,
        )
        self.pairings = PairingManager(self.paths.pairings, self.identity.device_id)
        self.pitrac = pitrac or PitracInstallation()
        self.relay = ShotRelay(ports=dict(relay_ports or DEFAULT_RELAY_PORTS))
        self.provisioner = WifiProvisioner(
            backend, self.paths.network, self.identity.setup_ssid,
            self.identity.setup_password, boot_grace=boot_grace,
        )
        self.link_server = CompanionLinkServer(
            self.pairings,
            device_info=self.device_info,
            version=version,
            on_attach=self._on_companion_attach,
            on_detach=self._on_companion_detach,
            on_frame=self._on_companion_frame,
            port=link_port,
        )
        self.backups = BackupManager(
            self.identity_store,
            self.settings,
            self.pitrac,
            self.pairings,
            self.paths.backups,
            version=version,
        )
        # An enclosure installed by install.sh has no git checkout, so the
        # source updater has nothing to pull. It fetches the release archive
        # and swaps it in instead. Anywhere else -- a development checkout, a
        # test -- the ordinary updater still applies.
        self.updates = Updater(version)
        # Where the installer puts releases, and the symlink that points at
        # the live one. Updating in place would modify the running release
        # directory; instead a new sibling release is created and the symlink
        # is moved, which is one atomic operation and leaves the old release
        # on disk to go back to.
        self.enclosure_updates = ArchiveUpdater(
            installed=version,
            app_dir=Path(__file__).resolve().parent.parent.parent,
            link_path=Path("/usr/lib/pitrac-easy-connect"),
            releases_dir=Path("/usr/lib/pitrac-easy-connect-releases/releases"),
            restart=self._restart_service,
            verify=_can_run,
        )
        self.discovery = discovery.DiscoveryResponder(self.describe, port=discovery_port)

        self._lock = threading.RLock()
        self._state = State.STARTING
        self._simulator_status: Optional[Dict[str, Any]] = None
        self._last_report = None
        self._stop = threading.Event()
        self._poller: Optional[threading.Thread] = None
        self._boot_messages: List[str] = []
        self.started_at = time.time()
        self.shutting_down = False

        self.selftest = SelfTest(
            backend,
            self.pitrac,
            self.relay.ports,
            network_status=self.provisioner.status,
            companion_connected=lambda: self.link_server.connected,
            simulator_status=lambda: self._simulator_status,
            config_problems=self._config_problems,
            relay_listening=lambda: self.relay.listening,
            models_dir=models_dir,
        )

    # --- Boot -------------------------------------------------------------

    def start(self) -> None:
        self._note("Easy-Connect {} starting".format(self.version))

        # 1. Networking first. Everything else can be reported once the
        #    enclosure is reachable; none of it can be reported if it is not.
        try:
            result = self.provisioner.recover_after_boot()
            self._note(result.message)
        except Exception as exc:
            self._note("Network recovery failed: {}".format(exc))

        # 2. The relay, before PiTrac is pointed at it, so nothing PiTrac sends
        #    arrives at a closed port.
        try:
            self.relay.start()
            self.selftest.relay_ports = self.relay.ports
            self._note(
                "Shot relay listening for PiTrac on {}".format(
                    ", ".join(
                        "{} port {}".format(simulator.label, port)
                        for simulator, port in sorted(
                            self.relay.ports.items(), key=lambda item: item[0].value
                        )
                    )
                )
            )
        except OSError as exc:
            self._note("Shot relay could not start: {}".format(exc))

        # 3. Point PiTrac at the relay. Idempotent, so this is a no-op after
        #    the first boot.
        try:
            changed = self.pitrac.point_at_relay(self.relay.ports)
            if changed:
                self._note("Pointed PiTrac at Easy-Connect ({} settings)".format(len(changed)))
        except OSError as exc:
            self._note("Could not update PiTrac settings: {}".format(exc))

        if self.manage_hostname:
            self._apply_hostname()

        try:
            self.link_server.start()
            self._note("Waiting for a computer on port {}".format(self.link_server.port))
        except OSError as exc:
            self._note("Could not listen for computers: {}".format(exc))

        try:
            self.discovery.start()
        except OSError as exc:
            self._note("Discovery could not start: {}".format(exc))

        self._publish_mdns()
        self.refresh()

        self._stop.clear()
        self._poller = threading.Thread(target=self._poll_loop, daemon=True)
        self._poller.start()

    def stop(self) -> None:
        self._stop.set()
        if self._poller is not None:
            self._poller.join(timeout=3)
        for closer in (self.discovery.stop, self.link_server.stop, self.relay.stop):
            try:
                closer()
            except Exception:
                pass

    def __enter__(self) -> "PiService":
        self.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.stop()

    def _apply_hostname(self) -> None:
        try:
            if self.backend.hostname() != self.identity.hostname:
                self.backend.set_hostname(self.identity.hostname)
                self._note("Hostname set to {}".format(self.identity.hostname))
        except BackendError as exc:
            self._note("Could not set the hostname: {}".format(exc))

    def _publish_mdns(self) -> None:
        try:
            self.backend.publish_mdns_service(
                self.identity.display_name,
                self.link_server.port,
                {
                    "deviceId": self.identity.device_id,
                    "version": self.version,
                    "hardware": self.identity.hardware_profile,
                },
            )
        except BackendError as exc:
            self._note("Could not advertise on the network: {}".format(exc))

    def _note(self, message: str) -> None:
        with self._lock:
            self._boot_messages.append(message)
            del self._boot_messages[: max(0, len(self._boot_messages) - 40)]

    def _config_problems(self) -> List[str]:
        problems = []
        for name, store in (
            ("device settings", self.settings),
            ("network settings", self.provisioner.journal),
        ):
            if getattr(store, "recovered_from_backup", False):
                problems.append(name)
        return problems

    # --- The running loop -------------------------------------------------

    def _poll_loop(self) -> None:
        last_refresh = 0.0
        while not self._stop.is_set():
            try:
                rolled_back = self.provisioner.poll()
                if rolled_back is not None:
                    self._note(rolled_back.message)
            except Exception:
                pass
            try:
                # A Companion that is connected but wedged would otherwise leave
                # PiTrac waiting on a reply that never comes.
                self.relay.sweep()
            except Exception:
                pass
            if time.monotonic() - last_refresh > POLL_SECONDS * 2:
                last_refresh = time.monotonic()
                try:
                    self.refresh()
                except Exception:
                    pass
            self._stop.wait(POLL_SECONDS)

    def refresh(self) -> State:
        report = self.selftest.run()
        network = self.provisioner.status()
        state = state_for(report, network, self.link_server.connected)
        with self._lock:
            if self.shutting_down:
                state = State.SHUTTING_DOWN
            self._last_report = report
            self._state = state
        self._push_status()
        return state

    def _push_status(self) -> None:
        """Send the enclosure's view to the attached computer, if there is one."""

        session = self.link_server.session
        if session is None or not session.authenticated:
            return
        try:
            session.send(link.enclosure_status(self.compact_status()))
        except Exception:
            # The link dying is handled by the link server, not here.
            pass

    def compact_status(self) -> Dict[str, Any]:
        """The subset of state the Companion shows, small enough to push often."""

        with self._lock:
            report = self._last_report
            state = self._state
        return {
            "state": state.value,
            "headline": state.headline,
            "detail": state.detail,
            "version": self.version,
            "device": self.identity.as_dict(),
            "dashboardUrl": self.dashboard_url(),
            "network": self.provisioner.status(),
            "relay": self.relay.status(),
            "pitrac": self.pitrac.status(self.backend, self.relay.ports).as_dict(),
            "images": self.pitrac.recent_images(),
            "selfTest": report.as_dict() if report else None,
        }

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    # --- What the Companion sees -----------------------------------------

    def device_info(self) -> Dict[str, Any]:
        value = self.identity.as_dict()
        value["version"] = self.version
        value["state"] = self.state.value
        value["protocol"] = link.PROTOCOL_VERSION
        value["portalPort"] = self.portal_port
        value["dashboardUrl"] = self.dashboard_url()
        return value

    def dashboard_url(self) -> str:
        from .pitrac import dashboard_url

        connection = self.backend.active_connection()
        return dashboard_url(connection.ipv4 if connection else "")

    def describe(self) -> Dict[str, Any]:
        connection = self.backend.active_connection()
        return {
            "deviceId": self.identity.device_id,
            "displayName": self.identity.display_name,
            "hostname": self.identity.hostname,
            "linkPort": self.link_server.port,
            "portalPort": self.portal_port,
            "version": self.version,
            "state": self.state.value,
            "address": (connection.ipv4.split("/")[0] if connection and connection.ipv4 else ""),
            "dashboardUrl": self.dashboard_url(),
        }

    def _on_companion_attach(self, session: CompanionSession) -> None:
        self.relay.attach_companion(session.send)
        self._note("{} connected".format(session.computer_name))
        if not self.settings.get("setupCompleted"):
            self.settings.set("setupCompleted", True)
        # A Companion arriving on a network the enclosure just moved to is
        # proof the move worked. This is what closes the confirmation window.
        if self.provisioner.awaiting_confirmation:
            self.provisioner.confirm()
            self._note("The new network was confirmed by {}".format(session.computer_name))
        self.refresh()

    def _on_companion_detach(self, session: CompanionSession) -> None:
        self.relay.detach_companion()
        with self._lock:
            self._simulator_status = None
        self._note("{} disconnected".format(session.computer_name or "The computer"))
        self.refresh()

    def _on_companion_frame(self, session: CompanionSession, frame: Dict[str, Any]) -> None:
        kind = frame.get("type")
        if kind == "simulatorMessage":
            self.relay.handle_simulator_message(frame.get("payload") or {})
        elif kind == "shotResult":
            self.relay.handle_shot_result(frame)
        elif kind == "simulatorStatus":
            with self._lock:
                self._simulator_status = dict(frame.get("status") or {})
            self.refresh()
        elif kind == "command":
            self._run_command(session, frame)

    def _run_command(self, session: CompanionSession, frame: Dict[str, Any]) -> None:
        request_id = frame.get("id")
        name = str(frame.get("command", ""))
        arguments = frame.get("arguments") or {}
        try:
            data = self.command(name, arguments)
            session.send(link.command_result(request_id, True, data))
        except EasyConnectError as exc:
            session.send(link.command_result(request_id, False, error_info=exc.as_dict()))
        except Exception as exc:
            session.send(
                link.command_result(
                    request_id,
                    False,
                    error_info={
                        "code": LINK_LOST.code,
                        "failed": str(exc),
                        "nextStep": "Try again. If it repeats, restart PiTrac.",
                        "stillSafe": "Nothing on the enclosure was changed.",
                    },
                )
            )

    # --- Commands ---------------------------------------------------------

    def command(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        arguments = arguments or {}
        handler = self._commands().get(name)
        if handler is None:
            raise ValueError("Unknown request: {}".format(name))
        return handler(arguments)

    def _commands(self) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        return {
            "status": lambda a: self.status(),
            "selfTest": lambda a: self._rerun_self_test(),
            "scanNetworks": lambda a: {
                "networks": [n.as_dict() for n in self.provisioner.scan()]
            },
            "setCountry": lambda a: self._set_country(a),
            "joinNetwork": lambda a: self._join(a),
            "confirmNetwork": lambda a: self.provisioner.confirm().as_dict(),
            "setDirectMode": lambda a: self.provisioner.set_direct_mode(
                bool(a.get("enabled"))
            ).as_dict(),
            "selectSimulator": lambda a: self._select_simulator(a),
            "rename": lambda a: self._rename(a),
            "trustedComputers": lambda a: {"computers": self.pairings.trusted_computers()},
            "renameComputer": lambda a: self._rename_computer(a),
            "revokeComputer": lambda a: self._revoke_computer(a),
            "resetNetwork": lambda a: self._reset_network(),
            "modelLicence": lambda a: ml_models.licence_text(),
            "installModels": lambda a: self._install_models(a),
            "prepareForNewOwner": lambda a: self._prepare_for_new_owner(a),
            "restartPitrac": lambda a: self._restart_pitrac(),
            "reboot": lambda a: self._reboot(),
            "shutdown": lambda a: self._shutdown(),
            "ownerCard": lambda a: {"text": self.identity.owner_card()},
            "checkForUpdates": lambda a: self._check_updates(),
            "applyUpdate": lambda a: self._apply_update(),
            "createBackup": lambda a: self._create_backup(a),
            "inspectBackup": lambda a: self.backups.inspect(str(a.get("file", ""))).as_dict(),
            "restoreBackup": lambda a: self._restore_backup(a),
        }

    def _rerun_self_test(self) -> Dict[str, Any]:
        self.refresh()
        return self.status()

    def _set_country(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.provisioner.set_country(str(arguments.get("country", "")))
        return {"country": self.provisioner.country()}

    def _join(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        result = self.provisioner.join(
            str(arguments.get("ssid", "")),
            arguments.get("password"),
            hidden=bool(arguments.get("hidden")),
        )
        self.refresh()
        return result.as_dict()

    def _select_simulator(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        simulator = Simulator(str(arguments.get("simulator", "")))
        self.settings.set("simulator", simulator.value)
        return {"simulator": simulator.value, "simulatorLabel": simulator.label}

    def _rename(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.identity = self.identity_store.rename(str(arguments.get("name", "")))
        self._publish_mdns()
        return self.identity.as_dict()

    def _rename_computer(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.pairings.rename(str(arguments.get("pairingId", "")), str(arguments.get("name", "")))
        return {"computers": self.pairings.trusted_computers()}

    def _revoke_computer(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        pairing_id = str(arguments.get("pairingId", ""))
        self.pairings.revoke(pairing_id)
        session = self.link_server.session
        if session is not None and session.pairing_id == pairing_id:
            # Revocation has to take effect now, not at the next reconnect.
            session.close()
        return {"computers": self.pairings.trusted_computers()}

    def _reset_network(self) -> Dict[str, Any]:
        """Removes saved Wi-Fi only. Pairings and calibration are untouched."""

        self.provisioner.forget_all_networks()
        result = self.provisioner.start_setup_hotspot()
        self.refresh()
        return {
            "removed": "networks",
            "kept": ["pairings", "calibration", "simulator settings"],
            "network": result.as_dict(),
        }

    def _prepare_for_new_owner(self, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Strip this enclosure back to something that can be handed on.

        The trained models have to go with everything else. Their licence is
        non-transferable, so passing on a machine with them still on it is a
        breach even when no money changes hands — the next owner has to get
        their own copy under their own acceptance of PiTracLM's terms. See
        ``ml_models`` for why the source clone goes too.
        """

        arguments = arguments or {}
        self.provisioner.forget_all_networks()
        self.pairings.revoke_all()
        self.settings.replace({})

        removed = ["networks", "paired computers", "preferences"]
        kept = ["installed software", "camera calibration"]
        models: Dict[str, Any] = {}
        if arguments.get("keepModels"):
            # Only for a machine that is not actually leaving your hands.
            kept.append("trained models")
        else:
            models = ml_models.remove(home=self._pitrac_home())
            removed.append("trained models and the PiTrac source clone")

        self.identity_store.regenerate_setup_password()
        self.identity = self.identity_store.identity
        self.provisioner.setup_password = self.identity.setup_password
        result = self.provisioner.start_setup_hotspot()
        self.refresh()
        return {
            "removed": removed,
            "kept": kept,
            "models": models,
            "ownerCard": self.identity.owner_card(),
            "network": result.as_dict(),
        }

    def _install_models(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Download PiTracLM's models, once their terms have been accepted.

        The acceptance is not a formality we can supply on the owner's behalf.
        Their licence is granted to whoever accepts it, and the whole reason
        this software fetches rather than ships the models is so that person is
        the owner of the machine rather than whoever built it.
        """

        from ..common.errors import PI_MODEL_DOWNLOAD_FAILED, PI_MODELS_NOT_ACCEPTED

        if not arguments.get("accepted"):
            raise EasyConnectError(
                PI_MODELS_NOT_ACCEPTED, "the terms were not accepted"
            )
        try:
            result = ml_models.install_from_source(
                owner=self.pitrac.intended_owner_ids(),
            )
        except EasyConnectError:
            raise
        except Exception as exc:
            raise EasyConnectError(PI_MODEL_DOWNLOAD_FAILED, str(exc)) from exc

        self.settings.update({"modelsAcceptedAt": time.time()})
        self.refresh()
        result["state"] = self.state.value
        return result

    def _pitrac_home(self) -> Optional[str]:
        """The home directory PiTrac was built in, not root's."""

        return self.pitrac.owner_home()

    def _create_backup(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        document = self.backups.create(
            include_identity=bool(arguments.get("includeIdentity")),
            include_pairings=bool(arguments.get("includePairings")),
        )
        return {
            "filename": self.backups.suggested_filename(),
            "backup": document,
            "info": self.backups.inspect(document).as_dict(),
        }

    def _restore_backup(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        result = self.backups.restore(
            str(arguments.get("file", "")),
            calibration=bool(arguments.get("calibration", True)),
            preferences=bool(arguments.get("preferences", True)),
            identity=bool(arguments.get("identity", False)),
            pairings=bool(arguments.get("pairings", False)),
            confirm_different_device=bool(arguments.get("confirmDifferentDevice", False)),
        )
        # A restore can change the enclosure's name, identity, and the settings
        # PiTrac reads, so everything downstream is rebuilt from disk.
        self.identity = self.identity_store.identity
        self.provisioner.setup_ssid = self.identity.setup_ssid
        self.provisioner.setup_password = self.identity.setup_password
        self.settings.load()
        self._publish_mdns()
        self.refresh()
        return result.as_dict()

    def _updater(self):
        """Whichever updater suits how this copy was installed."""

        return (
            self.updates if self.updates.kind() == updates_module.SOURCE
            else self.enclosure_updates
        )

    def _check_updates(self) -> Dict[str, Any]:
        updater = self._updater()
        if updater is self.updates:
            return self.updates.check(force=True).as_dict()
        return updater.check().as_dict()

    def _apply_update(self) -> Dict[str, Any]:
        return self._updater().apply()

    def _restart_service(self) -> None:
        # Restarting kills this process, so nothing after it in the update runs.
        # That is why the new copy is checked *before* the swap, not after.
        """Restart Easy-Connect itself, so the new code is the running code.

        Deliberately not a plain exit: systemd brings the unit back, and if
        this is not running under systemd there is nothing sensible to do
        anyway, so the caller is told the files are in place either way.
        """

        self.backend.restart_service("pitrac-easy-connect")

    def _restart_pitrac(self) -> Dict[str, Any]:
        from .pitrac import PITRAC_WEB_SERVICE

        self.backend.restart_service(PITRAC_WEB_SERVICE)
        self.refresh()
        return {"restarted": PITRAC_WEB_SERVICE}

    def _reboot(self) -> Dict[str, Any]:
        with self._lock:
            self.shutting_down = True
            self._state = State.SHUTTING_DOWN
        self.backend.reboot()
        return {"rebooting": True}

    def _shutdown(self) -> Dict[str, Any]:
        with self._lock:
            self.shutting_down = True
            self._state = State.SHUTTING_DOWN
        self.backend.shutdown()
        return {"shuttingDown": True, "safeToUnplugWhen": "the green light stops blinking"}

    # --- Reporting --------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        with self._lock:
            report = self._last_report
            state = self._state
            simulator_status = dict(self._simulator_status) if self._simulator_status else None
            messages = list(self._boot_messages)

        facts = self.backend.system_facts()
        session = self.link_server.session
        simulator = Simulator(self.settings.get("simulator", Simulator.GSPRO.value))
        return {
            "version": self.version,
            "state": state.value,
            "headline": state.headline,
            "detail": state.detail,
            "ready": state is State.READY_TO_PLAY,
            "device": self.identity.as_dict(),
            "dashboardUrl": self.dashboard_url(),
            "setupComplete": bool(self.settings.get("setupCompleted")),
            "network": self.provisioner.status(),
            "pairedComputer": session.as_dict() if session else None,
            "trustedComputerCount": self.pairings.count,
            "trustedComputers": self.pairings.trusted_computers(),
            "pairing": self.pairings.status(),
            "simulator": simulator.value,
            "simulatorLabel": simulator.label,
            "simulatorStatus": simulator_status,
            "relay": self.relay.status(),
            "pitrac": self.pitrac.status(self.backend, self.relay.ports).as_dict(),
            "selfTest": report.as_dict() if report else None,
            "system": {
                "model": facts.model,
                "os": facts.os_name,
                "temperatureC": facts.temperature_c,
                "freeBytes": facts.free_bytes,
                "totalBytes": facts.total_bytes,
                "uptimeSeconds": facts.uptime_seconds,
                "throttled": facts.throttled_now,
                "underVoltage": facts.under_voltage_now,
            },
            "log": messages,
            "uptimeSeconds": time.time() - self.started_at,
        }


def _can_run(package: "Path") -> bool:
    """Whether a staged copy of the application will actually start.

    Restarting the service kills the process performing the update, so nothing
    after the restart can check anything or roll anything back. The check has
    to happen before the swap. This runs the staged code in a separate
    interpreter and asks it to build the pieces the service needs, which
    catches the failures that matter -- a truncated download, an import that
    no longer resolves, a version that needs a newer Python.
    """

    import os
    import subprocess
    import sys

    probe = (
        "import sys; sys.path.insert(0, {!r});"
        "import pitrac_easy_connect as p;"
        "from pitrac_easy_connect.pi import service, portal;"
        "from pitrac_easy_connect.common import link, discovery;"
        "assert p.__version__;"
        "print('ok')"
    ).format(str(package.parent))
    # The service runs as root, and this executes code that was just
    # downloaded. Updates are not signed yet, so the download is trusted only
    # as far as TLS to the release host. Dropping to an unprivileged user for
    # the check means that trust does not have to extend to root as well.
    def drop_privileges():                       # pragma: no cover - root only
        import pwd

        try:
            nobody = pwd.getpwnam("nobody")
        except KeyError:
            return
        os.setgroups([])
        os.setgid(nobody.pw_gid)
        os.setuid(nobody.pw_uid)

    lower = None
    if hasattr(os, "geteuid") and os.geteuid() == 0 and hasattr(os, "setuid"):
        lower = drop_privileges

    try:
        done = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=60,
            preexec_fn=lower,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and "ok" in done.stdout

"""Easy Connect's dealings with the PiTrac installation already on the Pi.

Easy Connect is a separate service. It does not build, patch, or link against
PiTrac; it asks PiTrac's own web server what it is doing, and adds one entry to
the list of simulators PiTrac sends shots to.

That entry is a GSPro-format target at ``127.0.0.1:9210``, where the local relay
listens. It is made once and reused, which is the whole point of the relay:
moving to a new house changes nothing here. Any other simulators the owner has
added are theirs, and are left alone.
"""

import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models import Simulator
from .pitrac_api import PitracApi, PitracApiError, PitracUnreachable

PITRAC_HOME = Path(os.path.expanduser("~/.pitrac"))
PITRAC_CONFIG_DIR = PITRAC_HOME / "config"
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

#: Where PiTrac writes the images it measured a shot from. Its own web server
#: serves these at /api/images/<name>, so listing them here is enough — the
#: pictures themselves are always fetched from PiTrac, never copied.
IMAGES_DIR = Path(
    os.environ.get("PITRAC_IMAGES_DIR", os.path.expanduser("~/LM_Shares/Images"))
)

#: Only these are offered as shot images.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

#: A deliberately narrow filename, checked before it is ever put in a URL.
SAFE_IMAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")

#: What our entry in PiTrac's list of simulators is called.
RELAY_SIM_NAME = "Easy-Connect"
RELAY_SIM_TYPE = "gspro"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}

#: How long one look at PiTrac answers further questions. The self-test and the
#: setup page ask several at once, and a PiTrac that is not answering should
#: cost one timeout rather than one each.
SNAPSHOT_SECONDS = 2.0

CONNECTED = "connected"


@dataclass(frozen=True)
class RelayTarget:
    """PiTrac's entry for the local relay, as PiTrac itself reports it."""

    sim_id: str
    on: bool
    correct: bool
    status: str
    detail: str

    @property
    def delivering(self) -> bool:
        return self.on and self.correct and self.status == CONNECTED


@dataclass(frozen=True)
class PitracSnapshot:
    """One consistent look at PiTrac: either all of it was read, or none was."""

    at: float = 0.0
    reachable: bool = False
    supported: bool = False
    detail: str = ""
    sims: List[Dict[str, Any]] = field(default_factory=list)
    setup: Dict[str, Any] = field(default_factory=dict)

    @property
    def readable(self) -> bool:
        return self.reachable and self.supported

    def uncalibrated(self) -> List[str]:
        """What still needs calibrating, in words. Empty once everything is done."""

        missing = []
        for number in (1, 2):
            camera = (self.setup.get("cameras") or {}).get("camera{}".format(number)) or {}
            if not camera.get("lens_calibrated"):
                missing.append("camera {} lens".format(number))
            if not camera.get("position_calibrated"):
                missing.append("camera {} position".format(number))
        return missing

    @property
    def calibrated(self) -> bool:
        return self.readable and not self.uncalibrated()

    @property
    def strobe(self) -> Dict[str, Any]:
        return self.setup.get("strobe") or {}

    def relay_target(self, port: int) -> Optional[RelayTarget]:
        sim = find_relay_sim(self.sims, port)
        if sim is None:
            return None
        return RelayTarget(
            sim_id=sim["id"],
            on=sim["on"],
            correct=_points_at(sim, port),
            status=str(sim.get("status", "")),
            detail=str(sim.get("detail", "")),
        )

    def direct_gspro_targets(self, port: int) -> List[str]:
        """GSPro targets that bypass the relay, which would score a shot twice."""

        return [
            str(sim.get("target") or sim.get("name") or "GSPro")
            for sim in self.sims
            if sim["type"] == RELAY_SIM_TYPE and sim["on"] and not _points_at(sim, port)
            and sim.get("name") != RELAY_SIM_NAME
        ]


def _points_at(sim: Dict[str, Any], port: int) -> bool:
    settings = sim.get("settings") or {}
    try:
        configured = int(settings.get("port") or 0)
    except (TypeError, ValueError):
        return False
    host = str(settings.get("host", "")).strip().lower()
    return host in LOOPBACK_HOSTS and configured == int(port)


def find_relay_sim(sims: List[Dict[str, Any]], port: int) -> Optional[Dict[str, Any]]:
    """Our entry: the one that points at the relay, or failing that, by name.

    By endpoint first, so a target the owner made by hand is adopted rather than
    doubled. By name second, so one whose address was edited is repaired.
    """

    ours = [sim for sim in sims if sim["type"] == RELAY_SIM_TYPE]
    pointing = [sim for sim in ours if _points_at(sim, port)]
    for group in (
        [sim for sim in pointing if sim["on"]],
        pointing,
        [sim for sim in ours if sim.get("name") == RELAY_SIM_NAME],
    ):
        if group:
            return group[0]
    return None


@dataclass(frozen=True)
class PitracStatus:
    snapshot: PitracSnapshot
    measurement_running: bool
    web_active: bool
    target: Optional[RelayTarget]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "measurementRunning": self.measurement_running,
            "webActive": self.web_active,
            "reachable": self.snapshot.reachable,
            "supported": self.snapshot.supported,
            "calibrated": self.snapshot.calibrated,
            "relayConfigured": bool(self.target and self.target.on and self.target.correct),
            "relayConnected": bool(self.target and self.target.delivering),
        }


class PitracInstallation:
    def __init__(
        self,
        api: Optional[PitracApi] = None,
        config_dir: Path = PITRAC_CONFIG_DIR,
        images_dir: Path = IMAGES_DIR,
    ):
        self.api = api if api is not None else PitracApi()
        self.config_dir = Path(config_dir)
        self.images_dir = Path(images_dir)
        self._lock = threading.Lock()
        self._snapshot = PitracSnapshot()

    # --- Reading ----------------------------------------------------------

    def snapshot(self, max_age: float = SNAPSHOT_SECONDS) -> PitracSnapshot:
        """What PiTrac says about itself, at most ``max_age`` seconds old."""

        with self._lock:
            last = self._snapshot
            if last.at and time.monotonic() - last.at < max_age:
                return last
            self._snapshot = self._look()
            return self._snapshot

    def _look(self) -> PitracSnapshot:
        try:
            sims = self.api.sims()
            setup = self.api.setup_status()
        except PitracUnreachable as exc:
            return PitracSnapshot(at=time.monotonic(), detail=str(exc))
        except PitracApiError as exc:
            return PitracSnapshot(at=time.monotonic(), reachable=True, detail=str(exc))
        return PitracSnapshot(
            at=time.monotonic(), reachable=True, supported=True, sims=sims, setup=setup
        )

    def invalidate(self) -> None:
        with self._lock:
            self._snapshot = PitracSnapshot()

    def export(self) -> Dict[str, Any]:
        """PiTrac's settings and calibration. Raises ``PitracApiError``."""

        return self.api.export_config()

    def import_(self, **sections: Dict[str, Any]) -> Dict[str, str]:
        """Replace whole sections, returning the keys PiTrac would not take."""

        skipped = self.api.import_config(sections)
        self.invalidate()
        return skipped

    def recent_images(self, limit: int = 12) -> List[Dict[str, Any]]:
        """The most recent shot images PiTrac has written, newest first.

        Only names are returned. The pictures are fetched from PiTrac's own web
        server by the app, so nothing is copied and nothing has to be kept in
        step with what PiTrac deletes.
        """

        try:
            entries = [
                entry
                for entry in self.images_dir.iterdir()
                if entry.is_file()
                and entry.suffix.lower() in IMAGE_SUFFIXES
                and SAFE_IMAGE_NAME.match(entry.name)
            ]
        except OSError:
            return []

        def when(entry):
            try:
                return entry.stat().st_mtime
            except OSError:
                return 0.0

        entries.sort(key=when, reverse=True)
        found = []
        for entry in entries[: max(0, limit)]:
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            found.append(
                {
                    "name": entry.name,
                    "at": when(entry),
                    "sizeBytes": size,
                    "url": "/api/images/{}".format(entry.name),
                }
            )
        return found

    # --- Writing ----------------------------------------------------------

    def ensure_relay_target(self, relay_ports: Dict[Simulator, int]) -> List[str]:
        """Make sure PiTrac has exactly one entry for the relay.

        Returns what was changed, in words; empty when nothing needed to be.
        Raises ``PitracApiError`` when PiTrac cannot be asked.

        An entry the owner switched off stays off. That is their decision to
        make in PiTrac's dashboard, and the self-test says plainly what it
        costs. A second entry pointing at the same relay is switched off
        rather than deleted: two would each deliver every shot.
        """

        port = int(relay_ports[Simulator.GSPRO])
        wanted = {"host": "127.0.0.1", "port": port}
        changed: List[str] = []
        try:
            sims = self.api.sims()
            ours = find_relay_sim(sims, port)
            if ours is None:
                self.api.create_sim({
                    "type": RELAY_SIM_TYPE, "name": RELAY_SIM_NAME, "on": True, "settings": wanted,
                })
                return ["Added Easy-Connect to PiTrac's simulators"]
            if not _points_at(ours, port):
                self.api.update_sim(ours["id"], {"settings": wanted})
                changed.append("Corrected Easy-Connect's address in PiTrac")
            for sim in sims:
                if sim["id"] != ours["id"] and sim["on"] and self._is_stray(sim, relay_ports):
                    self.api.update_sim(sim["id"], {"on": False})
                    changed.append("Switched off a duplicate simulator in PiTrac ({})".format(
                        sim.get("name") or sim["type"]))
            return changed
        finally:
            self.invalidate()

    @staticmethod
    def _is_stray(sim: Dict[str, Any], relay_ports: Dict[Simulator, int]) -> bool:
        """Another entry aimed at one of the relay's own ports.

        Earlier releases had PiTrac send to both a GSPro and an E6 port, and
        PiTrac turns those settings into entries of their own when it upgrades.
        """

        return any(_points_at(sim, port) for port in relay_ports.values())

    def intended_owner_ids(self):
        """The uid and gid PiTrac's own files carry, for anything we install."""

        return self._intended_owner()

    def owner_home(self) -> Optional[str]:
        """The home directory of whoever PiTrac belongs to on this machine.

        Easy Connect runs as root, so anything that looks for PiTrac's own
        files under ``~`` would look in root's home and find nothing.
        """

        owner = self._intended_owner()
        if owner is None:
            return None
        try:
            import pwd

            return pwd.getpwuid(owner[0]).pw_dir
        except Exception:
            return None

    def _intended_owner(self) -> Optional[Tuple[int, int]]:
        """Whose PiTrac this is, judged by who owns its configuration.

        Easy Connect runs as root so it can drive NetworkManager, but PiTrac
        runs as an ordinary user. Anything installed for it has to be readable
        by that user rather than by root.
        """

        if not hasattr(os, "chown"):
            return None
        for candidate in (self.config_dir, self.config_dir.parent):
            try:
                info = candidate.stat()
            except OSError:
                continue
            return info.st_uid, info.st_gid
        return None

    # --- Reporting --------------------------------------------------------

    def status(self, backend, relay_ports: Dict[Simulator, int]) -> PitracStatus:
        snapshot = self.snapshot()
        return PitracStatus(
            snapshot=snapshot,
            measurement_running=backend.process_running(PITRAC_PROCESS),
            web_active=backend.service_status(PITRAC_WEB_SERVICE).active,
            target=snapshot.relay_target(relay_ports[Simulator.GSPRO]),
        )

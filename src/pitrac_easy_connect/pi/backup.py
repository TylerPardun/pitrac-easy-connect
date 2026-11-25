"""Exporting and restoring what would be painful to recreate.

Calibration is the thing worth protecting. Wi-Fi can be re-entered in a minute
and pairing takes one click, but calibration means setting up a rig and
walking through a procedure, and it is specific to one physical pair of cameras
in one enclosure.

A backup is a single JSON file with a checksum over its contents. The checksum
catches a truncated download, a corrupted card, or a file someone has edited by
hand. It is **not** a signature — there is no key involved, so it cannot prove
who made the file. Restoring a backup from an untrusted source is therefore a
decision about trusting that source, and the interface says so.

Two details drive the design:

**Reflashing a memory card produces a new device ID.** Identity is generated on
first run, so a rebuilt card is, as far as the software can tell, a different
enclosure. That is exactly the case the backup exists for, so restoring identity
is offered as a deliberate choice: take it when the card was replaced in the same
enclosure, and the printed owner card keeps working.

**Calibration from another enclosure produces wrong shot data.** Silently
accepting it would give a plausible-looking but incorrect ball flight, which is
worse than refusing. So calibration coming from a different device ID needs an
explicit acknowledgement.

**Strobe settings belong to one circuit board.** They set how hard the strobe is
driven, and which board PiTrac believes it is driving, so values from another are
a risk to the hardware rather than just wrong numbers. They are restored only to
the Raspberry Pi they were read from, and only when its owner says the board
attached to it has not been changed. Otherwise this enclosure keeps its own, and
if it has none PiTrac asks for the strobe to be calibrated.

The enclosure's identity is no evidence of that. Restoring identity copies it, so
afterwards two machines have the same one. The Pi's serial number does not copy.
"""

import copy
import json
import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import __version__
from ..common import jsontext
from ..common.configstore import ConfigStore, atomic_write_bytes
from .pitrac_api import PitracApiError
from ..common.errors import (
    BACKUP_ROLLBACK_FAILED,
    CFG_BACKUP_INVALID,
    CFG_BACKUP_WRONG_DEVICE,
    CFG_CALIBRATION_REFUSED,
    CFG_PITRAC_NEEDED,
    CFG_SCHEMA_NEWER,
    EasyConnectError,
)

FORMAT = "pitrac-easy-connect-backup"
FORMAT_VERSION = 1
MAX_BACKUP_BYTES = 8 * 1024 * 1024

#: Sections a backup can carry. The first two are the point of the exercise; the
#: last two are secrets and are never included unless explicitly asked for.
SECTION_CALIBRATION = "calibration"
SECTION_PREFERENCES = "preferences"
SECTION_IDENTITY = "identity"
SECTION_PAIRINGS = "pairings"

SECTION_LABELS = {
    SECTION_CALIBRATION: "Camera calibration",
    SECTION_PREFERENCES: "Simulator choice, enclosure name, and PiTrac settings",
    SECTION_IDENTITY: "Enclosure identity and setup Wi-Fi password",
    SECTION_PAIRINGS: "Paired computers",
}
#: How this enclosure's own strobe board is driven. The whole section, in the
#: settings as well as the calibration: which version the board is lives in the
#: settings, and telling PiTrac it is an older one turns its safety check off.
STROBE_SECTION = "gs_config.strobing"

#: Where PiTrac has kept its simulator destinations. Wiring, not a preference:
#: a backup must never redirect where this enclosure's shots go.
SIMULATOR_SETTINGS = ("gs_config.golf_simulator_interfaces", "simulators")

SECRET_SECTIONS = {SECTION_IDENTITY, SECTION_PAIRINGS}


def _canonical(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def checksum_of(payload: Dict[str, Any]) -> str:
    return sha256(_canonical(payload)).hexdigest()


@dataclass(frozen=True)
class BackupInfo:
    """What a backup says about itself, before anything is applied."""

    device_id: str
    display_name: str
    hardware_profile: str
    created_at: float
    created_by: str
    sections: List[str]
    same_device: bool
    contains_secrets: bool
    #: Whether it was made on this very Raspberry Pi. ``None`` when either side
    #: cannot say.
    same_hardware: Optional[bool] = None
    has_strobe: bool = False

    @property
    def can_restore_strobe(self) -> bool:
        return self.has_strobe and self.same_hardware is True

    @property
    def created_text(self) -> str:
        return time.strftime("%d %B %Y at %H:%M", time.localtime(self.created_at))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "deviceId": self.device_id,
            "displayName": self.display_name,
            "hardwareProfile": self.hardware_profile,
            "createdAt": self.created_at,
            "createdText": self.created_text,
            "createdBy": self.created_by,
            "sections": list(self.sections),
            "sectionLabels": [SECTION_LABELS.get(s, s) for s in self.sections],
            "sameDevice": self.same_device,
            "containsSecrets": self.contains_secrets,
            "sameHardware": self.same_hardware,
            "canRestoreStrobe": self.can_restore_strobe,
        }


@dataclass
class RestoreResult:
    restored: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    pre_restore_backup: str = ""
    needs_restart: bool = False
    #: Whether the strobe settings came from the backup, or were kept.
    strobe_restored: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "restored": [SECTION_LABELS.get(s, s) for s in self.restored],
            "skipped": [SECTION_LABELS.get(s, s) for s in self.skipped],
            "preRestoreBackup": self.pre_restore_backup,
            "needsRestart": self.needs_restart,
            "strobeRestored": self.strobe_restored,
        }


class BackupManager:
    def __init__(
        self,
        identity_store,
        settings: ConfigStore,
        pitrac,
        pairings,
        backup_dir: Path,
        version: str = __version__,
        board_serial: Callable[[], str] = lambda: "",
    ):
        self.board_serial = board_serial
        self.identity_store = identity_store
        self.settings = settings
        self.pitrac = pitrac
        self.pairings = pairings
        self.backup_dir = Path(backup_dir)
        self.version = version

    # --- Creating ---------------------------------------------------------

    def create(
        self, include_identity: bool = False, include_pairings: bool = False
    ) -> Dict[str, Any]:
        """Build a backup document.

        Calibration and preferences are always included. The two secret sections
        are opt-in, because a file containing the setup Wi-Fi password and the
        pairing secrets has to be looked after like the owner card itself.
        """

        return self._document(self._pitrac_export(), include_identity, include_pairings)

    def _pitrac_export(self) -> Dict[str, Any]:
        """PiTrac's calibration and settings, or a refusal.

        A backup that silently left calibration out would look complete until
        the day it was needed.
        """

        try:
            return self.pitrac.export()
        except PitracApiError as exc:
            raise EasyConnectError(CFG_PITRAC_NEEDED, str(exc)) from exc

    def _document(
        self, exported: Dict[str, Any], include_identity: bool, include_pairings: bool
    ) -> Dict[str, Any]:
        identity = self.identity_store.identity

        sections: List[str] = []
        payload: Dict[str, Any] = {
            "createdAt": time.time(),
            "createdBy": self.version,
            "device": {
                "deviceId": identity.device_id,
                "displayName": identity.display_name,
                "hardwareProfile": identity.hardware_profile,
                "hardwareSerial": self.board_serial(),
            },
        }

        calibration = exported.get("calibration_data") or {}
        if calibration:
            payload[SECTION_CALIBRATION] = calibration
            sections.append(SECTION_CALIBRATION)

        payload[SECTION_PREFERENCES] = {
            "settings": self.settings.all(),
            "displayName": identity.display_name,
            "hardwareProfile": identity.hardware_profile,
            "pitracSettings": exported.get("user_settings") or {},
        }
        sections.append(SECTION_PREFERENCES)

        if include_identity:
            payload[SECTION_IDENTITY] = {
                "deviceId": identity.device_id,
                "displayName": identity.display_name,
                "setupPassword": identity.setup_password,
                "hardwareProfile": identity.hardware_profile,
            }
            sections.append(SECTION_IDENTITY)

        if include_pairings:
            payload[SECTION_PAIRINGS] = self.pairings.export()
            sections.append(SECTION_PAIRINGS)

        payload["sections"] = sections
        return {
            "format": FORMAT,
            "formatVersion": FORMAT_VERSION,
            "checksum": checksum_of(payload),
            "payload": payload,
        }

    def create_bytes(self, **kwargs: Any) -> bytes:
        return _file_bytes(self.create(**kwargs))

    def suggested_filename(self) -> str:
        identity = self.identity_store.identity
        return "pitrac-{}-{}.pitracbackup".format(
            identity.device_id.lower(), time.strftime("%Y-%m-%d")
        )

    # --- Reading one ------------------------------------------------------

    def inspect(self, data: Any) -> BackupInfo:
        """Validate a backup and describe it, without changing anything."""

        document = self._parse(data)
        payload = document["payload"]
        device = payload.get("device") or {}
        sections = [s for s in payload.get("sections", []) if s in SECTION_LABELS]
        theirs, ours = str(device.get("hardwareSerial") or ""), self.board_serial()
        return BackupInfo(
            device_id=str(device.get("deviceId", "")),
            display_name=str(device.get("displayName", "PiTrac")),
            hardware_profile=str(device.get("hardwareProfile", "")),
            created_at=float(payload.get("createdAt") or 0),
            created_by=str(payload.get("createdBy", "")),
            sections=sections,
            same_device=str(device.get("deviceId", "")) == self.identity_store.identity.device_id,
            contains_secrets=bool(set(sections) & SECRET_SECTIONS),
            same_hardware=(theirs == ours) if theirs and ours else None,
            has_strobe=bool(
                _dig(payload.get(SECTION_CALIBRATION) or {}, STROBE_SECTION)
                or _dig((payload.get(SECTION_PREFERENCES) or {}).get("pitracSettings") or {},
                        STROBE_SECTION)
            ),
        )

    def _parse(self, data: Any) -> Dict[str, Any]:
        if isinstance(data, (bytes, bytearray)):
            if len(data) > MAX_BACKUP_BYTES:
                raise EasyConnectError(CFG_BACKUP_INVALID, "that file is too large to be a backup")
            try:
                data = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise EasyConnectError(CFG_BACKUP_INVALID, "that file is not a backup") from exc
        if isinstance(data, str):
            try:
                data = jsontext.loads(data)
            except ValueError as exc:
                raise EasyConnectError(CFG_BACKUP_INVALID, "that file is not a backup") from exc
        if not isinstance(data, dict):
            raise EasyConnectError(CFG_BACKUP_INVALID, "that file is not a backup")

        if data.get("format") != FORMAT:
            raise EasyConnectError(CFG_BACKUP_INVALID, "that file is not a PiTrac backup")

        version = data.get("formatVersion")
        if not isinstance(version, int):
            raise EasyConnectError(CFG_BACKUP_INVALID, "the backup does not say what version it is")
        if version > FORMAT_VERSION:
            raise EasyConnectError(
                CFG_SCHEMA_NEWER,
                "the backup uses format {}, this build understands {}".format(
                    version, FORMAT_VERSION
                ),
            )

        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise EasyConnectError(CFG_BACKUP_INVALID, "the backup has no contents")

        # Comparing the recomputed checksum is what catches a truncated download
        # or a file edited by hand.
        if checksum_of(payload) != str(data.get("checksum", "")):
            raise EasyConnectError(
                CFG_BACKUP_INVALID, "the backup's contents do not match its checksum"
            )
        return data

    # --- Restoring --------------------------------------------------------

    def restore(
        self,
        data: Any,
        calibration: bool = True,
        preferences: bool = True,
        identity: bool = False,
        pairings: bool = False,
        confirm_different_device: bool = False,
        confirm_same_board: bool = False,
    ) -> RestoreResult:
        document = self._parse(data)
        payload = document["payload"]
        info = self.inspect(document)
        available = set(info.sections)

        wants_calibration = calibration and SECTION_CALIBRATION in available
        # Restoring identity makes this enclosure become the one in the backup,
        # so the calibration is no longer from "a different enclosure".
        becoming_same_device = identity and SECTION_IDENTITY in available
        # Unless the hardware says otherwise. Two enclosures given the same
        # identity are still two pairs of cameras.
        elsewhere = info.same_hardware is False or (
            not info.same_device and not becoming_same_device
        )
        if wants_calibration and elsewhere:
            if not confirm_different_device:
                raise EasyConnectError(
                    CFG_BACKUP_WRONG_DEVICE,
                    "the backup is from {} and this enclosure is {}".format(
                        info.display_name or info.device_id,
                        self.identity_store.identity.display_name,
                    ),
                )

        # Check everything that was asked for before changing anything. The
        # sections used to be validated as they were applied, so a backup with
        # good calibration and a bad identity rewrote calibration and settings
        # and then raised, leaving the enclosure half restored.
        self._check_sections(payload, available, identity, pairings)

        # Read before anything is changed, so that a PiTrac that cannot be
        # reached stops the restore here. Nothing that PiTrac holds is touched
        # when neither of its sections was asked for, so then it may be down.
        needs_pitrac = wants_calibration or (
            preferences and SECTION_PREFERENCES in available
        )
        exported: Dict[str, Any] = {}
        try:
            exported = self._pitrac_export()
        except EasyConnectError:
            if needs_pitrac:
                raise

        # Always take a snapshot first, so a restore can itself be undone.
        snapshot = self._snapshot(exported)
        result = RestoreResult(pre_restore_backup=snapshot)
        same_board = confirm_same_board and info.can_restore_strobe

        # What each thing being changed looked like beforehand, so a failure
        # can be undone directly. Replaying a restore from the snapshot would
        # go back through the code that just failed.
        undo = self._remember(exported, wants_calibration, preferences, identity, pairings)
        try:
            return self._apply(payload, available, result, wants_calibration,
                               calibration, preferences, identity, pairings,
                               exported, same_board)
        except Exception:
            self._put_back(undo)
            raise

    def _remember(self, exported: Dict[str, Any], calibration: bool, preferences: bool,
                  identity: bool, pairings: bool) -> Dict[str, Any]:
        state: Dict[str, Any] = {}
        if calibration:
            state["calibration"] = exported.get("calibration_data") or {}
        if preferences:
            state["settings"] = dict(self.settings.all())
            state["displayName"] = self.identity_store.identity.display_name
            # PiTrac's own settings are written by the same step. Leaving them
            # out meant a rollback put Easy-Connect's preferences back and left
            # PiTrac changed.
            state["pitracSettings"] = exported.get("user_settings") or {}
        if identity:
            state["identity"] = self.identity_store.identity.as_dict(include_secrets=True)
        if pairings:
            state["pairings"] = self.pairings.export()
        return state

    def _put_back(self, state: Dict[str, Any]) -> None:
        """Undo whatever a failed restore had already written.

        A rollback that quietly fails is worse than one that does not run: the
        machine is left in a state nobody described. Anything that could not be
        put back is collected and raised.
        """

        failures: List[str] = []

        if "calibration" in state:
            try:
                refused = self.pitrac.import_(calibration_data=state["calibration"])
                if refused:
                    failures.append("calibration: PiTrac refused {}".format(
                        ", ".join(sorted(refused))))
            except PitracApiError as exc:
                failures.append("calibration: {}".format(exc))
        if "settings" in state:
            try:
                self.settings.replace(state["settings"])
            except Exception as exc:
                failures.append("preferences: {}".format(exc))
        if "pitracSettings" in state:
            try:
                self.pitrac.import_(user_settings=state["pitracSettings"])
            except PitracApiError as exc:
                failures.append("PiTrac settings: {}".format(exc))
        if "identity" in state:
            try:
                self.identity_store.restore(state["identity"])
                # Restoring the identity forward updates this; rolling it back
                # did not, so a failed restore left the pairing manager
                # checking pairings against the identity that was abandoned.
                self.pairings.device_id = self.identity_store.identity.device_id
            except Exception as exc:
                failures.append("identity: {}".format(exc))
        if "pairings" in state:
            try:
                self.pairings.restore(state["pairings"])
            except Exception as exc:
                failures.append("paired computers: {}".format(exc))
        if failures:
            raise EasyConnectError(
                BACKUP_ROLLBACK_FAILED,
                "; ".join(failures),
            )

    def _apply(self, payload, available, result, wants_calibration,
               calibration, preferences, identity, pairings,
               exported, same_board) -> RestoreResult:
        if wants_calibration:
            self._restore_calibration(payload[SECTION_CALIBRATION], exported, same_board)
            result.strobe_restored = same_board
            result.restored.append(SECTION_CALIBRATION)
            result.needs_restart = True
        elif calibration:
            result.skipped.append(SECTION_CALIBRATION)

        if preferences and SECTION_PREFERENCES in available:
            self._restore_preferences(payload[SECTION_PREFERENCES], exported, same_board)
            result.restored.append(SECTION_PREFERENCES)
            result.needs_restart = True
        elif preferences:
            result.skipped.append(SECTION_PREFERENCES)

        if identity:
            if SECTION_IDENTITY in available:
                self.identity_store.restore(payload[SECTION_IDENTITY])
                # The pairing manager captured the device id when it was
                # built. Leaving it stale means pairings are checked against
                # an enclosure that no longer exists until the service
                # restarts.
                self.pairings.device_id = self.identity_store.identity.device_id
                result.restored.append(SECTION_IDENTITY)
                result.needs_restart = True
            else:
                result.skipped.append(SECTION_IDENTITY)

        if pairings:
            if SECTION_PAIRINGS in available:
                self.pairings.restore(payload[SECTION_PAIRINGS])
                result.restored.append(SECTION_PAIRINGS)
            else:
                result.skipped.append(SECTION_PAIRINGS)

        return result

    def _check_sections(self, payload, available, identity: bool, pairings: bool) -> None:
        """Refuse a restore that would fail partway, before it starts."""

        if identity and SECTION_IDENTITY in available:
            self.identity_store.validate(payload[SECTION_IDENTITY])
        if pairings and SECTION_PAIRINGS in available:
            self.pairings.validate(payload[SECTION_PAIRINGS])

    def _restore_calibration(
        self, wanted: Any, exported: Dict[str, Any], same_board: bool
    ) -> None:
        if not isinstance(wanted, dict):
            raise EasyConnectError(CFG_BACKUP_INVALID, "the calibration in the backup is not readable")
        restored = copy.deepcopy(wanted)
        if not same_board:
            _keep_own(restored, exported.get("calibration_data") or {}, STROBE_SECTION)
        try:
            refused = self.pitrac.import_(calibration_data=restored)
        except PitracApiError as exc:
            raise EasyConnectError(CFG_PITRAC_NEEDED, str(exc)) from exc
        if refused:
            # Part of a calibration is not a calibration.
            raise EasyConnectError(
                CFG_CALIBRATION_REFUSED,
                "; ".join("{}: {}".format(key, why) for key, why in sorted(refused.items())),
            )

    def _restore_preferences(
        self, section: Dict[str, Any], exported: Dict[str, Any], same_board: bool
    ) -> None:
        settings = section.get("settings")
        if isinstance(settings, dict):
            self.settings.replace(settings)

        name = section.get("displayName")
        if isinstance(name, str) and name.strip():
            try:
                self.identity_store.rename(name)
            except ValueError:
                pass

        pitrac_settings = section.get("pitracSettings")
        if isinstance(pitrac_settings, dict) and pitrac_settings:
            # The backup's settings win. They are what the owner asked to have
            # back. The exception is where PiTrac sends its shots, which is
            # this installation's own wiring. PiTrac now keeps that apart from
            # its settings, but still acts on the old keys if they reappear,
            # so a backup from before that change must not bring them in.
            restored = copy.deepcopy(pitrac_settings)
            for dotted in SIMULATOR_SETTINGS:
                _uproot(restored, dotted)
            if not same_board:
                _keep_own(restored, exported.get("user_settings") or {}, STROBE_SECTION)
            try:
                # Values this PiTrac no longer accepts are left out by PiTrac;
                # for a preference that is the right outcome.
                self.pitrac.import_(user_settings=restored)
            except PitracApiError as exc:
                raise EasyConnectError(CFG_PITRAC_NEEDED, str(exc)) from exc

    def _snapshot(self, exported: Dict[str, Any]) -> str:
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            path = self._snapshot_path()
            # Everything the restore can change has to be in here, or the undo
            # file it advertises cannot actually undo it. Pairings were left
            # out, so a restore that replaced the paired computers could not
            # be reversed.
            atomic_write_bytes(
                path,
                _file_bytes(self._document(exported, include_identity=True, include_pairings=True)),
                mode=0o600,
            )
            self._prune_snapshots()
            return str(path)
        except OSError:
            # A snapshot that cannot be written must not block the restore, but
            # the caller is told it did not happen.
            return ""

    def _snapshot_path(self) -> Path:
        """A name no existing snapshot has.

        The stamp only resolves to the second. Two restores inside one second
        used to land on the same name, and the atomic write pushes whatever is
        already there aside as a ``.bak`` -- a second full copy of the
        enclosure's secrets, under a name the pruning below did not count, kept
        forever. Snapshots are written once and never revised, so the answer is
        a name that is free rather than an overwrite.
        """

        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = self.backup_dir / "before-restore-{}.pitracbackup".format(stamp)
        serial = 2
        while path.exists():
            path = self.backup_dir / "before-restore-{}-{}.pitracbackup".format(stamp, serial)
            serial += 1
        return path

    def _prune_snapshots(self, keep: int = 5) -> None:
        # Deliberately wider than the snapshots themselves: a half-finished
        # write leaves a sibling holding the same secrets, and it is never
        # wanted once the write it belonged to is over.
        everything = sorted(self.backup_dir.glob("before-restore-*"))
        snapshots = [path for path in everything if path.suffix == ".pitracbackup"]
        debris = [path for path in everything if path.suffix != ".pitracbackup"]
        for stale in debris + snapshots[:-keep]:
            try:
                stale.unlink()
            except OSError:
                continue


def _file_bytes(document: Dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _dig(document: Dict[str, Any], dotted: str) -> Any:
    """Read a value at a dotted path, or None if it is not there."""

    node: Any = document
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _plant(document: Dict[str, Any], dotted: str, value: Any) -> None:
    """Write a value at a dotted path, making the parents as needed."""

    parts = dotted.split(".")
    node = document
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def _keep_own(restored: Dict[str, Any], mine: Dict[str, Any], dotted: str) -> None:
    """Put this machine's value over the backup's, or remove the backup's.

    PiTrac replaces a whole section at once, so simply leaving something out of
    what is restored would erase it here rather than keep it.
    """

    _uproot(restored, dotted)
    value = _dig(mine, dotted)
    if value is not None:
        _plant(restored, dotted, copy.deepcopy(value))


def _uproot(document: Dict[str, Any], dotted: str) -> None:
    """Remove whatever is at a dotted path, if anything is."""

    *parents, last = dotted.split(".")
    node: Any = document
    for part in parents:
        node = node.get(part) if isinstance(node, dict) else None
    if isinstance(node, dict):
        node.pop(last, None)

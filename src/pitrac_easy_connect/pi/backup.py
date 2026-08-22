"""Exporting and restoring what would be painful to recreate.

Calibration is the thing worth protecting. Wi-Fi can be re-entered in a minute
and a pairing code takes seconds, but calibration means setting up a rig and
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
"""

import json
import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List

from .. import __version__
from ..common.configstore import ConfigStore, atomic_write_bytes
from ..common.errors import (
    CFG_BACKUP_INVALID,
    CFG_BACKUP_WRONG_DEVICE,
    CFG_SCHEMA_NEWER,
    CFG_WRITE_FAILED,
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
        }


@dataclass
class RestoreResult:
    restored: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    pre_restore_backup: str = ""
    needs_restart: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "restored": [SECTION_LABELS.get(s, s) for s in self.restored],
            "skipped": [SECTION_LABELS.get(s, s) for s in self.skipped],
            "preRestoreBackup": self.pre_restore_backup,
            "needsRestart": self.needs_restart,
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
    ):
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

        identity = self.identity_store.identity
        pitrac_settings, readable = self.pitrac.read_settings()

        sections: List[str] = []
        payload: Dict[str, Any] = {
            "createdAt": time.time(),
            "createdBy": self.version,
            "device": {
                "deviceId": identity.device_id,
                "displayName": identity.display_name,
                "hardwareProfile": identity.hardware_profile,
            },
        }

        calibration = self.pitrac.read_calibration()
        if calibration:
            payload[SECTION_CALIBRATION] = calibration
            sections.append(SECTION_CALIBRATION)

        payload[SECTION_PREFERENCES] = {
            "settings": self.settings.all(),
            "displayName": identity.display_name,
            "hardwareProfile": identity.hardware_profile,
            "pitracSettings": pitrac_settings if readable else {},
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
        return (json.dumps(self.create(**kwargs), indent=2, sort_keys=True) + "\n").encode("utf-8")

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
        return BackupInfo(
            device_id=str(device.get("deviceId", "")),
            display_name=str(device.get("displayName", "PiTrac")),
            hardware_profile=str(device.get("hardwareProfile", "")),
            created_at=float(payload.get("createdAt") or 0),
            created_by=str(payload.get("createdBy", "")),
            sections=sections,
            same_device=str(device.get("deviceId", "")) == self.identity_store.identity.device_id,
            contains_secrets=bool(set(sections) & SECRET_SECTIONS),
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
                data = json.loads(data)
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
    ) -> RestoreResult:
        document = self._parse(data)
        payload = document["payload"]
        info = self.inspect(document)
        available = set(info.sections)

        wants_calibration = calibration and SECTION_CALIBRATION in available
        # Restoring identity makes this enclosure become the one in the backup,
        # so the calibration is no longer from "a different enclosure".
        becoming_same_device = identity and SECTION_IDENTITY in available
        if wants_calibration and not info.same_device and not becoming_same_device:
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

        # Always take a snapshot first, so a restore can itself be undone.
        result = RestoreResult(pre_restore_backup=self._snapshot())

        if wants_calibration:
            self._write_json(self.pitrac.calibration_path, payload[SECTION_CALIBRATION])
            result.restored.append(SECTION_CALIBRATION)
            result.needs_restart = True
        elif calibration:
            result.skipped.append(SECTION_CALIBRATION)

        if preferences and SECTION_PREFERENCES in available:
            self._restore_preferences(payload[SECTION_PREFERENCES])
            result.restored.append(SECTION_PREFERENCES)
            result.needs_restart = True
        elif preferences:
            result.skipped.append(SECTION_PREFERENCES)

        if identity:
            if SECTION_IDENTITY in available:
                self.identity_store.restore(payload[SECTION_IDENTITY])
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

    def _restore_preferences(self, section: Dict[str, Any]) -> None:
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
            # PiTrac's own settings are merged rather than replaced: the relay
            # addresses this build wrote must survive a restore from a backup
            # made when they were different.
            current, readable = self.pitrac.read_settings()
            if readable:
                merged = _deep_merge(dict(pitrac_settings), current)
                self._write_json(self.pitrac.settings_path, merged)

    def _snapshot(self) -> str:
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            path = self.backup_dir / "before-restore-{}.pitracbackup".format(
                time.strftime("%Y%m%d-%H%M%S")
            )
            # Everything the restore can change has to be in here, or the undo
            # file it advertises cannot actually undo it. Pairings were left
            # out, so a restore that replaced the paired computers could not
            # be reversed.
            atomic_write_bytes(
                path,
                self.create_bytes(include_identity=True, include_pairings=True),
                mode=0o600,
            )
            self._prune_snapshots()
            return str(path)
        except OSError:
            # A snapshot that cannot be written must not block the restore, but
            # the caller is told it did not happen.
            return ""

    def _prune_snapshots(self, keep: int = 5) -> None:
        snapshots = sorted(self.backup_dir.glob("before-restore-*.pitracbackup"))
        for stale in snapshots[:-keep]:
            try:
                stale.unlink()
            except OSError:
                continue

    def _write_json(self, path: Path, value: Dict[str, Any]) -> None:
        payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
        owner = self.pitrac._intended_owner() if hasattr(self.pitrac, "_intended_owner") else None
        try:
            atomic_write_bytes(path, payload)
        except OSError as exc:
            raise EasyConnectError(CFG_WRITE_FAILED, str(exc)) from exc
        if owner is not None and hasattr(self.pitrac, "_restore_owner"):
            saved = self.pitrac.settings_path
            try:
                self.pitrac.settings_path = path
                self.pitrac._restore_owner(owner)
            finally:
                self.pitrac.settings_path = saved


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``override`` onto ``base``, keeping nested branches from both."""

    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result

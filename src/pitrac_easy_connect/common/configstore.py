"""Configuration storage that survives having the power pulled out.

Users unplug golf simulators. They do it mid-save, mid-update, and mid-network
change. Every persistent write in Easy Connect goes through this module so that
an interrupted write leaves either the previous valid document or the new valid
document, and never a half-written file.

The technique is the ordinary one, applied consistently:

1. Write the new document to a temporary file in the same directory.
2. ``fsync`` the temporary file so its bytes are actually on the card.
3. Keep the current document as a ``.bak`` sibling.
4. ``rename`` the temporary file over the real name, which is atomic.
5. ``fsync`` the directory so the rename itself is durable.

If the main document is unreadable at load time, the ``.bak`` is used and the
caller is told, so the interface can show ``PT-PI-009`` instead of silently
resetting a user's settings.
"""

import errno
import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .errors import (
    CFG_SCHEMA_NEWER,
    CFG_WRITE_FAILED,
    PI_CONFIG_CORRUPT,
    EasyConnectError,
)

Migration = Callable[[Dict[str, Any]], Dict[str, Any]]


def atomic_write_bytes(path: Path, payload: bytes, mode: int = 0o644) -> None:
    """Durably replace ``path`` with ``payload``, keeping a ``.bak`` behind."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        # os.write is allowed to write fewer bytes than it was given. A short
        # write here would leave a truncated settings file that still passed
        # every later check, so it loops until the payload is actually down.
        written = 0
        while written < len(payload):
            wrote = os.write(descriptor, payload[written:])
            if wrote <= 0:
                raise OSError("the file could not be written in full")
            written += wrote
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    # Permissions are set explicitly because os.open honours the process umask.
    os.chmod(temporary, mode)

    if path.exists():
        backup = path.with_name(path.name + ".bak")
        try:
            os.replace(path, backup)
        except OSError:
            # A missing backup is survivable; refusing to save is not.
            pass

    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


class ConfigStore:
    """One versioned JSON document with atomic saves and migrations.

    ``schema_version`` is the version this build understands. Documents written
    by an older build are migrated on load. Documents written by a newer build
    are refused rather than silently downgraded, because a downgrade would throw
    away settings the user made on the newer version.
    """

    def __init__(
        self,
        path: Path,
        defaults: Dict[str, Any],
        schema_version: int = 1,
        migrations: Optional[Dict[int, Migration]] = None,
        secret: bool = False,
    ):
        self.path = Path(path)
        self.defaults = defaults
        self.schema_version = schema_version
        self.migrations = migrations or {}
        self.mode = 0o600 if secret else 0o644
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self.recovered_from_backup = False
        self.load()

    # Reading ---------------------------------------------------------------

    def load(self) -> Dict[str, Any]:
        with self._lock:
            document, self.recovered_from_backup = self._read_document()
            if document is None:
                self._data = dict(self.defaults)
                return dict(self._data)

            version = document.get("schemaVersion", 1)
            if not isinstance(version, int):
                version = 1
            if version > self.schema_version:
                raise EasyConnectError(
                    CFG_SCHEMA_NEWER,
                    "{} was written by schema version {}, this build understands {}".format(
                        self.path.name, version, self.schema_version
                    ),
                )

            values = document.get("data")
            if not isinstance(values, dict):
                self._data = dict(self.defaults)
                self.recovered_from_backup = True
                return dict(self._data)

            while version < self.schema_version:
                migrate = self.migrations.get(version)
                values = migrate(values) if migrate else values
                version += 1

            merged = dict(self.defaults)
            merged.update(values)
            self._data = merged
            return dict(self._data)

    def _read_document(self):
        for candidate, from_backup in (
            (self.path, False),
            (self.path.with_name(self.path.name + ".bak"), True),
        ):
            try:
                raw = candidate.read_text(encoding="utf-8")
            except (FileNotFoundError, NotADirectoryError):
                continue
            except OSError:
                continue
            try:
                document = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                continue
            if isinstance(document, dict):
                return document, from_backup
        return None, False

    def get(self, key: str, fallback: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, fallback)

    def all(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    # Writing ---------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        self.update({key: value})

    def update(self, values: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            candidate = dict(self._data)
            candidate.update(values)
            self._write(candidate)
            self._data = candidate
            return dict(self._data)

    def replace(self, values: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            candidate = dict(self.defaults)
            candidate.update(values)
            self._write(candidate)
            self._data = candidate
            return dict(self._data)

    def _write(self, values: Dict[str, Any]) -> None:
        document = {"schemaVersion": self.schema_version, "data": values}
        payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
        try:
            atomic_write_bytes(self.path, payload, self.mode)
        except OSError as exc:
            detail = "could not write {}".format(self.path)
            if exc.errno == errno.ENOSPC:
                detail = "the memory card is full"
            raise EasyConnectError(CFG_WRITE_FAILED, detail) from exc

    # Diagnostics -----------------------------------------------------------

    def corruption_error(self) -> Optional[EasyConnectError]:
        """The error to surface if this document had to fall back to its backup."""

        if not self.recovered_from_backup:
            return None
        return EasyConnectError(
            PI_CONFIG_CORRUPT, "{} was restored from its backup copy".format(self.path.name)
        )

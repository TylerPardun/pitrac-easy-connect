"""Letting the enclosure hand out the software its owner's PC needs.

A new owner has a box, a Wi-Fi password on a card, and a Windows PC. Asking them
to find a download on the internet is one more thing to get wrong, and it fails
entirely in a garage with no internet — which is exactly where Direct Mode is
meant to work.

So the enclosure carries an offline cache of the exact desktop builds, dropped
into the downloads directory by an operator before handover (see
docs/distribution.md). This module only lists and serves what is already
there and matches one of the three real desktop assets; nothing here writes.

What is deliberately never offered here, no matter what sits in the
directory: the Pi-service `.pyz`, which is this project's own enclosure
update payload and has never been a desktop application, and
`PiTrac-Easy-Connect-windows.zip`, which is the installed desktop app's own
internal self-update payload rather than what a first-time Windows owner
should run. Offering either under "download the PC software" is exactly the
"Any computer with Python" and "For Linux" companion-download confusion this
module used to invite by matching on file suffix rather than exact identity.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common import release_manifest

@dataclass(frozen=True)
class AssetInfo:
    label: str
    note: str


#: The exact filenames a real release publishes as a desktop download --
#: see common/updates.py PLATFORM_ASSET_NAMES and docs/distribution.md.
#: Matched by exact name, not by suffix: a suffix match is how a `.pyz` or
#: an unrelated `.zip` ends up offered as if it were one of these.
SUPPORTED_DESKTOP_ASSETS: Dict[str, AssetInfo] = {
    "PiTrac-Easy-Connect-macos-apple-silicon.zip": AssetInfo(
        "macOS (Apple silicon)", "Unzip it and drag it to Applications.",
    ),
    "PiTrac-Easy-Connect-macos-intel.zip": AssetInfo(
        "macOS (Intel)", "Unzip it and drag it to Applications.",
    ),
    "PiTrac-Easy-Connect-windows-setup.exe": AssetInfo(
        "Windows", "The usual choice. Download it and run it.",
    ),
}

#: A deliberately narrow name for the manifest pair, matched exactly the same
#: way as a desktop asset -- these two are read, never offered for download.
_MANIFEST_NAME = release_manifest.MANIFEST_ASSET
_SIGNATURE_NAME = release_manifest.SIGNATURE_ASSET

#: A deliberately narrow name. Anything with a path separator, a leading dot, or
#: anything exotic is refused before it is ever joined to a directory.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

MAX_FILE_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class Download:
    name: str
    size_bytes: int
    label: str
    note: str

    @property
    def size_text(self) -> str:
        megabytes = self.size_bytes / 1024 / 1024
        if megabytes >= 1:
            return "{:.1f} MB".format(megabytes)
        return "{:.0f} KB".format(self.size_bytes / 1024)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "note": self.note,
            "sizeText": self.size_text,
            "url": "/companion/" + self.name,
        }


def _verified_manifest(directory: Path):
    """This directory's own signed manifest, if it has one and it checks out.

    An operator who copies a whole release into the downloads directory gets
    every stored file checked against what that release actually published,
    the same way the desktop and Pi updaters check a download. An operator
    who copies only the three assets, with no manifest, is not refused for
    it -- that would break every enclosure set up before this existed -- but
    gets none of this extra verification; SECURITY.md already documents
    physical card access as outside what this project defends against.
    """

    manifest_path = directory / _MANIFEST_NAME
    signature_path = directory / _SIGNATURE_NAME
    if not manifest_path.is_file() or not signature_path.is_file():
        return None
    try:
        manifest_bytes = manifest_path.read_bytes()
        signature_text = signature_path.read_bytes()
    except OSError:
        return None
    try:
        return release_manifest.verify_manifest(manifest_bytes, signature_text)
    except release_manifest.ManifestError:
        return None


def _matches_manifest(manifest, name: str, size_bytes: int, path: Path) -> bool:
    try:
        expected_size = release_manifest.expected_size(manifest, name)
        expected_digest = release_manifest.expected_digest(manifest, name)
    except release_manifest.ManifestError:
        # This release's manifest does not describe this filename at all.
        return False
    if size_bytes != expected_size:
        return False
    import hashlib

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_digest


class CompanionDownloads:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def available(self) -> List[Download]:
        try:
            entries = list(self.directory.iterdir())
        except OSError:
            return []

        manifest = _verified_manifest(self.directory)

        found = []
        for entry in entries:
            info = SUPPORTED_DESKTOP_ASSETS.get(entry.name)
            if info is None or entry.is_symlink() or not entry.is_file():
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            if manifest is not None and not _matches_manifest(manifest, entry.name, size, entry):
                continue
            found.append(Download(entry.name, size, info.label, info.note))

        # Windows first, because that is what the simulator PC runs.
        order = {"PiTrac-Easy-Connect-windows-setup.exe": 0}
        return sorted(found, key=lambda item: (order.get(item.name, 1), item.name))

    def resolve(self, name: str) -> Optional[Path]:
        """Return the path for a requested download, or ``None`` if it is not one.

        Only an exact, currently-supported desktop asset name can resolve.
        The name is validated before being joined to a directory, and the
        result is confirmed to still be directly inside the downloads
        directory and not a symlink, so a crafted or planted name cannot
        reach anything else on the card.
        """

        if not SAFE_NAME.match(str(name or "")) or name not in SUPPORTED_DESKTOP_ASSETS:
            return None
        candidate = self.directory / name
        if candidate.is_symlink():
            return None
        try:
            resolved = candidate.resolve()
            root = self.directory.resolve()
        except OSError:
            return None
        if resolved.parent != root or resolved.name != name:
            return None
        if not resolved.is_file():
            return None
        try:
            size = resolved.stat().st_size
        except OSError:
            return None
        if size > MAX_FILE_BYTES:
            return None
        manifest = _verified_manifest(self.directory)
        if manifest is not None and not _matches_manifest(manifest, name, size, resolved):
            return None
        return resolved

"""Letting the enclosure hand out the software its owner's PC needs.

A new owner has a box, a Wi-Fi password on a card, and a Windows PC. Asking them
to find a download on the internet is one more thing to get wrong, and it fails
entirely in a garage with no internet — which is exactly where Direct Mode is
meant to work.

So the enclosure carries the Companion. The PC joins the enclosure's own setup
signal to configure Wi-Fi anyway; while it is there, it can fetch the PC software
from the same page. That also guarantees the two halves are the same version,
because they shipped together.

Files are dropped into the downloads directory by the installer or by hand. This
module only lists and serves what is already there; nothing here writes.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Only these are offered. An arbitrary file dropped in the directory by mistake
#: is not something to hand to someone's PC.
ALLOWED_SUFFIXES = {".exe", ".msi", ".pyz", ".zip"}

#: A deliberately narrow name. Anything with a path separator, a leading dot, or
#: anything exotic is refused before it is ever joined to a directory.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

MAX_FILE_BYTES = 200 * 1024 * 1024

def _looks_like_the_mac_app(name: str) -> bool:
    """A .zip from a release is the macOS app; a .zip of source is not.

    Labelling every zip "Source" sent Mac owners straight past the only build
    that suits them.
    """

    lowered = name.lower()
    return lowered.endswith(".zip") and "mac" in lowered


DESCRIPTIONS = {
    ".exe": ("Windows", "The usual choice. Download it and run it."),
    ".msi": ("Windows installer", "Download it and run it."),
    ".pyz": (
        "Any computer with Python",
        "One file, no installation. Needs Python 3.9 or newer already installed.",
    ),
    # A .zip from a release is the macOS application, not source. Labelling
    # every zip "Source" sent Mac owners past the only build that suits them.
    ".zip": ("Source", "For Linux, or building it yourself."),
}


@dataclass(frozen=True)
class Download:
    name: str
    size_bytes: int
    suffix: str

    @property
    def label(self) -> str:
        if _looks_like_the_mac_app(self.name):
            return "macOS"
        return DESCRIPTIONS.get(self.suffix, ("File", ""))[0]

    @property
    def note(self) -> str:
        if _looks_like_the_mac_app(self.name):
            return "Unzip it and drag it to Applications."
        return DESCRIPTIONS.get(self.suffix, ("File", ""))[1]

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


class CompanionDownloads:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def available(self) -> List[Download]:
        try:
            entries = list(self.directory.iterdir())
        except OSError:
            return []

        found = []
        for entry in entries:
            if not entry.is_file() or entry.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            if not SAFE_NAME.match(entry.name):
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            found.append(Download(entry.name, size, entry.suffix.lower()))

        # Windows first, because that is what the simulator PC runs.
        order = {".exe": 0, ".msi": 1, ".pyz": 2, ".zip": 3}
        return sorted(found, key=lambda item: (order.get(item.suffix, 9), item.name))

    def resolve(self, name: str) -> Optional[Path]:
        """Return the path for a requested download, or ``None`` if it is not one.

        The name is validated against a pattern before being joined, and the
        result is confirmed to still be directly inside the downloads directory,
        so a crafted name cannot reach anything else on the card.
        """

        if not SAFE_NAME.match(str(name or "")):
            return None
        candidate = self.directory / name
        try:
            resolved = candidate.resolve()
            root = self.directory.resolve()
        except OSError:
            return None
        if resolved.parent != root:
            return None
        if resolved.suffix.lower() not in ALLOWED_SUFFIXES:
            return None
        if not resolved.is_file():
            return None
        try:
            if resolved.stat().st_size > MAX_FILE_BYTES:
                return None
        except OSError:
            return None
        return resolved

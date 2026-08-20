"""Comparing version numbers correctly.

Kept apart from the update machinery because getting this wrong is the classic
way an updater misbehaves: string comparison says "0.10.0" is older than
"0.9.0", and a user who upgrades gets told to upgrade again forever.
"""

import re
from typing import Optional, Tuple

#: A label has to begin and end with an alphanumeric, so a trailing separator
#: such as "1.2.3.4.5-" is rejected rather than half-understood.
_VERSION = re.compile(
    r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?"
    r"(?:[-+.](?P<label>[0-9A-Za-z](?:[0-9A-Za-z.\-]*[0-9A-Za-z])?))?\s*$"
)


def parse(text: str) -> Optional[Tuple[int, int, int, str]]:
    """Turn ``v1.2.3-beta.1`` into ``(1, 2, 3, "beta.1")``. ``None`` if unusable."""

    match = _VERSION.match(str(text or ""))
    if match is None:
        return None
    major, minor, patch = match.group(1), match.group(2), match.group(3)
    return (int(major), int(minor or 0), int(patch or 0), match.group("label") or "")


def _key(parsed: Tuple[int, int, int, str]):
    major, minor, patch, label = parsed
    # A release outranks any pre-release of the same numbers: 1.0.0 beats
    # 1.0.0-rc1. Within pre-releases, compare the labels.
    return (major, minor, patch, 1 if not label else 0, label)


def compare(left: str, right: str) -> Optional[int]:
    """-1, 0 or 1 as ``left`` is older, equal, or newer. ``None`` if either is unusable."""

    first, second = parse(left), parse(right)
    if first is None or second is None:
        return None
    if _key(first) == _key(second):
        return 0
    return -1 if _key(first) < _key(second) else 1


def is_newer(candidate: str, than: str) -> bool:
    """Whether ``candidate`` is a version worth offering over ``than``.

    An unparseable candidate is never newer. Refusing to guess is the safe
    answer: offering a bogus update is worse than missing a real one.
    """

    result = compare(candidate, than)
    return result == 1

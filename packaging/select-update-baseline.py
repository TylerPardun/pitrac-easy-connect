#!/usr/bin/env python3
"""Select the best published release below an update target.

Stable releases are preferred because they represent the normal updater path.
If a repository has deliberately reset its release history and only a
prerelease remains, that prerelease becomes the baseline for the next version.
Drafts and versions at or above the target are never eligible.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path

from packaging.version import InvalidVersion, Version


NO_BASELINE = 3


def _flatten_pages(value: object) -> Iterable[dict[str, object]]:
    """Accept either one GitHub API page or ``gh api --slurp`` output."""

    if not isinstance(value, list):
        raise ValueError("GitHub releases response is not a JSON array")
    for item in value:
        if isinstance(item, list):
            yield from _flatten_pages(item)
        elif isinstance(item, dict):
            yield item
        else:
            raise ValueError("GitHub releases response contains a non-object entry")


def select_update_baseline(releases: object, target_text: str) -> str | None:
    """Return a lower release tag, preferring the newest stable release."""

    target = Version(target_text)
    stable: list[tuple[Version, str]] = []
    prerelease: list[tuple[Version, str]] = []

    for release in _flatten_pages(releases):
        if release.get("draft"):
            continue
        tag = str(release.get("tag_name") or "")
        try:
            version = Version(tag.removeprefix("v"))
        except InvalidVersion:
            continue
        if version >= target:
            continue
        bucket = prerelease if release.get("prerelease") else stable
        bucket.append((version, tag))

    candidates = stable or prerelease
    return max(candidates)[1] if candidates else None


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} RELEASES_JSON TARGET_VERSION", file=sys.stderr)
        return 2
    try:
        releases = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        selected = select_update_baseline(releases, argv[2])
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"cannot select updater baseline: {error}", file=sys.stderr)
        return 2
    if selected is None:
        print(f"no published release exists below {argv[2]}", file=sys.stderr)
        return NO_BASELINE
    print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

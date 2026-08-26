#!/usr/bin/env python3
"""Describe platform signing and refuse a final release with missing reports.

A platform that reports nothing is not silently treated as signed: a missing
status file is a build that has not been updated to write one, and that is
published as a pre-release because this script cannot vouch for what shipped.
An explicit unsigned status is different: it proves the platform build ran and
reported its state honestly. Code signing is optional for this project, so a
complete unsigned build may be final while its operating-system warning stays
prominent in the release notes.
"""

import argparse
import json
from pathlib import Path

# Duplicated rather than imported: packaging/write-signing-status.py has a
# hyphen in its filename, which a plain `import` statement cannot load.
PLATFORMS = ("macos-apple-silicon", "macos-intel", "windows")


def gather(status_dir: Path) -> dict:
    found = {}
    for path in sorted(status_dir.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        platform = value.get("platform")
        if platform in PLATFORMS:
            found[platform] = value
    return found


def decide(statuses: dict) -> dict:
    missing = [name for name in PLATFORMS if name not in statuses]
    unsigned = [
        name for name, value in statuses.items() if not value.get("signed")
    ]
    unnotarized_macos = [
        name for name, value in statuses.items()
        if name.startswith("macos") and value.get("signed") and not value.get("notarized")
    ]
    complete = not missing
    fully_signed = complete and not unsigned and not unnotarized_macos

    lines = []
    if fully_signed:
        lines.append(
            "Every platform in this release is signed with a Developer ID "
            "Application certificate or Authenticode certificate, and the "
            "macOS builds are notarized and stapled."
        )
    elif missing:
        lines.append(
            "This release is missing required platform status reports, so it "
            "is published as a pre-release:"
        )
        for name in missing:
            lines.append("- {}: no signing status was reported at all.".format(name))
    else:
        lines.append(
            "This release is complete but not fully platform code-signed. It "
            "is published as a stable release; the documented first-launch "
            "operating-system warnings still apply:"
        )
        for name in unsigned:
            lines.append("- {}: {}".format(name, statuses[name].get("detail") or "not signed."))
        for name in unnotarized_macos:
            lines.append(
                "- {}: signed but not notarized: {}".format(
                    name, statuses[name].get("detail") or ""
                )
            )
    return {
        "fullySigned": fully_signed,
        "prerelease": not complete,
        "statuses": statuses,
        "notes": "\n".join(lines),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args(argv)

    result = decide(gather(arguments.status_dir))
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(result["notes"])
    print("fullySigned={}".format(str(result["fullySigned"]).lower()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

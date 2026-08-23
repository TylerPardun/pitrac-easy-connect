#!/usr/bin/env python3
"""Fail if the desktop application regains an external-browser path."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "src" / "pitrac_easy_connect" / "companion", ROOT / "packaging" / "app_entry.py"]
FORBIDDEN = {
    r"\bwebbrowser\b": "Python browser launcher",
    r"\bopen_in_browser\b": "legacy browser launcher",
    r"window\.open\s*\(": "JavaScript new-window launcher",
    r"target\s*=\s*[\"']_blank[\"']": "external/new-window link",
    r"--(?:no-browser|window)\b": "obsolete desktop option",
}


def main() -> int:
    failures = []
    files = []
    for target in TARGETS:
        files.extend(target.rglob("*.py") if target.is_dir() else [target])
    for path in files:
        text = path.read_text(encoding="utf-8")
        for pattern, label in FORBIDDEN.items():
            if re.search(pattern, text, re.I):
                failures.append("{}: {}".format(path.relative_to(ROOT), label))
    if failures:
        print("Desktop native-only check failed:")
        for failure in failures:
            print("  " + failure)
        return 1
    print("Desktop native-only check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

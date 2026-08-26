#!/usr/bin/env python3
"""Fail if the desktop application regains an external-browser path.

This checks low-level operating-system launchers as well as browser libraries.
The only file-manager commands allowed are the exact local-file selection
forms used by CompanionService.reveal_downloaded_update.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "src" / "pitrac_easy_connect", ROOT / "packaging" / "app_entry.py"]
FORBIDDEN = {
    r"\bwebbrowser\b": "Python browser launcher",
    r"\bopen_in_browser\b": "legacy browser launcher",
    r"window\.open\s*\(": "JavaScript new-window launcher",
    r"target\s*=\s*[\"']_blank[\"']": "external/new-window link",
    r"--(?:no-browser|window)\b": "obsolete desktop option",
    r"/usr/bin/open\b": "macOS operating-system opener",
    r"\bxdg-open\b": "Linux operating-system opener",
    r"\bos\.startfile\s*\(": "Windows operating-system opener",
    r"\bShellExecute(?:A|W)?\b": "Windows shell URL opener",
    r"[\"']cmd[\"']\s*,\s*[\"']/c[\"']\s*,\s*[\"']start[\"']": "Windows cmd URL opener",
    r"\bStart-Process\b": "PowerShell process/URL opener",
    r"[\"']explorer\.exe[\"']": "Windows Explorer opener",
}

# These select one backend-owned local file. Remove only these exact source
# forms before applying the broad opener rules above; a changed invocation is
# rejected until it is deliberately reviewed here.
SAFE_LOCAL_REVEALS = (
    '["/usr/bin/open", "-R", str(resolved)]',
    '["explorer.exe", "/select,{}".format(resolved)]',
)


def scan(paths):
    failures = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for safe in SAFE_LOCAL_REVEALS:
            text = text.replace(safe, "")
        for pattern, label in FORBIDDEN.items():
            if re.search(pattern, text, re.I):
                try:
                    shown = path.relative_to(ROOT)
                except ValueError:
                    shown = path
                failures.append("{}: {}".format(shown, label))
    return failures


def main() -> int:
    files = []
    for target in TARGETS:
        files.extend(target.rglob("*.py") if target.is_dir() else [target])
    failures = scan(files)
    if failures:
        print("Desktop native-only check failed:")
        for failure in failures:
            print("  " + failure)
        return 1
    print("Desktop native-only check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

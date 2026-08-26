"""Locate a real OpenSSL command on release-development machines.

macOS exposes ``/usr/bin/openssl`` but it is LibreSSL and cannot generate or
sign Ed25519 payloads with the commands used by the release tooling. CI and
Windows installations also put OpenSSL in different places. Release scripts
use this small locator instead of silently selecting an incompatible binary.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def candidates(explicit=None):
    values = []
    if explicit:
        values.append(explicit)
    if os.environ.get("OPENSSL"):
        values.append(os.environ["OPENSSL"])
    if sys.platform == "darwin":
        values.extend((
            "/opt/homebrew/opt/openssl@3/bin/openssl",
            "/opt/homebrew/bin/openssl",
            "/usr/local/opt/openssl@3/bin/openssl",
        ))
    elif sys.platform == "win32":
        values.extend((
            r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
            r"C:\Program Files\Git\mingw64\bin\openssl.exe",
            r"C:\Program Files\Git\usr\bin\openssl.exe",
        ))
    found = shutil.which("openssl")
    if found:
        values.append(found)

    seen = set()
    for value in values:
        path = str(value)
        if path in seen or not Path(path).is_file():
            continue
        seen.add(path)
        yield path


def command(explicit=None):
    """Return OpenSSL (not LibreSSL), or fail with an actionable message."""

    inspected = []
    for candidate in candidates(explicit):
        result = subprocess.run(
            [candidate, "version"], capture_output=True, text=True
        )
        detail = (result.stdout or result.stderr or "").strip()
        inspected.append("{} ({})".format(candidate, detail or "did not answer"))
        if result.returncode == 0 and detail.startswith("OpenSSL "):
            return candidate
    raise SystemExit(
        "OpenSSL 1.1.1 or newer is required for Ed25519 release signing; "
        "checked {}. Install OpenSSL 3 or pass --openssl.".format(
            ", ".join(inspected) if inspected else "no executable"
        )
    )

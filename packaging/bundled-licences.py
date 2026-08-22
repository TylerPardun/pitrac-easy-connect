#!/usr/bin/env python3
"""Report what a packaged build actually redistributes.

NOTICE.md lists other people's code that ships inside the macOS and Windows
apps. That list is an attribution obligation, not a description, so it has to
match what the build really contains rather than what anyone remembers adding.

This reads PyInstaller's own manifest from the last build and prints the
third-party packages in it.

    python3 packaging/bundled-licences.py
    python3 packaging/bundled-licences.py --check   # exit 1 if NOTICE is short

Run a build first: the manifest does not exist until PyInstaller has run.
"""

import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOC = ROOT / "build" / "PiTrac-Easy-Connect" / "Analysis-00.toc"
NOTICE = ROOT / "NOTICE.md"

#: Bundled names that belong to CPython itself or to us, and so are covered by
#: the interpreter's own entry rather than needing one each.
OURS = {"pitrac_easy_connect", "python3", "libpython3", "base_library"}

#: How a bundled name maps onto the thing NOTICE has to credit.
CREDITED_AS = {
    "objc": "pyobjc", "AppKit": "pyobjc", "Foundation": "pyobjc",
    "CoreFoundation": "pyobjc", "WebKit": "pyobjc", "PyObjCTools": "pyobjc",
    "UniformTypeIdentifiers": "pyobjc", "Quartz": "pyobjc", "Security": "pyobjc",
    "clr_loader": "pythonnet", "clr": "pythonnet", "System": "pythonnet",
    "libssl": "OpenSSL", "libcrypto": "OpenSSL",
    "libz": "zlib", "libbz2": "bzip2", "liblzma": "xz",
    "libexpat": "libexpat", "libffi": "libffi",
    "typing_extensions": "typing-extensions",
    "proxy_tools": "proxy-tools",
}


#: sys.stdlib_module_names arrived in 3.10, and this project supports 3.9.
def _standard_library_names():
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    import os
    import sysconfig

    found = set(sys.builtin_module_names)
    stdlib = sysconfig.get_paths().get("stdlib")
    if stdlib and os.path.isdir(stdlib):
        for entry in os.listdir(stdlib):
            if entry.endswith(".py"):
                found.add(entry[:-3])
            elif "." not in entry:
                found.add(entry)
    return found


_STDLIB = _standard_library_names()


def bundled():
    text = TOC.read_text()
    found = collections.Counter()
    for name, _source, kind in re.findall(
        r"\('([^']+)',\s*'([^']*)',\s*'(PYMODULE|EXTENSION|BINARY)'\)", text
    ):
        root = name.split(".")[0].split("/")[0]
        if root in OURS or root.startswith("_"):
            continue
        if root in _STDLIB:
            continue
        found[CREDITED_AS.get(root, root)] += 1
    return found


def main() -> int:
    if not TOC.exists():
        print("No build manifest at {}.".format(TOC.relative_to(ROOT)))
        print("Run ./packaging/build-app.sh first.")
        # --check used to pass here, so a build with nothing to verify
        # reported success. A check that cannot check has failed.
        return 1

    found = bundled()
    notice = NOTICE.read_text().lower()
    missing = [name for name in found if name.lower() not in notice]

    print("Third-party code inside the last build:\n")
    for name, count in sorted(found.items()):
        mark = " <- NOT IN NOTICE.md" if name in missing else ""
        print("  {:<24} {:>4} files{}".format(name, count, mark))

    if "--check" in sys.argv:
        if missing:
            print("\nNOTICE.md does not credit: {}".format(", ".join(sorted(missing))))
            print("Every bundled package is an attribution obligation. Add them.")
            return 1
        print("\nNOTICE.md credits everything in the build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

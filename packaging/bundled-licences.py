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

#: Windows names the interpreter's own entry already covers: python313.dll is
#: CPython itself, under a name macOS never produces.
INTERPRETER = re.compile(r"^(lib)?python\d+$", re.I)

#: The Microsoft C runtime PyInstaller places beside a Windows build. These are
#: dozens of separate files -- ucrtbase, VCRUNTIME140, and the api-ms-win-*
#: stubs -- but one redistributable with one set of terms, so they are credited
#: once rather than listed individually. They are still credited: they ship
#: inside the download like everything else here.
MICROSOFT_RUNTIME = re.compile(r"^(api-ms-win-|ucrtbase|vcruntime\d)", re.I)

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


#: Binaries that belong to somebody other than the package shipping them.
#: pywebview's wheel carries Microsoft's WebView2 loader and interop
#: assemblies; reducing them to their directory would credit Microsoft's code
#: to pywebview, so the file's own name is consulted first.
VENDORED = {
    "WebView2Loader": "WebView2",
    "WebBrowserInterop": "WebView2",
    "Microsoft": "WebView2",
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
        root = _root_of(name)
        if root in OURS or root.startswith("_"):
            continue
        if root in _STDLIB:
            continue
        found[_credited_as(root, name)] += 1
    return found


def _root_of(name):
    """The package a bundled file belongs to.

    Windows manifests separate with backslashes, so splitting on "/" alone
    left whole paths as their own package -- every WebView2 shim looked like
    an uncredited component of its own, and none of the mappings below could
    match.
    """

    return _segments(name)[0].split(".")[0]


def _segments(name):
    return name.replace("\\", "/").split("/")


def _leaf_of(name):
    return _segments(name)[-1].split(".")[0] if name else ""


def _credited_as(root, name=""):
    leaf = _leaf_of(name)
    if leaf in VENDORED:
        return VENDORED[leaf]
    if root in CREDITED_AS:
        return CREDITED_AS[root]
    if INTERPRETER.match(root):
        return "CPython"
    if MICROSOFT_RUNTIME.match(root):
        return "Microsoft C runtime"
    # Shared libraries carry their ABI version in the name, and where it sits
    # differs by platform: libssl.3.dylib loses it to the split above, while
    # libssl-3.dll keeps it and misses every mapping.
    trimmed = re.sub(r"-\d+$", "", root)
    return CREDITED_AS.get(trimmed, trimmed)


def credited():
    """What the notice actually credits: its table rows, not its prose.

    Searching the whole document let a package pass because its name happened
    to appear in a sentence -- "packaging" was credited by the mention of
    packaging/bundled-licences.py, and nothing else.
    """

    rows = [
        line for line in NOTICE.read_text().splitlines()
        if line.lstrip().startswith("|")
    ]
    return "\n".join(rows).lower()


def main() -> int:
    if not TOC.exists():
        print("No build manifest at {}.".format(TOC.relative_to(ROOT)))
        print("Run ./packaging/build-app.sh first.")
        # --check used to pass here, so a build with nothing to verify
        # reported success. A check that cannot check has failed.
        return 1

    found = bundled()
    notice = credited()
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

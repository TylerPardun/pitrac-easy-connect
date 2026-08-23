#!/usr/bin/env python3
"""Collect the full licence text of everything the native build bundles.

NOTICE.md names the third-party components; this produces the texts themselves,
which is what the licences actually require to be distributed. Run as part of
the build, and the build fails if a component's text cannot be found -- a
missing licence is a compliance problem, not a warning.

    python3 packaging/collect-licences.py            # write the bundle
    python3 packaging/collect-licences.py --check    # fail if it is stale
"""

import argparse
import sys
from email.utils import getaddresses
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "THIRD-PARTY-LICENCES.txt"

#: Everything the build bundles, and where its licence lives in site-packages.
#: Names are the import names PyInstaller records, mapped to distributions.
BUNDLED = {
    "pywebview": ["webview"],
    "pyobjc-core": ["objc"],
    "pyobjc-framework-Cocoa": ["AppKit", "Foundation", "CoreFoundation"],
    "pyobjc-framework-WebKit": ["WebKit"],
    "pyobjc-framework-Quartz": ["Quartz"],
    "proxy_tools": ["proxy_tools"],
    "typing_extensions": ["typing_extensions"],
    "psutil": ["psutil"],
    "PyGObject": ["gi"],
    "pycairo": ["cairo"],
    "pythonnet": ["clr"],
    "clr_loader": ["clr_loader"],
    # Pulled in beneath pythonnet on Windows, and bundled with it.
    "cffi": ["cffi", "_cffi_backend"],
    "pycparser": ["pycparser"],
    "setuptools": ["setuptools", "pkg_resources"],
    "packaging": ["packaging"],
}

LICENCE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "LICENCE.txt",
                 "COPYING", "COPYING.txt", "LICENSE.rst")


def installed_distributions():
    try:
        from importlib import metadata
    except ImportError:                                   # pragma: no cover
        import importlib_metadata as metadata             # type: ignore
    found = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            found[name.lower().replace("_", "-")] = dist
    return found


def licence_text(dist):
    """The licence text, from the distribution's own files.

    Modern wheels put it in ``<name>.dist-info/licenses/``; older ones put it
    at the top of the package. Some carry only a short identifier in metadata,
    which is not a licence text and is reported as missing rather than passed
    off as one.
    """

    candidates = []
    for file in dist.files or []:
        path = Path(str(file))
        if path.name not in LICENCE_NAMES:
            continue
        # Prefer the packaged licence, and never a build artefact that merely
        # happens to be called "copying".
        if ".dSYM" in str(path) or path.suffix in (".so", ".plist", ".yml"):
            continue
        depth = 0 if ".dist-info" in str(path) else 1
        candidates.append((depth, str(file)))

    for _depth, name in sorted(candidates):
        text = None
        try:
            # read_text only reaches files at the dist-info root, so anything
            # under licenses/ has to be read from disk.
            text = dist.read_text(name)
        except Exception:
            text = None
        if not text:
            try:
                located = dist.locate_file(name)
                if located and Path(str(located)).exists():
                    text = Path(str(located)).read_text(errors="replace")
            except Exception:
                text = None
        if text and len(text.strip()) > 120:
            return text

    # A full licence sometimes appears in the metadata field itself. An SPDX
    # identifier like "MIT" does not count: that is a name, not the text.
    for field in ("License", "License-Expression"):
        value = dist.metadata.get(field)
        if value and len(value.strip()) > 400:
            return value
    return None


#: Some wheels ship no licence text at all, only an identifier in their
#: metadata. The obligation to distribute the terms does not go away because
#: the packager left them out, so the standard text of the declared licence is
#: used, with the copyright holder taken from the package's own metadata and a
#: note saying exactly where each part came from. Nothing here is invented: if
#: the declared licence is not one of these, the build fails instead.
STANDARD_TEXTS = {
    "MIT": """MIT License

Copyright (c) {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.""",
}

# Native libraries do not have importlib distribution metadata. Keep their
# upstream licence text here so the generated file that travels beside each
# app still covers them. The attribution scanner decides whether a particular
# platform bundled the library; carrying the text on the others is harmless.
NATIVE_LICENCES = {
    "libmpdec 4.0.0": """Copyright (c) 2008-2024 Stefan Krah. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.""",
}

# Meson-built pycairo wheels omit the licence files that are present in the
# source archive. Debian and Ubuntu install the same standard texts centrally;
# use both because pycairo is dual-licensed. If another Linux builder does not
# provide them, collection still fails closed below.
SYSTEM_LICENCES = {
    "pycairo": (
        Path("/usr/share/common-licenses/LGPL-2.1"),
        Path("/usr/share/common-licenses/MPL-1.1"),
    ),
}

# PyInstaller copies these shared libraries into the Linux executable. They
# are Debian/Ubuntu packages rather than Python distributions, so their
# complete upstream notices and licence grants come from the package copyright
# files. Presence of PyGObject means this is the Linux build: in that case all
# of these files are mandatory and collection fails closed if one is absent.
LINUX_NATIVE_COPYRIGHTS = {
    # Ubuntu 24.04 uses the t64 GLib package name; 22.04 does not.
    "GLib": (
        Path("/usr/share/doc/libglib2.0-0t64/copyright"),
        Path("/usr/share/doc/libglib2.0-0/copyright"),
    ),
    "util-linux": (Path("/usr/share/doc/libblkid1/copyright"),),
    "PCRE2": (Path("/usr/share/doc/libpcre2-8-0/copyright"),),
    "libselinux": (Path("/usr/share/doc/libselinux1/copyright"),),
}


def system_licence_text(name):
    paths = SYSTEM_LICENCES.get(name)
    if not paths or not all(path.is_file() for path in paths):
        return None
    return "\n\n".join(
        "{}\n{}\n\n{}".format(path.name, "=" * len(path.name), path.read_text().strip())
        for path in paths
    )


def declared_holder(dist):
    """The copyright holder the distribution names for itself.

    Older metadata puts a bare name in ``Author``. Newer metadata folds the
    name into ``Author-email`` as ``"Name" <address>``, so the name has to be
    parsed back out of the address. Only the name is used; the address is not
    part of a licence notice.
    """

    for field in ("Author", "Maintainer"):
        value = (dist.metadata.get(field) or "").strip()
        if value:
            return value
    for field in ("Author-email", "Maintainer-email"):
        value = (dist.metadata.get(field) or "").strip()
        if not value:
            continue
        for one in getaddresses([value]):
            name = one[0].strip().strip('"').strip()
            if name:
                return name
    return None


def reconstructed_text(dist):
    """The declared licence's standard text, when the wheel ships none."""

    declared = (dist.metadata.get("License") or "").strip()
    if declared not in STANDARD_TEXTS:
        return None
    holder = declared_holder(dist)
    if not holder:
        return None
    body = STANDARD_TEXTS[declared].format(holder=holder)
    return (
        "[This distribution ships no licence file. Its metadata declares {},\n"
        " and names the author below. The standard text of that licence\n"
        " follows.]\n\n".format(declared) + body
    )


def build() -> tuple:
    distributions = installed_distributions()
    sections, missing = [], []

    sections.append(
        "Third-party licences bundled in PiTrac Easy-Connect\n"
        + ("=" * 52) + "\n\n"
        "The Raspberry Pi service uses only the Python standard library. The\n"
        "packaged macOS, Windows, and Linux applications bundle\n"
        "the components below, and their licence texts follow in full.\n"
    )

    for name in sorted(BUNDLED):
        key = name.lower().replace("_", "-")
        dist = distributions.get(key)
        if dist is None:
            continue                       # not installed on this platform
        text = licence_text(dist) or reconstructed_text(dist) or system_licence_text(name)
        version = dist.metadata["Version"]
        if not text:
            missing.append("{} {}".format(name, version))
            continue
        sections.append(
            "\n" + "-" * 72 + "\n{} {}\n".format(name, version) + "-" * 72 + "\n\n" + text.strip() + "\n"
        )
    for name, text in sorted(NATIVE_LICENCES.items()):
        sections.append(
            "\n" + "-" * 72 + "\n{}\n".format(name) + "-" * 72 + "\n\n"
            + text.strip() + "\n"
        )
    if "pygobject" in distributions:
        for name, candidates in sorted(LINUX_NATIVE_COPYRIGHTS.items()):
            path = next((one for one in candidates if one.is_file()), None)
            if path is None:
                missing.append("{} ({})".format(name, " or ".join(map(str, candidates))))
                continue
            sections.append(
                "\n" + "-" * 72 + "\n{} (Linux system library)\n".format(name)
                + "-" * 72 + "\n\n" + path.read_text(errors="replace").strip() + "\n"
            )
    return "\n".join(sections), missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    text, missing = build()
    if missing:
        print("No licence text found for: {}".format(", ".join(missing)))
        print("A bundled component without its licence cannot be distributed.")
        return 1

    if args.check:
        if not OUTPUT.exists():
            print("{} is missing. Run: python3 packaging/collect-licences.py".format(OUTPUT.name))
            return 1
        if OUTPUT.read_text() != text:
            print("{} is out of date. Run: python3 packaging/collect-licences.py".format(OUTPUT.name))
            return 1
        print("{} is current.".format(OUTPUT.name))
        return 0

    OUTPUT.write_text(text)
    print("Wrote {} ({:.0f} KB)".format(OUTPUT.name, len(text) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())

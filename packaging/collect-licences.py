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
    "pythonnet": ["clr"],
    "clr_loader": ["clr_loader"],
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


def reconstructed_text(dist):
    """The declared licence's standard text, when the wheel ships none."""

    declared = (dist.metadata.get("License") or "").strip()
    if declared not in STANDARD_TEXTS:
        return None
    holder = (dist.metadata.get("Author") or dist.metadata.get("Maintainer") or "").strip()
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
        "The Raspberry Pi service and running from source use only the Python\n"
        "standard library. The packaged macOS and Windows applications bundle\n"
        "the components below, and their licence texts follow in full.\n"
    )

    for name in sorted(BUNDLED):
        key = name.lower().replace("_", "-")
        dist = distributions.get(key)
        if dist is None:
            continue                       # not installed on this platform
        text = licence_text(dist) or reconstructed_text(dist)
        version = dist.metadata["Version"]
        if not text:
            missing.append("{} {}".format(name, version))
            continue
        sections.append(
            "\n" + "-" * 72 + "\n{} {}\n".format(name, version) + "-" * 72 + "\n\n" + text.strip() + "\n"
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

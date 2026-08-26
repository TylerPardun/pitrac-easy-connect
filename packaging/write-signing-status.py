#!/usr/bin/env python3
"""Record what actually happened when a platform's build tried to sign itself.

Each build job runs on its own runner, sometimes without the signing secrets
this repository's fork of a PR run cannot see. Rather than the build silently
falling back to an ad-hoc/unsigned artifact and the release job having no way
to know that happened, each platform writes one small, honest record of it --
uploaded alongside its zip or installer -- and the release job reads all of
them before deciding whether this release may call itself final.
"""

import argparse
import json
import sys
from pathlib import Path

PLATFORMS = ("macos-apple-silicon", "macos-intel", "windows")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--platform", required=True, choices=PLATFORMS)
    parser.add_argument("--signed", required=True, choices=("true", "false"))
    parser.add_argument(
        "--notarized", choices=("true", "false"), default="false",
        help="macOS only: whether notarization was submitted and stapled",
    )
    parser.add_argument("--detail", required=True)
    arguments = parser.parse_args(argv)

    signed = arguments.signed == "true"
    notarized = arguments.notarized == "true"
    if notarized and not signed:
        parser.error("a notarized build must also be signed")
    if arguments.platform != "windows" and arguments.detail == "":
        parser.error("--detail is required")

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps({
        "platform": arguments.platform,
        "signed": signed,
        "notarized": notarized,
        "detail": arguments.detail,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

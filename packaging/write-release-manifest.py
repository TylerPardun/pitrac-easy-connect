#!/usr/bin/env python3
"""Write the machine-readable manifest one release publishes about itself.

Every fact here is measured or declared in the source tree, never typed in
twice: sizes and digests come from the built files, the protocol version from
common/link.py, the package layout from companion/self_update.py, and the
supported-platform declarations from common/release_manifest.py. A release
that changes any of those changes this document by construction.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pitrac_easy_connect.common import link, release_manifest  # noqa: E402
from pitrac_easy_connect.companion import self_update  # noqa: E402


def described(path: Path) -> dict:
    payload = path.read_bytes()
    return {
        "name": path.name,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--channel", default=release_manifest.DEFAULT_CHANNEL)
    parser.add_argument(
        "--asset", type=Path, action="append", default=[],
        help="a published file; repeat once per asset",
    )
    parser.add_argument(
        "--pi-asset", type=Path, required=True,
        help="the enclosure's service archive",
    )
    arguments = parser.parse_args(argv)

    version = arguments.version.lstrip("v")
    assets = list(arguments.asset) + [arguments.pi_asset]
    missing = [str(path) for path in assets if not path.is_file()]
    if missing:
        raise SystemExit("these assets were not built: {}".format(", ".join(missing)))
    described_assets = [described(path) for path in assets]
    names = {entry["name"] for entry in described_assets}

    platforms = []
    for platform in release_manifest.DESKTOP_PLATFORMS:
        if platform["asset"] not in names:
            raise SystemExit(
                "this release declares a {} {} build but published no {}".format(
                    platform["system"], platform["machine"], platform["asset"]
                )
            )
        platforms.append(dict(platform))

    manifest = {
        "manifestVersion": release_manifest.MANIFEST_VERSION,
        "channel": arguments.channel,
        "signingKeyId": arguments.signing_key_id,
        "application": {"version": version, "tag": arguments.tag},
        "protocol": {
            "version": link.PROTOCOL_VERSION,
            "minimum": link.PROTOCOL_VERSION,
            "maximum": link.PROTOCOL_VERSION,
        },
        "packageLayoutVersion": self_update.PACKAGE_LAYOUT_VERSION,
        "minimumCompatible": {
            "desktop": release_manifest.MINIMUM_COMPATIBLE_DESKTOP,
            "piService": release_manifest.MINIMUM_COMPATIBLE_PI_SERVICE,
        },
        "assets": sorted(described_assets, key=lambda entry: entry["name"]),
        "desktop": {"platforms": platforms},
        "pi": {
            "asset": arguments.pi_asset.name,
            "hardware": list(release_manifest.PI_HARDWARE),
            "os": list(release_manifest.PI_OPERATING_SYSTEMS),
            "python": {"minimum": release_manifest.PI_MINIMUM_PYTHON},
        },
        "pitrac": {"minimumVersion": release_manifest.PITRAC_MINIMUM_VERSION},
    }

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print("Wrote {} describing {} assets for {}".format(
        arguments.out, len(described_assets), arguments.tag
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Sign a release manifest's exact bytes with the release Ed25519 key.

The signature covers the file as published, byte for byte. Nothing here
re-serialises or canonicalises it, because the applications verify the bytes
they downloaded and any difference between the two would be a signature that
checks out over something nobody actually read.

The private key arrives on stdin or in a file that this deletes nothing and
keeps nothing: in the workflow it is a secret written to a temporary path.
"""

import argparse
import base64
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pitrac_easy_connect.common import release_manifest, signing  # noqa: E402
from openssl_tools import command as openssl_command  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--openssl", help="path to OpenSSL 1.1.1 or newer (auto-detected by default)"
    )
    arguments = parser.parse_args(argv)
    openssl = openssl_command(arguments.openssl)

    manifest_bytes = arguments.manifest.read_bytes()
    signature = subprocess.run(
        [openssl, "pkeyutl", "-sign", "-inkey", str(arguments.key),
         "-rawin", "-in", str(arguments.manifest)],
        check=True, capture_output=True,
    ).stdout
    if len(signature) != signing.SIGNATURE_BYTES:
        raise SystemExit("openssl produced a {}-byte signature".format(len(signature)))

    der = subprocess.run(
        [openssl, "pkey", "-in", str(arguments.key), "-pubout", "-outform", "DER"],
        check=True, capture_output=True,
    ).stdout
    public = der[-32:]
    identifier = release_manifest.key_id(public)

    # Verify before publishing, with the same code the applications run. A
    # signature nobody checked until a user's machine checked it is a release
    # that finds out in the field.
    if not signing.verify(manifest_bytes, signature, public):
        raise SystemExit("the signature this key produced does not verify")
    manifest = release_manifest.verify_manifest(
        manifest_bytes, base64.b64encode(signature), trusted={identifier: public},
    )
    if str(manifest.get("signingKeyId")) != identifier:
        raise SystemExit(
            "the manifest names signing key {!r} but this key is {}".format(
                manifest.get("signingKeyId"), identifier
            )
        )

    out = arguments.out or arguments.manifest.with_name(
        arguments.manifest.name + ".sig"
    )
    out.write_bytes(base64.b64encode(signature) + b"\n")
    print("Signed {} with key {} -> {}".format(arguments.manifest, identifier, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate the Ed25519 key a release manifest is signed with.

Run once, by a maintainer, off any shared machine. It prints two things:
the private key, which goes into the release environment's secrets and
nowhere else, and the line to paste into ``_PINNED_KEYS`` so applications
will trust the matching signatures.

Rotation is an addition, never an edit: keep the old public key pinned until
no supported release is still signed with it. See SECURITY.md.
"""

import argparse
import base64
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pitrac_easy_connect.common import release_manifest  # noqa: E402
from openssl_tools import command as openssl_command  # noqa: E402


def raw_public_key(private_pem: Path, openssl: str) -> bytes:
    """The 32 key bytes, out of the DER SubjectPublicKeyInfo wrapper."""

    der = subprocess.run(
        [openssl, "pkey", "-in", str(private_pem), "-pubout", "-outform", "DER"],
        check=True, capture_output=True,
    ).stdout
    if len(der) != 44:
        raise SystemExit("that is not an Ed25519 public key ({} DER bytes)".format(len(der)))
    return der[-32:]


def generate_private_key(path: Path, explicit_openssl=None) -> str:
    """Generate with an installed implementation supporting Ed25519."""

    openssl = openssl_command(explicit_openssl)
    subprocess.run(
        [openssl, "genpkey", "-algorithm", "ed25519", "-out", str(path)],
        check=True, capture_output=True,
    )
    return openssl


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("release-signing-key.pem"))
    parser.add_argument(
        "--openssl", help="path to OpenSSL 1.1.1 or newer (auto-detected by default)"
    )
    arguments = parser.parse_args(argv)

    if arguments.out.exists():
        raise SystemExit("{} already exists; refusing to overwrite a key".format(arguments.out))
    openssl = generate_private_key(arguments.out, arguments.openssl)
    arguments.out.chmod(0o600)
    public = raw_public_key(arguments.out, openssl)
    identifier = release_manifest.key_id(public)

    print("Private key written to {} (mode 0600).".format(arguments.out))
    print()
    print("1. Put its contents in the release environment secret "
          "PITRAC_RELEASE_SIGNING_KEY, then delete the file:")
    print("     gh secret set PITRAC_RELEASE_SIGNING_KEY --env release < {}".format(
        arguments.out))
    print("     rm {}".format(arguments.out))
    print()
    print("2. Add this to _PINNED_KEYS in "
          "src/pitrac_easy_connect/common/release_manifest.py:")
    print()
    print('    "{}": "{}",'.format(identifier, public.hex()))
    print()
    print("   Key ID:            {}".format(identifier))
    print("   Public key base64: {}".format(base64.b64encode(public).decode()))
    print()
    print("Applications built before that line is added will refuse every release "
          "at or above {}.".format(release_manifest.MANIFEST_REQUIRED_FROM))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

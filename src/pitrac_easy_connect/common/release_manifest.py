"""What a release says about itself, and why it may be believed.

Every release already publishes a SHA-256 for each file, and the updaters
already check it. That proves the download arrived intact. It does not prove
the project produced it: the checksum and the file come from the same release
API, so whoever can answer as that API can serve a matching pair of both.
"Updates are signed" was never true of a digest delivered beside its own file.

So each release also publishes one small manifest describing itself -- the
exact assets and their sizes and digests, which platforms they are for, which
protocol versions they speak, and what they will refuse to install over -- and
one detached Ed25519 signature over that manifest's exact bytes. The signing
key is held by the release workflow; only the public half is pinned here.

Two details are load-bearing:

The signature covers the literal bytes of the downloaded file, not a
re-serialisation of the parsed object. Canonicalising JSON before verifying is
a well-worn way to end up verifying something subtly different from what was
actually read, so the bytes are verified first and parsed afterwards.

Being unable to verify is not the same answer as "did not verify", and neither
is the same as "verified". A machine with no usable OpenSSL, a release with no
manifest, and a release with a bad signature are three different situations,
and only one of them is ever allowed to end in an installation.
"""

import base64
import hashlib
import json
from typing import Any, Callable, Dict, Optional

from . import signing
from .versions import compare, parse

#: The two files each release publishes alongside its packages.
MANIFEST_ASSET = "release-manifest.json"
SIGNATURE_ASSET = "release-manifest.json.sig"

#: The manifest layout this code understands. A release declaring a newer one
#: is refused rather than read optimistically: the whole point of the document
#: is that its meaning is not open to interpretation.
MANIFEST_VERSION = 1

#: Releases from this version onward must carry a manifest that verifies.
#: Earlier releases genuinely have none -- they were published before any of
#: this existed -- so they fall back to the digest check they shipped with.
#: This is a one-way transition pinned to a version, not a preference: a
#: release at or above it that publishes no manifest is refused, and so is one
#: whose manifest does not verify.
MANIFEST_REQUIRED_FROM = "0.9.0"

#: Public halves of the keys this project signs releases with, by key ID.
#: The private halves live only in the release environment's secrets.
#:
#: Rotation adds a new public key before it is used and retains the old key
#: until no supported installed release depends on it. See SECURITY.md.
_PINNED_KEYS: Dict[str, str] = {
    "88a9e5c5d11a50d5": "737c1cdf730b3b518e25c4829575619f6837f65844ed0d437b3b873bab1af4bd",
}

#: Maximum bytes to read for either file. Both are small documents; this
#: exists so a hostile release API cannot make the updater read a stream
#: forever before it has authenticated anything at all.
MAX_MANIFEST_BYTES = 256 * 1024


# --- What this source tree declares when it builds a release -------------
#
# Kept beside the rules that read it, so the document the workflow writes and
# the checks the applications make cannot drift apart without a test noticing.
# Everything here is a statement about what was built and tested, not a
# preference: changing one means a release genuinely supports something else.

#: The desktop builds published for each platform, and the oldest OS each one
#: will start on. macOS is set by LSMinimumSystemVersion in the app spec.
DESKTOP_PLATFORMS = (
    {"system": "Darwin", "machine": "arm64", "minimumOS": "11.0",
     "asset": "PiTrac-Easy-Connect-macos-apple-silicon.zip"},
    {"system": "Darwin", "machine": "x86_64", "minimumOS": "11.0",
     "asset": "PiTrac-Easy-Connect-macos-intel.zip"},
    {"system": "Windows", "machine": "x86_64", "minimumOS": "10.0.19041",
     "asset": "PiTrac-Easy-Connect-windows.zip"},
)

#: The enclosure this release is built and tested for. install.sh refuses
#: anything that is not 64-bit, and warns on any model but a Pi 5.
PI_HARDWARE = ("Raspberry Pi 5",)
PI_OPERATING_SYSTEMS = ("Raspberry Pi OS",)
PI_MINIMUM_PYTHON = "3.9"

#: The PiTrac the relay and dashboard were exercised against.
PITRAC_MINIMUM_VERSION = ""

#: What this release refuses to install itself over. An update is a swap of a
#: whole directory, not a migration, so anything older than these has to be
#: reinstalled rather than updated.
MINIMUM_COMPATIBLE_DESKTOP = "0.7.0"
MINIMUM_COMPATIBLE_PI_SERVICE = "0.7.0"

DEFAULT_CHANNEL = "stable"


class ManifestError(Exception):
    """The release could not be authenticated, so nothing about it is usable."""


def trusted_keys() -> Dict[str, bytes]:
    return {
        key_id: bytes.fromhex(value) for key_id, value in _PINNED_KEYS.items()
    }


def key_id(public_key: bytes) -> str:
    """A short stable name for a key, so rotation is an addition not an edit."""

    return hashlib.sha256(bytes(public_key)).hexdigest()[:16]


def signature_required_for(tag: str) -> bool:
    """Whether this release is one that must carry a verified manifest."""

    order = compare(str(tag or ""), MANIFEST_REQUIRED_FROM)
    return order is not None and order >= 0


def verify_manifest(manifest_bytes: bytes, signature_text: bytes,
                    *, trusted: Optional[Dict[str, bytes]] = None) -> Dict[str, Any]:
    """Authenticate the exact bytes read, then read them.

    Raises ManifestError for every failure, including being unable to check.
    A caller that gets an exception here has learned nothing it may act on.
    """

    keys = trusted_keys() if trusted is None else dict(trusted)
    if not keys:
        raise ManifestError(
            "this build pins no release signing key, so no release can be authenticated"
        )
    if len(manifest_bytes or b"") > MAX_MANIFEST_BYTES:
        raise ManifestError("the release manifest is implausibly large")

    try:
        signature = base64.b64decode(bytes(signature_text or b"").strip(), validate=True)
    except (ValueError, TypeError):
        raise ManifestError("the release manifest signature is not valid base64")

    try:
        matched = [
            name for name, public in keys.items()
            if signing.verify(manifest_bytes, signature, public)
        ]
    except signing.SigningUnavailable as exc:
        # Not a rejection: this machine could not ask the question. Refusing
        # is still the only safe outcome, but the reason has to survive.
        raise ManifestError(
            "the release signature could not be checked on this computer: {}".format(exc)
        )
    if not matched:
        raise ManifestError(
            "the release manifest is not signed by any key this application trusts"
        )

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ManifestError("the release manifest is not readable: {}".format(exc))
    if not isinstance(manifest, dict):
        raise ManifestError("the release manifest is not a record")

    declared = manifest.get("manifestVersion")
    if declared != MANIFEST_VERSION:
        raise ManifestError(
            "this application understands release manifest version {}, not {!r}".format(
                MANIFEST_VERSION, declared
            )
        )
    stated = str(manifest.get("signingKeyId") or "")
    if stated not in matched:
        # The signature is genuine, but the document names a different key.
        # That mismatch is exactly what a rotation gone wrong looks like.
        raise ManifestError(
            "the manifest names signing key {!r} but was signed by {}".format(
                stated, ", ".join(sorted(matched))
            )
        )
    _require_shape(manifest)
    return manifest


def _require_shape(manifest: Dict[str, Any]) -> None:
    """Every field a caller is allowed to rely on, present and the right type."""

    for key, kind in (
        ("channel", str), ("application", dict), ("protocol", dict),
        ("assets", list), ("desktop", dict), ("pi", dict),
        ("packageLayoutVersion", int), ("minimumCompatible", dict),
    ):
        if not isinstance(manifest.get(key), kind):
            raise ManifestError("the release manifest has no usable {!r}".format(key))
    application = manifest["application"]
    if not parse(str(application.get("version") or "")):
        raise ManifestError("the release manifest states no readable version")
    if not str(application.get("tag") or ""):
        raise ManifestError("the release manifest states no tag")
    for asset in manifest["assets"]:
        if not isinstance(asset, dict):
            raise ManifestError("the release manifest lists an unreadable asset")
        if not str(asset.get("name") or ""):
            raise ManifestError("the release manifest lists an asset with no name")
        digest = str(asset.get("sha256") or "")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
            raise ManifestError(
                "the release manifest gives no usable digest for {}".format(
                    asset.get("name")
                )
            )
        if not isinstance(asset.get("size"), int) or asset["size"] <= 0:
            raise ManifestError(
                "the release manifest gives no usable size for {}".format(asset["name"])
            )


# --- Reading a verified manifest ----------------------------------------

def asset(manifest: Dict[str, Any], name: str) -> Dict[str, Any]:
    for entry in manifest.get("assets", []):
        if str(entry.get("name")) == str(name):
            return entry
    raise ManifestError("the release manifest does not describe {}".format(name))


def expected_digest(manifest: Dict[str, Any], name: str) -> str:
    return str(asset(manifest, name)["sha256"]).lower()


def expected_size(manifest: Dict[str, Any], name: str) -> int:
    return int(asset(manifest, name)["size"])


def declared_tag(manifest: Dict[str, Any]) -> str:
    return str(manifest["application"]["tag"])


def declared_version(manifest: Dict[str, Any]) -> str:
    return str(manifest["application"]["version"])


def desktop_asset_for(manifest: Dict[str, Any], system: str, machine: str) -> str:
    """The one asset this manifest says belongs to this computer."""

    for platform in manifest.get("desktop", {}).get("platforms", []):
        if (str(platform.get("system")) == str(system)
                and str(platform.get("machine")) == str(machine)):
            return str(platform.get("asset") or "")
    return ""


def check_desktop_supported(manifest: Dict[str, Any], *, version: str,
                            system: str, machine: str) -> Optional[str]:
    """Why this desktop may not take this release, or None if it may."""

    if not desktop_asset_for(manifest, system, machine):
        return "Version {} does not publish a build for {} {}.".format(
            declared_version(manifest), system, machine
        )
    minimum = str(manifest.get("minimumCompatible", {}).get("desktop") or "")
    if minimum:
        order = compare(str(version), minimum)
        if order is None:
            return "This application's version could not be compared with {}.".format(minimum)
        if order < 0:
            return (
                "Version {} can only be installed over {} or newer, and this is {}."
            ).format(declared_version(manifest), minimum, version)
    return None


def check_pi_supported(manifest: Dict[str, Any], *, version: str,
                       python_version: str, model: str = "",
                       os_name: str = "") -> Optional[str]:
    """Why this enclosure may not take this release, or None if it may."""

    pi = manifest.get("pi", {})
    if not str(pi.get("asset") or ""):
        return "Version {} publishes no enclosure package.".format(declared_version(manifest))

    minimum_python = str(pi.get("python", {}).get("minimum") or "")
    if minimum_python:
        order = compare(str(python_version), minimum_python)
        if order is None or order < 0:
            return (
                "Version {} needs Python {} or newer, and this enclosure has {}."
            ).format(declared_version(manifest), minimum_python, python_version)

    minimum_service = str(manifest.get("minimumCompatible", {}).get("piService") or "")
    if minimum_service:
        order = compare(str(version), minimum_service)
        if order is None:
            return "The enclosure's version could not be compared with {}.".format(
                minimum_service
            )
        if order < 0:
            return (
                "Version {} can only be installed over {} or newer, and this enclosure "
                "is on {}. Reinstall it from the current release instead."
            ).format(declared_version(manifest), minimum_service, version)

    # Hardware and OS are refused only when this enclosure is sure what it is.
    # An unreadable model string is a Pi we cannot identify, not a Pi we know
    # to be unsupported, and bricking updates on an unfamiliar board is worse
    # than installing on one.
    supported_hardware = [str(value) for value in pi.get("hardware", []) if value]
    if model and supported_hardware and not any(
        entry.lower() in model.lower() for entry in supported_hardware
    ):
        return "Version {} is not published for {}.".format(declared_version(manifest), model)
    supported_os = [str(value) for value in pi.get("os", []) if value]
    if os_name and supported_os and not any(
        entry.lower() in os_name.lower() for entry in supported_os
    ):
        return "Version {} is not published for {}.".format(
            declared_version(manifest), os_name
        )
    return None


def protocol_range(manifest: Dict[str, Any]):
    protocol = manifest.get("protocol", {})
    minimum = protocol.get("minimum", protocol.get("version"))
    maximum = protocol.get("maximum", protocol.get("version"))
    return int(minimum), int(maximum)


# --- Getting one from a release -----------------------------------------

def fetch_manifest(release: Dict[str, Any], fetch: Callable[[str], bytes], *,
                   tag: str, trusted: Optional[Dict[str, bytes]] = None
                   ) -> Optional[Dict[str, Any]]:
    """Read and authenticate the manifest a release publishes, if it must.

    Returns None only for a release old enough to predate manifests entirely.
    Every other outcome is either a verified manifest or an exception; there
    is deliberately no third answer meaning "carry on unverified".
    """

    assets = {str(item.get("name") or ""): item for item in release.get("assets", [])}
    manifest_asset = assets.get(MANIFEST_ASSET)
    signature_asset = assets.get(SIGNATURE_ASSET)
    required = signature_required_for(tag)

    if manifest_asset is None or signature_asset is None:
        if required:
            raise ManifestError(
                "Release {} publishes no signed manifest, so it was not installed."
                .format(tag)
            )
        return None

    manifest_bytes = bytes(fetch(str(manifest_asset.get("browser_download_url") or "")))
    signature_text = bytes(fetch(str(signature_asset.get("browser_download_url") or "")))
    manifest = verify_manifest(manifest_bytes, signature_text, trusted=trusted)

    # The signature proves the project wrote this document. It does not prove
    # the document is about the release it was found in, and a valid manifest
    # from a different release is exactly what a downgrade attack serves.
    if compare(declared_tag(manifest), str(tag)) != 0:
        raise ManifestError(
            "the manifest found on release {} describes {} instead".format(
                tag, declared_tag(manifest)
            )
        )
    return manifest

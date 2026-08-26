"""A deterministic release-signing key, for tests only.

The applications only ever verify, so there is no signing code to reuse here.
Shelling out to the ``openssl`` command is not an option either: the suite
runs on Windows CI, where there is no such command. So this drives the same
libcrypto the verifier uses, through the signing half of the same API.

The key is a fixed seed rather than a fresh one, so a failure is reproducible
and no test depends on key generation working.
"""

import base64
import ctypes
import hashlib
import json
import sys

import pytest

from pitrac_easy_connect.common import release_manifest, signing

#: Platforms every CI runner in this project covers. libcrypto is expected to
#: be genuinely loadable here; treat "unavailable" as a real regression to
#: fail loudly on rather than a skip, since a skip is exactly what let
#: signing.py go unable to find any libcrypto at all on Windows for a whole
#: release cycle without a single test noticing.
_ALWAYS_SUPPORTED_PLATFORMS = ("win32", "darwin", "linux")

#: Not a secret and never used for anything real: 32 fixed bytes.
SEED = bytes(range(32))


def _library():
    try:
        library = signing.libcrypto()
    except signing.SigningUnavailable as exc:
        if sys.platform in _ALWAYS_SUPPORTED_PLATFORMS:
            pytest.fail(
                "libcrypto could not be loaded on {}, a platform this project "
                "runs CI on and expects to always find one: {}".format(sys.platform, exc)
            )
        pytest.skip("no OpenSSL with Ed25519 on this machine: {}".format(exc))
    library.EVP_PKEY_new_raw_private_key.restype = ctypes.c_void_p
    library.EVP_PKEY_new_raw_private_key.argtypes = [
        ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t,
    ]
    library.EVP_PKEY_get_raw_public_key.restype = ctypes.c_int
    library.EVP_PKEY_get_raw_public_key.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t),
    ]
    library.EVP_DigestSignInit.restype = ctypes.c_int
    library.EVP_DigestSignInit.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p,
    ]
    library.EVP_DigestSign.restype = ctypes.c_int
    library.EVP_DigestSign.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_char_p, ctypes.c_size_t,
    ]
    return library


def _private():
    library = _library()
    key = library.EVP_PKEY_new_raw_private_key(
        signing.NID_ED25519, None, SEED, len(SEED)
    )
    assert key, "libcrypto would not accept the fixed test seed"
    return library, key


def public_key() -> bytes:
    library, key = _private()
    try:
        size = ctypes.c_size_t(signing.PUBLIC_KEY_BYTES)
        buffer = ctypes.create_string_buffer(signing.PUBLIC_KEY_BYTES)
        assert library.EVP_PKEY_get_raw_public_key(key, buffer, ctypes.byref(size)) == 1
        return buffer.raw[: size.value]
    finally:
        library.EVP_PKEY_free(key)


def sign(message: bytes) -> bytes:
    library, key = _private()
    context = None
    try:
        context = library.EVP_MD_CTX_new()
        assert library.EVP_DigestSignInit(context, None, None, None, key) == 1
        size = ctypes.c_size_t(signing.SIGNATURE_BYTES)
        buffer = ctypes.create_string_buffer(signing.SIGNATURE_BYTES)
        assert library.EVP_DigestSign(
            context, buffer, ctypes.byref(size), bytes(message), len(message)
        ) == 1
        return buffer.raw[: size.value]
    finally:
        if context:
            library.EVP_MD_CTX_free(context)
        library.EVP_PKEY_free(key)


def key_id() -> str:
    return release_manifest.key_id(public_key())


def trusted() -> dict:
    return {key_id(): public_key()}


def pin(monkeypatch) -> None:
    """Make this key the one the applications trust, for one test."""

    monkeypatch.setattr(
        release_manifest, "_PINNED_KEYS", {key_id(): public_key().hex()}
    )


def manifest_for(assets, *, version, tag=None, pi_asset=None, **overrides):
    """A well-formed manifest describing exactly these bytes.

    ``assets`` maps filename to the published bytes, so the digests and sizes
    are the real ones rather than values a test has to keep in step by hand.
    """

    tag = tag or ("v" + version)
    described = [
        {"name": name,
         "size": len(payload),
         "sha256": hashlib.sha256(payload).hexdigest()}
        for name, payload in sorted(assets.items())
    ]
    manifest = {
        "manifestVersion": release_manifest.MANIFEST_VERSION,
        "channel": "stable",
        "signingKeyId": key_id(),
        "application": {"version": version, "tag": tag},
        "protocol": {"version": 1, "minimum": 1, "maximum": 1},
        "packageLayoutVersion": 1,
        "minimumCompatible": {"desktop": "0.1.0", "piService": "0.1.0"},
        "assets": described,
        "desktop": {"platforms": [
            dict(platform) for platform in release_manifest.DESKTOP_PLATFORMS
            if platform["asset"] in assets
        ]},
        "pi": {
            "asset": pi_asset or "",
            "hardware": list(release_manifest.PI_HARDWARE),
            "os": list(release_manifest.PI_OPERATING_SYSTEMS),
            "python": {"minimum": "3.9"},
        },
        "pitrac": {"minimumVersion": ""},
    }
    for key, value in overrides.items():
        manifest[key] = value
    return manifest


def signed(manifest):
    """The exact bytes to publish, and the detached signature over them."""

    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return payload, base64.b64encode(sign(payload)) + b"\n"

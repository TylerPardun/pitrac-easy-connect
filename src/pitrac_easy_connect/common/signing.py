"""Ed25519 signature verification, borrowed rather than written.

This project ships no packages: the enclosure gets a directory of Python and
nothing to install, and that is worth keeping. But a checksum published by the
same API as the file it describes proves only that the download arrived
intact, not that the project produced it -- anyone who can answer as the
release API can serve both. Release manifests are therefore signed, and
something has to check the signature.

Nothing here implements any cryptography. The signature check is OpenSSL's
``EVP_DigestVerify`` against a raw Ed25519 public key, reached through ctypes.
The only judgement this module makes is *which* libcrypto to load, and the
only interesting part of that is refusing one particular library:

macOS ships a stub at /usr/lib/libcrypto.dylib whose entire behaviour on being
loaded is to abort the process. Not raise -- abort, uncatchably, taking the
application with it. ``ctypes.util.find_library("crypto")`` returns exactly
that path. So candidates are tried in a deliberate order, most-known-good
first, and anything in the macOS system library directory is never opened at
all.

Signing lives in the release workflow, not here. This side only ever verifies.
"""

import ctypes
import ctypes.util
import os
import sys
import sysconfig
from pathlib import Path
from typing import Iterator, Optional

#: OpenSSL's NID for Ed25519, which is what identifies the key type when a
#: raw 32-byte public key is turned into an EVP_PKEY.
NID_ED25519 = 1087
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64


class SigningUnavailable(Exception):
    """No usable libcrypto, so nothing can be verified on this machine.

    Deliberately distinct from "the signature did not match". A caller that
    cannot verify must refuse the update, not install it; keeping the two
    apart is what stops that becoming a silent skip.
    """


def _macos_system_library(path: Path) -> bool:
    """The stub that aborts the process. Never opened, only recognised."""

    if sys.platform != "darwin":
        return False
    return str(path).startswith("/usr/lib/libcrypto")


def _bundled() -> Iterator[Path]:
    """What a frozen desktop build ships, which is what it was tested with."""

    base = getattr(sys, "_MEIPASS", None)
    if base is None and getattr(sys, "frozen", False):
        base = Path(sys.executable).parent / "_internal"
    if not base:
        return
    for name in ("libcrypto*.dylib", "libcrypto*.so*", "libcrypto*.dll"):
        for found in sorted(Path(base).glob(name)):
            yield found


def _alongside_python() -> Iterator[Path]:
    """The library the running interpreter's own ``ssl`` module already uses.

    On Raspberry Pi OS this is the packaged system OpenSSL; in a virtual
    environment or a conda prefix it is that prefix's own copy. On Windows,
    the official CPython builds (including the ones GitHub Actions'
    setup-python installs) bundle their own OpenSSL DLLs in a "DLLs"
    subdirectory or directly beside python.exe, under an
    architecture-suffixed name (``libcrypto-3-arm64.dll``,
    ``libcrypto-3-x64.dll``, and so on) rather than a fixed one -- hence the
    glob, matching every architecture instead of naming each one. Either way
    it is a real library rather than a stub, because ``import ssl`` worked.
    """

    for variable in ("LIBDIR", "prefix", "base"):
        directory = sysconfig.get_config_var(variable)
        if not directory:
            continue
        for parent in (Path(directory), Path(directory) / "lib", Path(directory) / "DLLs"):
            if not parent.is_dir():
                continue
            for pattern in ("libcrypto*.dylib", "libcrypto*.so*", "libcrypto*.dll"):
                for found in sorted(parent.glob(pattern)):
                    yield found


def _from_loader() -> Iterator[Path]:
    found = ctypes.util.find_library("crypto")
    if found:
        yield Path(found)


def candidates() -> Iterator[Path]:
    seen = set()
    for source in (_bundled(), _alongside_python(), _from_loader()):
        for path in source:
            if _macos_system_library(path):
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            yield path


_library = None
_looked = False


def libcrypto():
    """The first candidate that loads and offers the Ed25519 raw-key API."""

    global _library, _looked
    if _looked:
        if _library is None:
            raise SigningUnavailable(
                "no OpenSSL library with Ed25519 support could be loaded"
            )
        return _library
    _looked = True
    for path in candidates():
        try:
            library = ctypes.CDLL(str(path))
        except OSError:
            continue
        if not all(hasattr(library, name) for name in (
            "EVP_PKEY_new_raw_public_key", "EVP_MD_CTX_new",
            "EVP_DigestVerifyInit", "EVP_DigestVerify",
        )):
            # OpenSSL older than 1.1.1, which predates Ed25519 entirely.
            continue
        _declare(library)
        _library = library
        return library
    raise SigningUnavailable("no OpenSSL library with Ed25519 support could be loaded")


def _declare(library) -> None:
    """Argument types, so a 64-bit pointer is never truncated to an int."""

    library.EVP_PKEY_new_raw_public_key.restype = ctypes.c_void_p
    library.EVP_PKEY_new_raw_public_key.argtypes = [
        ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t,
    ]
    library.EVP_PKEY_free.argtypes = [ctypes.c_void_p]
    library.EVP_MD_CTX_new.restype = ctypes.c_void_p
    library.EVP_MD_CTX_free.argtypes = [ctypes.c_void_p]
    library.EVP_DigestVerifyInit.restype = ctypes.c_int
    library.EVP_DigestVerifyInit.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p,
    ]
    library.EVP_DigestVerify.restype = ctypes.c_int
    library.EVP_DigestVerify.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t,
        ctypes.c_char_p, ctypes.c_size_t,
    ]


def available() -> bool:
    """Whether this machine can verify at all, without deciding anything."""

    try:
        libcrypto()
    except SigningUnavailable:
        return False
    return True


def verify(message: bytes, signature: bytes, public_key: bytes) -> bool:
    """Whether ``signature`` is this key's Ed25519 signature over ``message``.

    Returns False for every bad signature. Raises SigningUnavailable when the
    question could not be asked, which is a different answer and must not be
    confused with "no".
    """

    if not isinstance(message, (bytes, bytearray)):
        raise TypeError("the signed message must be bytes")
    signature = bytes(signature or b"")
    public_key = bytes(public_key or b"")
    if len(public_key) != PUBLIC_KEY_BYTES or len(signature) != SIGNATURE_BYTES:
        # Wrong-sized input is a malformed signature, not an unusable machine.
        return False

    library = libcrypto()
    key = library.EVP_PKEY_new_raw_public_key(
        NID_ED25519, None, public_key, PUBLIC_KEY_BYTES
    )
    if not key:
        return False
    context = None
    try:
        context = library.EVP_MD_CTX_new()
        if not context:
            raise SigningUnavailable("OpenSSL would not allocate a digest context")
        if library.EVP_DigestVerifyInit(context, None, None, None, key) != 1:
            return False
        return library.EVP_DigestVerify(
            context, signature, len(signature), bytes(message), len(message)
        ) == 1
    finally:
        if context:
            library.EVP_MD_CTX_free(context)
        library.EVP_PKEY_free(key)


def describe() -> str:
    """Which library is doing the verifying, for logs and support questions."""

    try:
        library = libcrypto()
    except SigningUnavailable as exc:
        return str(exc)
    try:
        library.OpenSSL_version.restype = ctypes.c_char_p
        return library.OpenSSL_version(0).decode("utf-8", "replace")
    except Exception:                            # pragma: no cover - very old
        return "an OpenSSL library with Ed25519 support"

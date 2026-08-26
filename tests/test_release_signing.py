"""Releases are authenticated, not merely checksummed.

The digest a release publishes for a file arrives from the same API as the
file's own download URL. It proves the bytes arrived intact; it cannot prove
the project produced them, because anything able to answer as that API can
serve a matching pair of file and digest. The manifest and its detached
Ed25519 signature are what close that, and everything here is about the
places where an unverified release must be refused rather than installed.
"""

import base64
import json

import pytest

import manifest_fixture
from pitrac_easy_connect.common import release_manifest as rm
from pitrac_easy_connect.common import signing
from pitrac_easy_connect.common.updates import ArchiveUpdater


@pytest.fixture(autouse=True)
def pinned(monkeypatch):
    manifest_fixture.pin(monkeypatch)


def a_manifest(**kwargs):
    kwargs.setdefault("version", "9.9.9")
    kwargs.setdefault("pi_asset", "PiTrac-Easy-Connect-9.9.9.pyz")
    return manifest_fixture.manifest_for(
        {"PiTrac-Easy-Connect-9.9.9.pyz": b"the enclosure package"}, **kwargs
    )


# --- The signature -------------------------------------------------------


def test_a_genuine_manifest_verifies_and_is_readable():
    payload, signature = manifest_fixture.signed(a_manifest())
    manifest = rm.verify_manifest(payload, signature)
    assert rm.declared_tag(manifest) == "v9.9.9"
    assert rm.expected_size(manifest, "PiTrac-Easy-Connect-9.9.9.pyz") == len(
        b"the enclosure package"
    )


@pytest.mark.parametrize("damage", [
    lambda payload: payload.replace(b'"9.9.9"', b'"9.9.8"'),
    lambda payload: payload + b" ",
    lambda payload: payload[:-1],
    lambda payload: b"{}",
])
def test_any_change_to_the_signed_bytes_is_refused(damage):
    payload, signature = manifest_fixture.signed(a_manifest())
    with pytest.raises(rm.ManifestError):
        rm.verify_manifest(damage(payload), signature)


def test_a_signature_from_another_key_is_refused():
    payload, _signature = manifest_fixture.signed(a_manifest())
    stranger = base64.b64encode(bytes(signing.SIGNATURE_BYTES))
    with pytest.raises(rm.ManifestError, match="not signed by any key"):
        rm.verify_manifest(payload, stranger)


def test_a_manifest_naming_a_key_it_was_not_signed_with_is_refused():
    """What a rotation gone wrong looks like, and it must not pass."""

    manifest = a_manifest()
    manifest["signingKeyId"] = "0123456789abcdef"
    payload, signature = manifest_fixture.signed(manifest)
    with pytest.raises(rm.ManifestError, match="names signing key"):
        rm.verify_manifest(payload, signature)


def test_a_build_with_no_pinned_key_trusts_nothing(monkeypatch):
    """Shipping before the release key exists must fail closed, loudly."""

    monkeypatch.setattr(rm, "_PINNED_KEYS", {})
    payload, signature = manifest_fixture.signed(a_manifest())
    with pytest.raises(rm.ManifestError, match="pins no release signing key"):
        rm.verify_manifest(payload, signature)


def test_being_unable_to_check_is_refused_not_treated_as_valid(monkeypatch):
    """A machine with no usable OpenSSL must not quietly install anyway."""

    def no_library(*_args, **_kwargs):
        raise signing.SigningUnavailable("no OpenSSL library with Ed25519 support")

    monkeypatch.setattr(signing, "verify", no_library)
    payload, signature = manifest_fixture.signed(a_manifest())
    with pytest.raises(rm.ManifestError, match="could not be checked"):
        rm.verify_manifest(payload, signature)


def test_a_signature_that_is_not_base64_is_refused():
    payload, _signature = manifest_fixture.signed(a_manifest())
    with pytest.raises(rm.ManifestError, match="valid base64"):
        rm.verify_manifest(payload, b"not base64 at all !!!")


def test_an_implausibly_large_manifest_is_refused_before_verifying():
    with pytest.raises(rm.ManifestError, match="implausibly large"):
        rm.verify_manifest(b"x" * (rm.MAX_MANIFEST_BYTES + 1), b"")


def test_a_newer_manifest_layout_is_refused_rather_than_guessed_at():
    manifest = a_manifest()
    manifest["manifestVersion"] = rm.MANIFEST_VERSION + 1
    payload, signature = manifest_fixture.signed(manifest)
    with pytest.raises(rm.ManifestError, match="understands release manifest version"):
        rm.verify_manifest(payload, signature)


@pytest.mark.parametrize("field", [
    "channel", "application", "protocol", "assets", "desktop", "pi",
    "packageLayoutVersion", "minimumCompatible",
])
def test_a_signed_but_incomplete_manifest_is_refused(field):
    """A genuine signature over a useless document is still useless."""

    manifest = a_manifest()
    del manifest[field]
    payload, signature = manifest_fixture.signed(manifest)
    with pytest.raises(rm.ManifestError, match="no usable"):
        rm.verify_manifest(payload, signature)


@pytest.mark.parametrize("asset,reason", [
    ({"name": "a.zip", "size": 1, "sha256": "nope"}, "no usable digest"),
    ({"name": "a.zip", "size": 0, "sha256": "a" * 64}, "no usable size"),
    ({"name": "", "size": 1, "sha256": "a" * 64}, "no name"),
])
def test_an_asset_the_manifest_cannot_pin_down_is_refused(asset, reason):
    manifest = a_manifest()
    manifest["assets"] = [asset]
    payload, signature = manifest_fixture.signed(manifest)
    with pytest.raises(rm.ManifestError, match=reason):
        rm.verify_manifest(payload, signature)


# --- Finding one on a release -------------------------------------------


def _release(tag, manifest=None):
    assets = [{"name": "PiTrac-Easy-Connect-{}.pyz".format(tag.lstrip("v")),
               "browser_download_url": "https://example.invalid/a.pyz"}]
    documents = {}
    if manifest is not None:
        payload, signature = manifest_fixture.signed(manifest)
        documents = {"https://example.invalid/m": payload,
                     "https://example.invalid/s": signature}
        assets += [
            {"name": rm.MANIFEST_ASSET, "browser_download_url": "https://example.invalid/m"},
            {"name": rm.SIGNATURE_ASSET, "browser_download_url": "https://example.invalid/s"},
        ]
    return {"tag_name": tag, "assets": assets}, (lambda url: documents[url])


def test_a_release_old_enough_to_predate_manifests_may_have_none():
    release, fetch = _release("v0.8.9")
    assert rm.fetch_manifest(release, fetch, tag="v0.8.9") is None


def test_a_release_that_should_carry_a_manifest_and_does_not_is_refused():
    release, fetch = _release(rm.MANIFEST_REQUIRED_FROM)
    with pytest.raises(rm.ManifestError, match="no signed manifest"):
        rm.fetch_manifest(release, fetch, tag=rm.MANIFEST_REQUIRED_FROM)


def test_the_transition_is_pinned_to_a_version_not_a_preference():
    assert rm.signature_required_for(rm.MANIFEST_REQUIRED_FROM) is True
    assert rm.signature_required_for("0.8.9") is False
    assert rm.signature_required_for("v99.0.0") is True


def test_a_valid_manifest_for_a_different_release_is_refused():
    """A genuine signature is not a statement about where it was found."""

    release, fetch = _release("v9.9.9", manifest=a_manifest(version="9.9.8"))
    with pytest.raises(rm.ManifestError, match="describes"):
        rm.fetch_manifest(release, fetch, tag="v9.9.9")


# --- What a verified manifest is allowed to decide ----------------------


def test_the_signed_digest_beats_the_release_apis_own_digest():
    """The whole point: a lying listing cannot substitute its own file."""

    blob = b"the enclosure package"
    manifest = a_manifest()
    honest = rm.expected_digest(manifest, "PiTrac-Easy-Connect-9.9.9.pyz")
    lie = "b" * 64
    release = {"tag_name": "v9.9.9", "assets": [
        {"name": "PiTrac-Easy-Connect-9.9.9.pyz",
         "browser_download_url": "https://example.invalid/a.pyz",
         "digest": "sha256:" + lie},
    ]}
    assert ArchiveUpdater._archive_digest(release, "v9.9.9") == lie
    assert ArchiveUpdater._archive_digest(release, "v9.9.9", manifest=manifest) == honest
    assert honest != lie
    import hashlib
    assert honest == hashlib.sha256(blob).hexdigest()


@pytest.mark.parametrize("version,system,machine,expected", [
    ("0.8.0", "Darwin", "arm64", None),
    ("0.8.0", "Darwin", "riscv64", "does not publish a build"),
    ("0.0.9", "Darwin", "arm64", "can only be installed over"),
])
def test_a_desktop_is_told_exactly_why_it_may_not_take_a_release(
    version, system, machine, expected
):
    manifest = manifest_fixture.manifest_for(
        {"PiTrac-Easy-Connect-macos-apple-silicon.zip": b"mac build"},
        version="9.9.9", pi_asset="p.pyz",
    )
    manifest["minimumCompatible"] = {"desktop": "0.7.0", "piService": "0.7.0"}
    refusal = rm.check_desktop_supported(
        manifest, version=version, system=system, machine=machine
    )
    if expected is None:
        assert refusal is None
    else:
        assert refusal and expected in refusal


@pytest.mark.parametrize("kwargs,expected", [
    ({"version": "0.8.0", "python_version": "3.11"}, None),
    ({"version": "0.8.0", "python_version": "3.8"}, "needs Python 3.9"),
    ({"version": "0.1.0", "python_version": "3.11"}, "can only be installed over"),
    ({"version": "0.8.0", "python_version": "3.11", "model": "Raspberry Pi 3 Model B"},
     "not published for"),
])
def test_an_enclosure_is_told_exactly_why_it_may_not_take_a_release(kwargs, expected):
    manifest = a_manifest()
    manifest["minimumCompatible"] = {"desktop": "0.7.0", "piService": "0.7.0"}
    refusal = rm.check_pi_supported(manifest, **kwargs)
    if expected is None:
        assert refusal is None
    else:
        assert refusal and expected in refusal


def test_an_unreadable_pi_model_is_not_treated_as_an_unsupported_one():
    """Bricking updates on a board we cannot identify is the worse failure."""

    manifest = a_manifest()
    assert rm.check_pi_supported(
        manifest, version="0.8.0", python_version="3.11", model="",
    ) is None


# --- The release tooling agrees with the applications -------------------


def test_the_workflow_writes_what_the_applications_require(tmp_path):
    """One generator, one verifier, checked against each other."""

    import importlib.util
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    dist = tmp_path / "dist"
    dist.mkdir()
    names = [platform["asset"] for platform in rm.DESKTOP_PLATFORMS]
    for name in names:
        (dist / name).write_bytes(b"pretend " + name.encode())
    pi_asset = dist / "PiTrac-Easy-Connect-9.9.9.pyz"
    pi_asset.write_bytes(b"pretend enclosure package")

    out = dist / rm.MANIFEST_ASSET
    arguments = [
        sys.executable, str(root / "packaging" / "write-release-manifest.py"),
        "--out", str(out), "--version", "9.9.9", "--tag", "v9.9.9",
        "--signing-key-id", manifest_fixture.key_id(),
        "--pi-asset", str(pi_asset),
    ]
    for name in names:
        arguments += ["--asset", str(dist / name)]
    done = subprocess.run(arguments, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr

    payload = out.read_bytes()
    signature = base64.b64encode(manifest_fixture.sign(payload))
    manifest = rm.verify_manifest(payload, signature)

    # Everything the applications read out of it is present and correct.
    assert rm.declared_tag(manifest) == "v9.9.9"
    for name in names:
        assert rm.expected_size(manifest, name) == (dist / name).stat().st_size
    for platform in rm.DESKTOP_PLATFORMS:
        assert rm.desktop_asset_for(
            manifest, platform["system"], platform["machine"]
        ) == platform["asset"]
    assert rm.check_pi_supported(
        manifest, version="9.9.9", python_version="3.11",
        model="Raspberry Pi 5 Model B", os_name="Raspberry Pi OS",
    ) is None


def test_release_tools_skip_macos_libressl_for_modern_openssl(monkeypatch):
    """The default /usr/bin/openssl on macOS cannot sign Ed25519 releases."""

    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "packaging" / "openssl_tools.py"
    spec = importlib.util.spec_from_file_location("openssl_tools_test", path)
    tools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tools)
    monkeypatch.setattr(
        tools, "candidates", lambda _explicit=None: iter(("/usr/bin/openssl", "/modern"))
    )

    class Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    monkeypatch.setattr(
        tools.subprocess, "run",
        lambda command, **_kwargs: Result(
            "LibreSSL 3.3.6" if command[0] == "/usr/bin/openssl"
            else "OpenSSL 3.6.3"
        ),
    )
    assert tools.command() == "/modern"

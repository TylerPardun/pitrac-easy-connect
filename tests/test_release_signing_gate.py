"""Release completeness and platform-signing notes from what CI reported.

Each platform build writes one honest record of whether it actually signed
itself (packaging/write-signing-status.py). release-signing-gate.py reads
whatever landed in the downloaded-artifacts directory. Missing reports remain
a release blocker; an honest unsigned report does not, because certificates
are optional and first-launch warnings are documented.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    path = ROOT / "packaging" / "{}.py".format(name.replace("_", "-"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load("release_signing_gate")
status_writer = _load("write_signing_status")


def write_status(directory, platform, *, signed, notarized=False, detail="x"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "signing-status-{}.json".format(platform)).write_text(
        json.dumps({
            "platform": platform, "signed": signed, "notarized": notarized,
            "detail": detail,
        }), encoding="utf-8",
    )


ALL_THREE = ("macos-apple-silicon", "macos-intel", "windows")


def test_every_platform_signed_and_macos_notarized_is_final(tmp_path):
    for platform in ("macos-apple-silicon", "macos-intel"):
        write_status(tmp_path / platform, platform, signed=True, notarized=True)
    write_status(tmp_path / "windows", "windows", signed=True)

    result = gate.decide(gate.gather(tmp_path))

    assert result["fullySigned"] is True
    assert result["prerelease"] is False
    assert "signed" in result["notes"].lower()


@pytest.mark.parametrize("missing", ALL_THREE)
def test_any_missing_platform_status_refuses_final(tmp_path, missing):
    for platform in ALL_THREE:
        if platform == missing:
            continue
        write_status(
            tmp_path / platform, platform, signed=True,
            notarized=platform.startswith("macos"),
        )

    result = gate.decide(gate.gather(tmp_path))

    assert result["fullySigned"] is False
    assert result["prerelease"] is True
    assert missing in result["notes"]


def test_a_platform_reporting_unsigned_is_final_with_a_warning(tmp_path):
    write_status(tmp_path / "macos-apple-silicon", "macos-apple-silicon",
                signed=True, notarized=True)
    write_status(tmp_path / "macos-intel", "macos-intel", signed=True, notarized=True)
    write_status(tmp_path / "windows", "windows", signed=False,
                detail="no WINDOWS_SIGNING_CERTIFICATE_PFX secret is configured; unsigned")

    result = gate.decide(gate.gather(tmp_path))

    assert result["fullySigned"] is False
    assert result["prerelease"] is False
    assert "unsigned" in result["notes"]
    assert "stable release" in result["notes"]


def test_signed_but_not_notarized_macos_is_final_with_a_warning(tmp_path):
    """A partial platform signature must be described without blocking files."""

    write_status(tmp_path / "macos-apple-silicon", "macos-apple-silicon",
                signed=True, notarized=False,
                detail="signed but no AC_NOTARY_KEY_P8 secret is configured")
    write_status(tmp_path / "macos-intel", "macos-intel", signed=True, notarized=True)
    write_status(tmp_path / "windows", "windows", signed=True)

    result = gate.decide(gate.gather(tmp_path))

    assert result["fullySigned"] is False
    assert result["prerelease"] is False
    assert "macos-apple-silicon" in result["notes"]


def test_an_empty_status_directory_refuses_final(tmp_path):
    result = gate.decide(gate.gather(tmp_path))
    assert result["fullySigned"] is False
    assert all(name in result["notes"] for name in ALL_THREE)


def test_a_corrupt_status_file_is_not_counted_as_present(tmp_path):
    directory = tmp_path / "macos-apple-silicon"
    directory.mkdir()
    (directory / "signing-status-macos-apple-silicon.json").write_text("{ not json")
    write_status(tmp_path / "macos-intel", "macos-intel", signed=True, notarized=True)
    write_status(tmp_path / "windows", "windows", signed=True)

    result = gate.decide(gate.gather(tmp_path))

    assert result["fullySigned"] is False
    assert "macos-apple-silicon" in result["notes"]


def test_gather_reads_nested_download_artifact_layout(tmp_path):
    """actions/download-artifact nests every artifact under its own name."""

    write_status(
        tmp_path / "signing-status-PiTrac-windows", "windows", signed=True,
    )
    found = gate.gather(tmp_path)
    assert "windows" in found


def test_write_signing_status_refuses_notarized_without_signed(tmp_path):
    done = subprocess.run(
        [sys.executable, str(ROOT / "packaging" / "write-signing-status.py"),
         "--out", str(tmp_path / "x.json"), "--platform", "windows",
         "--signed", "false", "--notarized", "true", "--detail", "x"],
        capture_output=True, text=True,
    )
    assert done.returncode != 0
    assert not (tmp_path / "x.json").exists()


def test_write_signing_status_produces_what_the_gate_reads(tmp_path):
    out = tmp_path / "status" / "signing-status-macos-intel.json"
    done = subprocess.run(
        [sys.executable, str(ROOT / "packaging" / "write-signing-status.py"),
         "--out", str(out), "--platform", "macos-intel",
         "--signed", "true", "--notarized", "true", "--detail", "signed and stapled"],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    value = json.loads(out.read_text())
    assert value == {
        "platform": "macos-intel", "signed": True, "notarized": True,
        "detail": "signed and stapled",
    }
    result = gate.decide(gate.gather(tmp_path))
    assert "macos-intel" in result["statuses"]


def test_the_workflow_labels_releases_from_reported_platform_status(tmp_path):
    """The wiring itself: the release job must not hardcode completeness."""

    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text()
    assert "release-signing-gate.py" in workflow
    assert "prerelease: ${{ env.PRERELEASE }}" in workflow
    # Each platform build has to actually produce what the gate reads.
    for step in (
        "write-signing-status.py", "signing-status-${{ matrix.artifact }}",
    ):
        assert step in workflow


def test_the_entitlements_file_is_the_narrow_shape_pyinstaller_needs(tmp_path):
    import plistlib

    raw = (ROOT / "packaging" / "entitlements.plist").read_bytes()
    value = plistlib.loads(raw)
    for required in (
        "com.apple.security.cs.allow-jit",
        "com.apple.security.cs.disable-library-validation",
    ):
        assert value.get(required) is True
    # Only distribution-signing keys -- nothing that grants the app a
    # capability it did not already have.
    for absent_key in (
        "com.apple.security.device.camera",
        "com.apple.security.device.microphone",
        "com.apple.security.app-sandbox",
    ):
        assert absent_key not in value

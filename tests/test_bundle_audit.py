"""The build refuses to ship a component NOTICE.md does not credit.

The macOS build passed this for months while the Windows build could not,
because the audit read manifests as if every path used forward slashes and
every shared library carried its version the way a .dylib does. These use a
manifest shaped the way PyInstaller writes one on Windows.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "packaging" / "bundled-licences.py"


@pytest.fixture
def audit(tmp_path):
    spec = importlib.util.spec_from_file_location("bundled_licences", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    module.TOC = tmp_path / "Analysis-00.toc"
    module.NOTICE = tmp_path / "NOTICE.md"
    module.NOTICE.write_text("| Component | License |\n|---|---|\n")
    return module


def manifest(*entries):
    return "(" + ", ".join(
        "('{}', '/wherever/{}', '{}')".format(name, name, kind) for name, kind in entries
    ) + ")"


def test_a_windows_path_reduces_to_its_package(audit):
    audit.TOC.write_text(manifest(
        (r"webview\lib\runtimes\win-x64\native\WebView2Loader", "BINARY"),
        (r"clr_loader\ffi\dlls\amd64\ClrLoader", "BINARY"),
        (r"pythonnet\runtime\Python.Runtime", "BINARY"),
    ))
    found = audit.bundled()
    assert "WebView2" in found
    assert found["pythonnet"] == 2, "clr_loader and pythonnet are credited together"


def test_a_versioned_dll_is_the_same_component_as_its_dylib(audit):
    audit.TOC.write_text(manifest(
        ("libssl-3", "BINARY"), ("libcrypto-3", "BINARY"), ("libffi-8", "BINARY"),
    ))
    found = audit.bundled()
    assert found["OpenSSL"] == 2
    assert found["libffi"] == 1


def test_the_interpreter_is_not_a_third_party_package(audit):
    audit.TOC.write_text(manifest(("python313", "BINARY")))
    assert list(audit.bundled()) == ["CPython"]


def test_the_microsoft_runtime_is_credited_once_not_forty_times(audit):
    audit.TOC.write_text(manifest(
        ("api-ms-win-crt-stdio-l1-1-0", "BINARY"),
        ("api-ms-win-core-file-l1-1-0", "BINARY"),
        ("VCRUNTIME140", "BINARY"), ("VCRUNTIME140_1", "BINARY"),
        ("ucrtbase", "BINARY"),
    ))
    found = audit.bundled()
    assert list(found) == ["Microsoft C runtime"]
    # Folded into one entry, but never dropped: it still has to be credited.
    assert found["Microsoft C runtime"] == 5


def test_a_name_mentioned_only_in_prose_is_not_credit(audit):
    audit.NOTICE.write_text(
        "See packaging/bundled-licences.py for details.\n\n"
        "| Component | License |\n|---|---|\n| CPython | PSF-2.0 |\n"
    )
    audit.TOC.write_text(manifest(("packaging", "PYMODULE")))
    assert "packaging" not in audit.credited()


def test_an_uncredited_package_fails_the_check(audit, monkeypatch, capsys):
    audit.TOC.write_text(manifest(("somebodyelsescode", "PYMODULE")))
    monkeypatch.setattr(audit.sys, "argv", ["bundled-licences.py", "--check"])
    assert audit.main() == 1
    assert "somebodyelsescode" in capsys.readouterr().out


def test_a_credited_package_passes_the_check(audit, monkeypatch):
    audit.NOTICE.write_text("| Component | License |\n|---|---|\n| pywebview | BSD-3-Clause |\n")
    audit.TOC.write_text(manifest(("webview", "PYMODULE")))
    monkeypatch.setattr(audit.sys, "argv", ["bundled-licences.py", "--check"])
    assert audit.main() == 0


def test_a_check_with_no_build_to_read_is_a_failure(audit, monkeypatch):
    monkeypatch.setattr(audit.sys, "argv", ["bundled-licences.py", "--check"])
    assert audit.main() == 1

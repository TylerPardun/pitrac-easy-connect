"""The SBOM lists what a build actually contains, or it refuses to write one.

write-sbom.py reuses bundled-licences.py's own PyInstaller-manifest reader --
the same one that gates NOTICE.md completeness in CI -- rather than a second,
independent enumeration that could quietly drift from it. These tests exercise
that reuse directly, with a synthetic manifest and NOTICE.md, the same pattern
test_bundle_audit.py uses for the reader itself.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "packaging" / "write-sbom.py"


@pytest.fixture
def sbom_writer(tmp_path):
    spec = importlib.util.spec_from_file_location("write_sbom", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.bundled_licences.ROOT = tmp_path
    module.bundled_licences.TOC = tmp_path / "Analysis-00.toc"
    module.bundled_licences.NOTICE = tmp_path / "NOTICE.md"
    return module, tmp_path


def manifest(*entries):
    return "(" + ", ".join(
        "('{}', '/wherever/{}', '{}')".format(name, name, kind) for name, kind in entries
    ) + ")"


def write_toc(tmp_path, text):
    (tmp_path / "Analysis-00.toc").write_text(text)


def write_notice(tmp_path, *names):
    rows = "\n".join("| {} | MIT |".format(name) for name in names)
    (tmp_path / "NOTICE.md").write_text("| Component | License |\n|---|---|\n" + rows + "\n")


def test_the_sbom_lists_exactly_what_the_manifest_says_is_bundled(sbom_writer):
    module, tmp_path = sbom_writer
    write_toc(tmp_path, manifest(("psutil", "PYMODULE"), ("certifi", "PYMODULE")))
    write_notice(tmp_path, "psutil", "certifi")

    sbom = module.build_sbom(
        toc=tmp_path / "Analysis-00.toc", component_name="PiTrac Easy-Connect",
        component_version="0.9.0", platform="macos-intel",
    )

    names = {component["name"] for component in sbom["components"]}
    assert names == {"psutil", "certifi"}
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["metadata"]["component"]["version"] == "0.9.0"


def test_the_sbom_refuses_to_write_when_notice_disagrees(sbom_writer):
    """The exact drift this exists to prevent: a component shipped, credited
    nowhere -- caught before the SBOM can misrepresent it as accounted for."""

    module, tmp_path = sbom_writer
    write_toc(tmp_path, manifest(("mystery_package", "PYMODULE")))
    write_notice(tmp_path, "some-other-thing")

    with pytest.raises(SystemExit, match="mystery_package"):
        module.build_sbom(
            toc=tmp_path / "Analysis-00.toc", component_name="PiTrac Easy-Connect",
            component_version="0.9.0", platform="windows",
        )


def test_the_sbom_carries_a_version_for_an_installed_distribution(sbom_writer):
    module, tmp_path = sbom_writer
    # packaging is a declared test dependency, so this remains a real
    # installed-distribution assertion even in the minimal isolated test
    # environment. psutil belongs to the desktop build extra and is not
    # installed merely to run the suite.
    write_toc(tmp_path, manifest(("packaging", "PYMODULE")))
    write_notice(tmp_path, "packaging")

    sbom = module.build_sbom(
        toc=tmp_path / "Analysis-00.toc", component_name="PiTrac Easy-Connect",
        component_version="0.9.0", platform="macos-apple-silicon",
    )

    packaging_component = next(
        c for c in sbom["components"] if c["name"] == "packaging"
    )
    assert packaging_component["version"] != "unknown"


def test_a_component_with_no_installed_distribution_is_marked_unknown_not_guessed(
    sbom_writer,
):
    """The Microsoft C runtime and CPython itself are not Python
    distributions; claiming a version for them would be inventing one."""

    module, tmp_path = sbom_writer
    write_toc(tmp_path, manifest(("api-ms-win-core-file-l1-1-0", "BINARY")))
    write_notice(tmp_path, "microsoft c runtime")

    sbom = module.build_sbom(
        toc=tmp_path / "Analysis-00.toc", component_name="PiTrac Easy-Connect",
        component_version="0.9.0", platform="windows",
    )

    assert len(sbom["components"]) == 1
    assert sbom["components"][0]["version"] == "unknown"


def test_the_cli_writes_readable_json_and_reports_the_component_count(
    sbom_writer, capsys,
):
    module, tmp_path = sbom_writer
    write_toc(tmp_path, manifest(("psutil", "PYMODULE")))
    write_notice(tmp_path, "psutil")
    out = tmp_path / "sbom.json"

    code = module.main([
        "--out", str(out), "--toc", str(tmp_path / "Analysis-00.toc"),
        "--component-name", "PiTrac Easy-Connect", "--component-version", "0.9.0",
        "--platform", "macos-intel",
    ])

    assert code == 0
    value = json.loads(out.read_text())
    assert value["components"][0]["name"] == "psutil"
    assert "1 components" in capsys.readouterr().out


def test_the_cli_refuses_when_the_manifest_does_not_exist(sbom_writer):
    module, tmp_path = sbom_writer
    with pytest.raises(SystemExit, match="build first"):
        module.main([
            "--out", str(tmp_path / "sbom.json"), "--toc", str(tmp_path / "missing.toc"),
            "--component-name", "PiTrac Easy-Connect", "--component-version", "0.9.0",
            "--platform", "windows",
        ])


def test_the_real_notice_and_a_real_installed_component_agree(tmp_path):
    """One real end-to-end pass, against this repository's own NOTICE.md,
    with no monkeypatching -- proves the reuse actually points at the real
    files in normal operation, not only in the redirected fixture above."""

    spec = importlib.util.spec_from_file_location("write_sbom", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    toc = tmp_path / "Analysis-00.toc"
    toc.write_text(manifest(("psutil", "PYMODULE")))
    sbom = module.build_sbom(
        toc=toc, component_name="PiTrac Easy-Connect", component_version="0.9.0",
        platform="macos-apple-silicon",
    )
    assert sbom["components"][0]["name"] == "psutil"


def test_the_workflow_writes_and_publishes_an_sbom_per_platform():
    """The wiring itself: three platforms in, three SBOMs published."""

    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text()
    assert "write-sbom.py" in workflow
    assert "sbomPlatform: windows" in workflow
    assert "sbomPlatform: macos-apple-silicon" in workflow
    assert "sbomPlatform: macos-intel" in workflow
    assert "sbom-${{ matrix.artifact }}" in workflow
    assert "release/sbom-*.json" in workflow, "SBOMs are gathered into the release directory"

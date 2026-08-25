"""What is shipped, and the shape it is shipped in.

Two decisions are pinned here.

**Windows is onedir.** It used to be a single self-contained .exe, which runs
perfectly well after being dragged out of the folder it shipped in -- and then
its "installation" is whatever folder it was dropped into. The updater refuses
to replace that, correctly: replacing somebody's Desktop is not an
installation step, and the field report was exactly "Desktop is a user folder,
not an application install". A onedir executable cannot be moved on its own,
so the install root is always the dedicated folder the updater requires and
macOS already had.

**Linux is not distributed.** It cannot be tested here, so it is not shipped.
The Linux *code paths* stay: this suite builds its fixtures with
system="Linux", and the Raspberry Pi service is Linux. Only the desktop
download is gone.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / "packaging" / "PiTrac-Easy-Connect.spec").read_text()
WORKFLOW = (ROOT / "workflows.marker") if False else (ROOT / ".github" / "workflows" / "build.yml")
FLOW = WORKFLOW.read_text()


def test_windows_is_built_as_a_directory_not_a_loose_executable():
    """A lone .exe can leave its folder; a onedir build cannot."""

    branch = SPEC.split("else:", 1)[1]
    assert "exclude_binaries=True" in branch, (
        "the non-macOS build still bundles everything into one executable, so it "
        "can be dragged out of its folder and have no install root"
    )
    assert branch.count("COLLECT(") == 1, "the non-macOS build does not collect a directory"


def test_both_platforms_produce_a_directory_named_for_the_app():
    """validate_install_root requires the root to carry the app's name."""

    from pitrac_easy_connect.companion.self_update import APP_NAME

    assert SPEC.count('name="{}"'.format(APP_NAME)) >= 2, (
        "each platform's collected directory must be named {}".format(APP_NAME)
    )


def test_the_updater_helper_stays_a_single_file():
    """It is copied out of the install with copy2, one file at a time."""

    helper_spec = (ROOT / "packaging" / "PiTrac-Updater.spec").read_text()
    assert "COLLECT(" not in helper_spec, (
        "the helper became a directory; prepare_transaction copies it as one file"
    )
    assert "exclude_binaries=True" not in helper_spec


@pytest.mark.parametrize("artifact", [
    "PiTrac-Easy-Connect-macos-apple-silicon.zip",
    "PiTrac-Easy-Connect-macos-intel.zip",
    "PiTrac-Easy-Connect-windows.zip",
])
def test_the_shipped_platforms_are_built_and_expected(artifact):
    assert artifact in FLOW, "{} is not built".format(artifact)


def test_linux_is_not_distributed():
    """It cannot be tested here, so it is not shipped."""

    assert "PiTrac-Easy-Connect-linux" not in FLOW, "a Linux desktop build is still produced"
    site = (ROOT / "site" / "index.html").read_text()
    assert "linux" not in site.lower(), "the download page still offers Linux"
    readme = (ROOT / "README.md").read_text()
    assert "Linux" not in readme, "the README still offers Linux"


def test_the_linux_code_paths_are_kept():
    """The tests build their fixtures on it, and the enclosure runs it."""

    from pitrac_easy_connect.companion import self_update

    assert self_update._platform_name(system="Linux") == "linux"
    root = Path("/tmp/PiTrac Easy-Connect")
    assert self_update.executable_path(root, system="Linux").name == self_update.APP_NAME


def test_the_release_expects_exactly_what_is_built():
    """A missing asset should fail the release, not ship quietly."""

    expected = FLOW.split("EXPECTED=(", 1)[1].split(")", 1)[0]
    assert "linux" not in expected.lower()
    for artifact in ("macos-apple-silicon", "macos-intel", "windows"):
        assert artifact in expected, "{} is not required at release time".format(artifact)

"""What is shipped, and the shape it is shipped in.

Two decisions are pinned here.

**Windows is onefile inside an installed directory.** The installer creates the
dedicated directory the updater requires. The main executable itself remains
self-contained because users move apparent application files. An onedir build
then dies in PyInstaller before our code can help, with "Failed to load Python
DLL" because its `_internal` directory stayed behind.

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


def test_windows_main_executable_is_self_contained():
    """Moving the visible executable must not strand its Python runtime."""

    branch = SPEC.split("else:", 1)[1]
    assert "exclude_binaries=True" not in branch, (
        "the Windows bootloader depends on a separate _internal directory and "
        "will fail before the application can explain a broken installation"
    )
    assert "analysis.binaries" in branch
    assert "analysis.datas" in branch
    assert "COLLECT(" not in branch


def test_windows_package_still_has_a_directory_named_for_the_app():
    """The installer/updater root is separate from PyInstaller's shape."""

    from pitrac_easy_connect.companion.self_update import APP_NAME

    assert '$root = "dist/payload/{}"'.format(APP_NAME) in FLOW


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


# --- The Windows installer -------------------------------------------------


def test_windows_ships_an_installer():
    """The installer provides the updater and supported application root."""

    assert "PiTrac-Easy-Connect-windows-setup.exe" in FLOW, "no installer is built"
    assert "windows-installer.iss" in FLOW, "the installer script is not used"
    script = (ROOT / "packaging" / "windows-installer.iss")
    assert script.is_file()


def test_the_installer_needs_no_administrator():
    """Elevation on install is a nuisance; elevation on every update is worse.

    A per-user install means the running application can replace its own
    directory without a prompt, which is the whole point of it being there.
    """

    script = (ROOT / "packaging" / "windows-installer.iss").read_text()
    assert "PrivilegesRequired=lowest" in script
    assert "{localappdata}" in script


def test_the_installed_directory_is_named_for_the_app():
    """validate_install_root refuses a root that is not."""

    from pitrac_easy_connect.companion.self_update import APP_NAME

    script = (ROOT / "packaging" / "windows-installer.iss").read_text()
    default = [l for l in script.splitlines() if l.startswith("DefaultDirName=")][0]
    assert default.rstrip().endswith(APP_NAME), (
        "the install directory does not end with {}, so updating would refuse "
        "it: {}".format(APP_NAME, default)
    )


def test_the_installer_does_not_invite_a_desktop_folder_install():
    """The app belongs in its fixed per-user program directory."""

    script = (ROOT / "packaging" / "windows-installer.iss").read_text()
    assert "DisableDirPage=yes" in script


def test_the_installer_creates_a_desktop_shortcut_by_default():
    """Users should move a shortcut, never the installed executable."""

    script = (ROOT / "packaging" / "windows-installer.iss").read_text()
    task = next(line for line in script.splitlines() if line.startswith('Name: "desktopicon"'))
    assert "unchecked" not in task


def test_windows_package_explains_which_download_is_for_people():
    guidance = ROOT / "packaging" / "WINDOWS-INSTALLATION.txt"
    assert guidance.is_file()
    text = guidance.read_text()
    assert "windows-setup.exe" in text
    assert "windows.zip" in text
    assert "not the Windows installer" in text
    assert "WINDOWS-INSTALLATION.txt" in FLOW


def test_the_installer_has_a_fixed_identity():
    """A changing AppId installs beside the old copy instead of replacing it."""

    script = (ROOT / "packaging" / "windows-installer.iss").read_text()
    assert "AppId=" in script and "Never change this" in script


def test_the_zip_is_still_published_because_the_updater_needs_it():
    """The updater downloads the zip by name; an installer cannot replace it."""

    from pitrac_easy_connect.common import updates

    wanted = updates.PLATFORM_ASSET_NAMES[("Windows", "x86_64")]
    assert wanted.endswith(".zip"), wanted
    assert wanted in FLOW, "the asset the updater downloads is no longer built"
    expected = FLOW.split("EXPECTED=(", 1)[1].split(")", 1)[0]
    assert wanted in expected, "the updater's asset is not required at release time"


def test_ci_installs_the_installer_and_checks_the_result():
    """Building an installer proves nothing about what it installs."""

    assert "/VERYSILENT" in FLOW, "the installer is never actually run"
    assert "validate_install_root" in FLOW, (
        "what the installer produced is never put through the updater's own check"
    )


def test_release_labels_separate_the_installer_from_the_updater_payload():
    assert "Windows installer - download this" in FLOW
    assert "Internal automatic-update payload - do not download manually" in FLOW

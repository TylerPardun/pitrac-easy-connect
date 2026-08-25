"""What the packaged builds are allowed to leave out.

The spec excludes packages to keep the download small and to avoid shipping
licences the project does not want to carry. Excluding one that pywebview
imports does not produce a smaller app, it produces an app with no window:
``import webview`` raises, the failure is caught, and every packaged build
quietly opens a browser instead. That shipped, in three releases, on every
platform, and nothing here noticed.

These tests read the spec rather than the built app, so they run everywhere
and cost nothing.
"""

import ast
import pathlib

import pytest

SPEC = pathlib.Path(__file__).resolve().parent.parent / "packaging" / "PiTrac-Easy-Connect.spec"

#: Imported by pywebview itself, not by anything this project calls directly.
#: webview/__init__.py imports webview.http unconditionally, and that module
#: imports bottle at the top, so the window backend cannot load without it.
NEEDED_BY_THE_WINDOW = {"bottle"}


def excludes_in_the_spec():
    """The excludes list, read out of the spec as data."""

    tree = ast.parse(SPEC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "excludes":
            return {
                element.value for element in node.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    raise AssertionError("the spec has no excludes list any more")


def test_the_spec_still_has_an_excludes_list():
    found = excludes_in_the_spec()
    assert found, "nothing is excluded, which means this test proves nothing"


@pytest.mark.parametrize("module", sorted(NEEDED_BY_THE_WINDOW))
def test_the_build_does_not_exclude_what_the_window_needs(module):
    assert module not in excludes_in_the_spec(), (
        "{} is excluded, so `import webview` will raise in the packaged app and "
        "every build will fall back to a browser".format(module)
    )


def test_the_window_backend_is_named_for_both_platforms():
    """PyInstaller cannot see a backend chosen at runtime."""

    source = SPEC.read_text()
    assert "webview.platforms.cocoa" in source
    assert "webview.platforms.edgechromium" in source


def test_linux_freezes_the_glib_override_used_by_pywebview():
    """Raw GLib expects priority first; pywebview uses the override API."""

    source = SPEC.read_text()
    assert '"webview.platforms.gtk"' in source
    assert '"gi.repository.GLib"' in source
    assert '"gi.overrides.GLib"' in source
    assert '"gi.repository.Gtk"' in source
    assert '"gi.repository.WebKit2"' in source


def test_macos_uses_the_supported_onedir_bundle_shape():
    source = SPEC.read_text()
    mac = source.split("if MACOS:", 1)[1].split("else:", 1)[0]
    assert "exclude_binaries=True" in mac
    assert "COLLECT(" in mac
    assert "BUNDLE(" in mac
    assert "BUNDLE(\n        collected" in mac
    assert '"LSMultipleInstancesProhibited": True' in mac
    assert '"NSLocalNetworkUsageDescription"' in mac
    assert '"NSAllowsLocalNetworking": True' in mac


def test_windows_ships_as_a_directory_like_macos():
    """Reversed deliberately. This used to require the opposite.

    A single self-contained .exe runs after being dragged out of the folder it
    shipped in, and then its install root is whatever folder it landed in --
    so the updater refused to replace it, which is right: replacing somebody's
    Desktop is not an installation step. The field report was exactly "Desktop
    is a user folder, not an application install".

    A onedir executable cannot be moved on its own, so the install root is
    always the dedicated folder both the updater and macOS already require.
    The binaries and data still ship; they sit beside the executable now
    instead of inside it.
    """

    source = SPEC.read_text()
    other = source.split("else:", 1)[1]
    assert "exclude_binaries=True" in other, (
        "the Windows build is a single executable again, which can leave its "
        "folder and lose the install root the updater needs"
    )
    assert "analysis.binaries" in other
    assert "analysis.datas" in other
    assert "COLLECT(" in other

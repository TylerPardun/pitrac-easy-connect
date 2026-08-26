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


def test_the_spec_carries_no_linux_window_backend():
    """Linux desktop distribution was removed; replaces a test that pinned it.

    The GTK/gi hidden-imports below used to be required so a frozen Linux
    build's window backend would actually load: PyInstaller cannot see a
    backend pywebview selects at runtime, so leaving these out meant
    ``import webview`` raised on Linux the same way excluding bottle did on
    every platform (see the module docstring). Now that no Linux desktop
    build is published or tested (docs/distribution.md,
    test_distribution_shape.py), keeping them would silently commit to
    correctly bundling a target nothing here can verify. Removing them here
    is a deliberate decision to stop trying, not an oversight to guard
    against -- so this asserts the opposite of what the test it replaces did.
    """

    source = SPEC.read_text()
    for gone in (
        "LINUX", '"webview.platforms.gtk"', '"gi.repository.GLib"',
        '"gi.overrides.GLib"', '"gi.repository.Gtk"', '"gi.repository.WebKit2"',
    ):
        assert gone not in source, "{} still names a removed Linux desktop path".format(gone)


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


def test_windows_executable_contains_its_runtime():
    """The visible EXE must not depend on a sibling `_internal` directory.

    A real user moved the onedir EXE to the Desktop. PyInstaller then failed to
    load `_internal/python313.dll` before application code ran. The installer
    still supplies the dedicated update root; onefile makes this predictable
    user action non-fatal.
    """

    source = SPEC.read_text()
    other = source.split("else:", 1)[1]
    assert "exclude_binaries=True" not in other, (
        "the Windows executable depends on external PyInstaller binaries"
    )
    assert "analysis.binaries" in other
    assert "analysis.datas" in other
    assert "COLLECT(" not in other

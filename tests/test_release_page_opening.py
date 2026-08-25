"""Getting to the download page when the app cannot install it itself.

The update can be refused for good reasons -- an app running from a user
folder, a package layout it cannot verify -- and when that happens the only
route left is downloading the new version by hand. That route was: print the
address as text and offer a Copy button.

On macOS that was nothing to click and a copy that did not happen, because a
WKWebView without clipboard permission fails silently. The reported symptom
was "I am not able to click the link to download". There was no link.
"""

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from pitrac_easy_connect.common.updates import RELEASES_PAGE, REPOSITORY
from pitrac_easy_connect.companion.service import CompanionService


def _ok():
    """What a successful platform opener looks like."""

    class Done:
        returncode = 0
    return Done()


@pytest.fixture
def service(tmp_path):
    made = CompanionService(config_path=tmp_path / "companion.json", discovery_port=0,
                            search_seconds=0.05, research_seconds=0.05)
    yield made
    made.close()


def test_it_opens_this_projects_releases_page(service):
    with mock.patch("subprocess.run", return_value=_ok()) as opened:
        result = service.open_release_page()
    assert result["opened"] is True
    assert opened.call_args[0][0][-1] == RELEASES_PAGE.format(REPOSITORY)


def test_a_specific_release_is_allowed(service):
    exact = "https://github.com/{}/releases/tag/v0.5.0".format(REPOSITORY)
    with mock.patch("subprocess.run", return_value=_ok()) as opened:
        result = service.open_release_page(exact)
    assert opened.call_args[0][0][-1] == exact
    assert result["url"] == exact


@pytest.mark.parametrize("hostile", [
    "https://evil.example/steal",
    "https://github.com/someone-else/repo/releases/latest",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "https://github.com/TylerPardun/pitrac-easy-connect/issues",
])
def test_it_will_not_open_anything_else(service, hostile):
    """The page asking is the one an injected script would run in."""

    with mock.patch("subprocess.run", return_value=_ok()) as opened:
        result = service.open_release_page(hostile)
    assert opened.call_args[0][0][-1] == RELEASES_PAGE.format(REPOSITORY), (
        "it opened {} instead of this project's releases".format(opened.call_args[0][0][-1])
    )
    assert result["url"] != hostile


def test_a_browser_that_will_not_open_is_reported_not_raised(service):
    with mock.patch("subprocess.run", side_effect=OSError("no opener")):
        result = service.open_release_page()
    assert result["opened"] is False
    assert result["url"]


def test_the_page_asks_the_app_to_open_it_rather_than_printing_an_address():
    """The fix is only real if the page actually calls it."""

    from pitrac_easy_connect.companion.page import PAGE

    wiring = PAGE.split("function wireDesktopDownload(")[1].split("\nfunction ")[0]
    assert '"/api/open-release"' in wiring, (
        "the manual-download path still only prints an address"
    )


def test_the_route_exists():
    from pitrac_easy_connect.companion.web import CompanionHandler
    import inspect

    assert '"/api/open-release"' in inspect.getsource(CompanionHandler)


def test_it_uses_the_platform_opener_not_the_browser_module(service):
    """check-native-only.py forbids the standard browser launcher by name.

    That rule exists so this application's own interface can never end up in
    a browser tab, and pywebview is configured to refuse external links for
    the same reason. Sending someone to a download page is a different act --
    the operating system shows a web page and nothing of ours renders there --
    so it is done with the platform's own opener, and the rule stays as
    strict as it was.
    """

    import platform as platform_module

    with mock.patch("subprocess.run", return_value=_ok()) as ran:
        service.open_release_page()

    command = ran.call_args[0][0]
    expected_first = {"Darwin": "/usr/bin/open", "Windows": "cmd"}.get(
        platform_module.system(), "xdg-open"
    )
    assert command[0] == expected_first, command


def test_the_native_only_rule_still_forbids_the_browser_module():
    """If this ever passes trivially, the guard has been weakened."""

    rules = (Path(__file__).resolve().parent.parent
             / "packaging" / "check-native-only.py").read_text()
    for forbidden in ("webbrowser", "open_in_browser", "_blank"):
        assert forbidden in rules, "{} is no longer refused".format(forbidden)

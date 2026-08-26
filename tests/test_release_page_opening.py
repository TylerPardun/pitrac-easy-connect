"""The desktop manual-update fallback is local-file-only.

If automatic replacement is safely refused after download and verification,
the app may reveal its own retained package. Page code cannot provide a path
and no desktop code may hand a URL to a browser or operating-system opener.
"""

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

from pitrac_easy_connect.common.updates import DesktopUpdateState
from pitrac_easy_connect.companion.service import CompanionService


ROOT = Path(__file__).resolve().parent.parent


class _Done:
    returncode = 0


@pytest.fixture
def service(tmp_path, monkeypatch):
    state = tmp_path / "updates"
    state.mkdir()
    monkeypatch.setenv("PITRAC_UPDATE_STATE_DIR", str(state))
    made = CompanionService(
        config_path=tmp_path / "companion.json", discovery_port=0,
        search_seconds=0.05, research_seconds=0.05,
    )
    yield made, state
    made.close()


def _retain_verified_package(service, state):
    transaction = state / ("transaction-" + "a" * 32)
    transaction.mkdir()
    package = transaction / "PiTrac-Easy-Connect.zip"
    package.write_bytes(b"verified package")
    service._desktop_archive_path = package
    service._desktop_update_state = DesktopUpdateState.PREFLIGHT_FAILED
    return package


@pytest.mark.parametrize(
    "system,expected",
    [
        ("Darwin", lambda path: ["/usr/bin/open", "-R", str(path)]),
        ("Windows", lambda path: ["explorer.exe", "/select,{}".format(path)]),
    ],
)
def test_only_the_retained_verified_package_is_revealed(service, system, expected):
    made, state = service
    package = _retain_verified_package(made, state)
    with mock.patch("platform.system", return_value=system), mock.patch(
        "subprocess.run", return_value=_Done()
    ) as ran:
        result = made.reveal_downloaded_update()
    assert result == {
        "revealed": True,
        "path": str(package),
        "detail": "The verified update package is selected in your file manager.",
    }
    assert ran.call_args.args[0] == expected(package)
    assert ran.call_args.kwargs["check"] is False


def test_no_package_or_wrong_state_cannot_invoke_a_file_manager(service):
    made, state = service
    _retain_verified_package(made, state)
    made._desktop_update_state = DesktopUpdateState.VERIFY_FAILED
    with mock.patch("subprocess.run") as ran:
        result = made.reveal_downloaded_update()
    assert result["revealed"] is False
    assert result["path"] == ""
    ran.assert_not_called()


def test_a_path_outside_the_private_update_state_is_refused(service, tmp_path):
    made, _state = service
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"not backend-owned")
    made._desktop_archive_path = outside
    made._desktop_update_state = DesktopUpdateState.PREFLIGHT_FAILED
    with mock.patch("subprocess.run") as ran:
        result = made.reveal_downloaded_update()
    assert result["revealed"] is False
    assert result["path"] == str(outside)
    ran.assert_not_called()


def test_a_symlink_is_refused_even_when_it_points_inside_update_state(service):
    made, state = service
    package = _retain_verified_package(made, state)
    link = package.with_name("selected.zip")
    link.symlink_to(package)
    made._desktop_archive_path = link
    with mock.patch("subprocess.run") as ran:
        result = made.reveal_downloaded_update()
    assert result["revealed"] is False
    ran.assert_not_called()


def test_file_manager_failure_leaves_the_exact_local_path_visible(service):
    made, state = service
    package = _retain_verified_package(made, state)
    with mock.patch("platform.system", return_value="Darwin"), mock.patch(
        "subprocess.run", side_effect=OSError("Finder unavailable")
    ):
        result = made.reveal_downloaded_update()
    assert result["revealed"] is False
    assert result["path"] == str(package)
    assert "exact saved path" in result["detail"]


def test_the_page_and_route_accept_no_url_or_path():
    import inspect

    from pitrac_easy_connect.companion.page import PAGE
    from pitrac_easy_connect.companion.web import CompanionHandler

    wiring = PAGE.split("function wireDesktopDownload(", 1)[1].split("\nfunction ", 1)[0]
    routes = inspect.getsource(CompanionHandler)
    assert 'api("/api/update/reveal",{})' in wiring
    assert '"/api/update/reveal": lambda body: service.reveal_downloaded_update()' in routes
    assert "open-release" not in PAGE
    assert "open-release" not in routes
    assert list(inspect.signature(CompanionService.reveal_downloaded_update).parameters) == ["self"]


def _checker_module():
    path = ROOT / "packaging" / "check-native-only.py"
    spec = importlib.util.spec_from_file_location("native_only_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "source",
    [
        'subprocess.run(["/usr/bin/open", "https://example.invalid"])',
        'subprocess.run(["cmd", "/c", "start", "", url])',
        'subprocess.Popen(["xdg-open", url])',
        'os.startfile(url)',
        'ShellExecuteW(None, "open", url, None, None, 1)',
        'subprocess.run(["explorer.exe", url])',
        'subprocess.run(["powershell", "Start-Process", url])',
        'window.open("https://example.invalid")',
    ],
)
def test_native_only_checker_detects_low_level_url_openers(tmp_path, source):
    path = tmp_path / "bad.py"
    path.write_text(source, encoding="utf-8")
    assert _checker_module().scan([path]), source


def test_native_only_checker_allows_the_narrow_local_file_reveal():
    service_source = ROOT / "src" / "pitrac_easy_connect" / "companion" / "service.py"
    failures = _checker_module().scan([service_source])
    assert not failures, failures


def test_the_packaged_smoke_reaches_the_manual_path_before_judging_browsers():
    """Watching only startup would miss the one path that used to open one.

    The refused-automatic-install path is where a releases URL used to be
    handed to the operating system, so the packaged gate has to actually
    arrive there -- with a real download, a real verification and a real
    refusal -- and only then decide whether a browser appeared.
    """

    smoke = (ROOT / "packaging" / "packaged-update-smoke.py").read_text(encoding="utf-8")
    assert "manual_candidate.executable, args, environment, state, before_browsers" in smoke
    assert "--signing-key" in smoke
    assert "sign-release-manifest.py" in smoke
    leg = smoke.split("def _manual_update_leg(", 1)[1].split("\ndef ", 1)[0]
    for required in (
        'PITRAC_FAILURE_INJECT_PREFLIGHT',
        '"preflight-failed"',
        '"/api/update/reveal"',
        "_ordinary_browsers() - base_browsers",
    ):
        assert required in leg, "{} is not exercised by the manual-update leg".format(required)
    assert "savedPackagePath" in leg


def test_the_native_only_rule_still_forbids_the_browser_module():
    """If this ever passes trivially, the guard has been weakened."""

    rules = (ROOT / "packaging" / "check-native-only.py").read_text(encoding="utf-8")
    for forbidden in ("webbrowser", "open_in_browser", "_blank", "xdg-open", "ShellExecute"):
        assert forbidden in rules, "{} is no longer refused".format(forbidden)

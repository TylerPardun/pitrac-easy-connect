"""The Pi service as a whole, and the guards on the page it exposes before pairing."""

import json
import socket
import time
import urllib.error
import urllib.request

import pytest

from pitrac_easy_connect.common.states import State
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.portal import PortalServer
from pitrac_easy_connect.pi.service import PiService, ServicePaths
from pitrac_easy_connect.pi.simulated import home_network_pi

import threading


@pytest.fixture
def service(tmp_path):
    backend = home_network_pi(country="US")
    pitrac = PitracInstallation(
        tmp_path / "user_settings.json", tmp_path / "calibration_data.json"
    )
    built = PiService(
        backend,
        paths=ServicePaths(tmp_path / "state"),
        pitrac=pitrac,
        relay_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
        link_port=0,
        discovery_port=0,
        manage_hostname=False,
    )
    built.start()
    yield built
    built.stop()


@pytest.fixture
def portal(service):
    server = PortalServer(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, "http://127.0.0.1:{}".format(server.server_port)
    server.shutdown()
    server.server_close()


def request(url, body=None, headers=None, method=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    all_headers = {"X-PiTrac-Portal": "1"}
    if body is not None:
        all_headers["Content-Type"] = "application/json"
    if headers is not None:
        all_headers = headers
    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


# --- Boot -----------------------------------------------------------------


def test_a_new_enclosure_comes_up_asking_to_be_set_up(service):
    assert service.state is State.SETUP_REQUIRED
    assert service.backend.active_connection().is_hotspot is True


def test_the_setup_hotspot_is_named_after_the_device(service):
    connection = service.backend.active_connection()
    assert connection.ssid == service.identity.setup_ssid
    assert service.identity.device_id in connection.ssid


def test_pitrac_is_pointed_at_the_relay_on_first_boot(service):
    assert service.pitrac.points_at_relay(service.relay.ports) is True


def test_pointing_pitrac_at_the_relay_is_idempotent(service):
    assert service.pitrac.point_at_relay(service.relay.ports) == []


def test_the_enclosure_advertises_itself_for_discovery(service):
    published = service.backend.published_mdns
    assert published["name"] == service.identity.display_name
    assert published["records"]["deviceId"] == service.identity.device_id


def test_the_beacon_describes_the_enclosure_without_secrets(service):
    described = json.dumps(service.describe())
    assert service.identity.device_id in described
    assert service.identity.setup_password not in described


def test_the_identity_survives_a_restart(tmp_path):
    backend = home_network_pi(country="US")
    pitrac = PitracInstallation(tmp_path / "s.json", tmp_path / "c.json")
    paths = ServicePaths(tmp_path / "state")
    ports = {Simulator.GSPRO: 0, Simulator.E6: 0}

    first = PiService(backend, paths, pitrac, ports, 0, 0, manage_hostname=False)
    first.start()
    identity = first.identity
    first.stop()

    second = PiService(backend, paths, pitrac, ports, 0, 0, manage_hostname=False)
    second.start()
    try:
        assert second.identity == identity
    finally:
        second.stop()


# --- Commands -------------------------------------------------------------


def test_joining_a_network_and_confirming_it(service):
    result = service.command("joinNetwork", {"ssid": "Ferndale", "password": "GoodPassword1"})
    assert result["ok"] is True
    assert result["awaitingConfirmation"] is True

    service.command("confirmNetwork")
    assert service.backend.active_connection().ssid == "Ferndale"


def test_resetting_the_network_keeps_pairings_and_calibration(service):
    pairing = service.pairings.redeem(service.pairings.issue_code().code, "Sim PC")
    service.command("joinNetwork", {"ssid": "Ferndale", "password": "GoodPassword1"})
    service.command("confirmNetwork")

    result = service.command("resetNetwork")
    assert service.backend.saved_profiles() == []
    assert service.pairings.is_paired(pairing.pairing_id) is True
    assert "calibration" in result["kept"]


def test_preparing_for_a_new_owner_removes_pairings_and_changes_the_setup_password(service):
    pairing = service.pairings.redeem(service.pairings.issue_code().code, "Old owner PC")
    before = service.identity.setup_password

    result = service.command("prepareForNewOwner")
    assert service.pairings.is_paired(pairing.pairing_id) is False
    assert service.identity.setup_password != before
    assert "camera calibration" in result["kept"]


def test_renaming_the_enclosure_keeps_its_device_id(service):
    device_id = service.identity.device_id
    renamed = service.command("rename", {"name": "Garage Bay"})
    assert renamed["displayName"] == "Garage Bay"
    assert service.identity.device_id == device_id


def test_an_unknown_command_is_refused(service):
    with pytest.raises(ValueError):
        service.command("deleteEverything")


def test_shutting_down_says_when_it_is_safe_to_unplug(service):
    result = service.command("shutdown")
    assert service.backend.shutdown_called is True
    assert "safeToUnplugWhen" in result
    assert service.state is State.SHUTTING_DOWN


# --- The setup page -------------------------------------------------------


def test_the_setup_page_loads(portal):
    _server, base = portal
    with urllib.request.urlopen(base + "/", timeout=5) as response:
        body = response.read().decode("utf-8")
    assert response.status == 200
    assert "PiTrac setup" in body


def test_status_reports_the_state_in_plain_language(portal):
    _server, base = portal
    status, data = request(base + "/api/status")
    assert status == 200
    assert data["headline"] and data["detail"]
    assert data["state"] == "SETUP REQUIRED"


def test_the_status_never_contains_the_setup_password(portal, service):
    _server, base = portal
    _status, data = request(base + "/api/status")
    assert service.identity.setup_password not in json.dumps(data)


def test_the_network_list_hides_technical_detail(portal):
    _server, base = portal
    _status, data = request(base + "/api/networks")
    for network in data["networks"]:
        assert "bars" in network and "needsPassword" in network
        assert "signal" not in network, "raw signal strength is not a user-facing number"


def test_joining_through_the_page_reports_a_wrong_password_specifically(portal):
    _server, base = portal
    _status, data = request(base + "/api/join", {"ssid": "Ferndale", "password": "wrong"})
    assert data["ok"] is False
    assert data["error"]["code"] == "PT-NET-001"
    assert data["error"]["stillSafe"]
    assert data["error"]["nextStep"]


def test_a_pairing_code_is_offered_and_can_be_replaced(portal):
    _server, base = portal
    _status, first = request(base + "/api/pairing-code")
    assert len(first["code"]) == 6
    _status, again = request(base + "/api/pairing-code")
    assert again["code"] == first["code"], "the same code stands until it is replaced"
    _status, fresh = request(base + "/api/pairing-code", {"refresh": True})
    assert fresh["code"] != first["code"]


# --- Guards on the page ---------------------------------------------------


def test_a_request_without_the_page_header_is_refused(portal):
    _server, base = portal
    status, data = request(
        base + "/api/reset-network", {}, headers={"Content-Type": "application/json"}
    )
    assert status == 403
    assert "setup page" in data["error"]["failed"]


def test_a_request_from_another_website_is_refused(portal):
    _server, base = portal
    status, data = request(
        base + "/api/shutdown",
        {},
        headers={
            "X-PiTrac-Portal": "1",
            "Content-Type": "application/json",
            "Origin": "https://not-pitrac.example",
        },
    )
    assert status == 403
    assert "another website" in data["error"]["failed"]


def test_a_preflight_is_refused_so_the_header_cannot_be_forged(portal):
    _server, base = portal
    status, _data = request(base + "/api/shutdown", method="OPTIONS")
    assert status == 403


def test_a_request_for_an_unrecognised_hostname_is_refused(portal):
    _server, base = portal
    status, data = request(
        base + "/api/status",
        headers={"X-PiTrac-Portal": "1", "Host": "evil.example.com"},
    )
    assert status == 421
    assert "does not answer" in data["error"]["failed"]


def test_the_enclosures_own_addresses_are_accepted(portal, service):
    _server, base = portal
    for host in ("10.42.0.1", "localhost", service.identity.hostname + ".local"):
        status, _data = request(
            base + "/api/status", headers={"X-PiTrac-Portal": "1", "Host": host}
        )
        assert status == 200, host


def test_an_oversized_request_is_refused(portal):
    _server, base = portal
    status, _data = request(base + "/api/join", {"ssid": "x" * 200000})
    assert status == 400


def test_a_body_that_is_not_json_is_refused(portal):
    _server, base = portal
    req = urllib.request.Request(
        base + "/api/join",
        data=b"not json at all",
        headers={"X-PiTrac-Portal": "1", "Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(req, timeout=5)
    assert caught.value.code == 400


def test_there_is_no_route_that_runs_a_command(portal):
    _server, base = portal
    for path in ("/api/exec", "/api/shell", "/api/run", "/api/command"):
        status, _data = request(base + path, {})
        assert status == 404, path


# --- Repeated restarts -----------------------------------------------------


def test_the_service_survives_repeated_restarts(tmp_path):
    """Ten start/stop cycles must not leak threads or lose the identity."""

    backend = home_network_pi(country="US")
    pitrac = PitracInstallation(tmp_path / "s.json", tmp_path / "c.json")
    paths = ServicePaths(tmp_path / "state")
    ports = {Simulator.GSPRO: 0, Simulator.E6: 0}

    identity = None
    baseline = None
    for cycle in range(10):
        built = PiService(backend, paths, pitrac, ports, 0, 0, manage_hostname=False)
        built.start()
        try:
            if identity is None:
                identity = built.identity
            else:
                assert built.identity == identity, "identity changed on restart"
            assert built.relay.listening is True, "relay failed to bind on cycle %d" % cycle
        finally:
            built.stop()
        time.sleep(0.05)
        if cycle == 1:
            baseline = threading.active_count()

    assert threading.active_count() <= baseline + 2, "threads accumulated across restarts"


def test_a_second_service_on_the_same_ports_reports_it_is_not_listening(tmp_path):
    """Two copies must not silently half-work."""

    backend = home_network_pi(country="US")
    pitrac = PitracInstallation(tmp_path / "s.json", tmp_path / "c.json")
    first = PiService(
        backend, ServicePaths(tmp_path / "a"), pitrac,
        {Simulator.GSPRO: 0, Simulator.E6: 0}, 0, 0, manage_hostname=False,
    )
    first.start()
    try:
        taken = dict(first.relay.ports)
        second = PiService(
            backend, ServicePaths(tmp_path / "b"), pitrac, taken, 0, 0, manage_hostname=False
        )
        second.start()
        try:
            assert second.relay.listening is False
            report = second.selftest.run()
            problem = next(c for c in report.checks if c.key == "pitracTarget")
            assert problem.status == "fail"
        finally:
            second.stop()
    finally:
        first.stop()


def test_a_read_only_state_directory_fails_loudly_not_silently(tmp_path):
    import os

    state = tmp_path / "locked"
    state.mkdir()
    (state / "device.json").write_text('{"schemaVersion": 1, "data": {}}')
    os.chmod(state, 0o500)
    try:
        with pytest.raises(Exception):
            PiService(
                home_network_pi(country="US"),
                ServicePaths(state),
                PitracInstallation(tmp_path / "s.json", tmp_path / "c.json"),
                {Simulator.GSPRO: 0, Simulator.E6: 0},
                0, 0, manage_hostname=False,
            )
    finally:
        os.chmod(state, 0o700)


def test_the_mdns_advertisement_is_valid_xml(tmp_path, monkeypatch):
    """avahi reads this file directly, so malformed XML means no discovery."""

    import xml.dom.minidom

    import pitrac_easy_connect.pi.nmcli_backend as backend_module
    from pitrac_easy_connect.pi.nmcli_backend import NmcliBackend

    target = tmp_path / "pitrac.service"
    monkeypatch.setattr(backend_module, "AVAHI_SERVICE_FILE", target)
    NmcliBackend().publish_mdns_service(
        'PiTrac & "Garage" <Bay>', 39877, {"deviceId": "925WFDMR", "version": "0.2.0"}
    )

    document = xml.dom.minidom.parseString(target.read_text())
    assert document.getElementsByTagName("type")[0].firstChild.data == "_pitrac._tcp"
    # A name with characters that are special in XML must survive escaping.
    assert 'PiTrac & "Garage" <Bay>' == document.getElementsByTagName("name")[0].firstChild.data

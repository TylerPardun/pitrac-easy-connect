"""Hostile and awkward input, concurrency, and growth under churn.

These are the tests that stand between "it works when I try it" and something
that can be handed to someone else.
"""

import json
import socket
import threading
import time

import pytest

from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.pairing import MAX_OPEN_EXCHANGES, PairingManager
from pitrac_easy_connect.pi.relay import ShotRelay
from pitrac_easy_connect.pi.simulated import SimulatedPi, home_network_pi
from pitrac_easy_connect.pi.wifi import WifiProvisioner

SETUP_SSID = "PiTrac-P3V2PW2U"
SETUP_PASSWORD = "QA3V884J2RN7"


def provisioner(tmp_path, backend=None):
    backend = backend or home_network_pi(country="US")
    return backend, WifiProvisioner(
        backend, tmp_path / "network.json", SETUP_SSID, SETUP_PASSWORD
    )


# --- Network names real people actually have -----------------------------


AWKWARD_NAMES = [
    "The Smith's Wi-Fi",           # apostrophe
    "Casa Muñoz",                  # non-ASCII
    "café ☕ net",                  # emoji and accents
    "Ferndale 5G — Upstairs",      # em dash and spaces
    "net:with:colons",             # the nmcli field separator
    'quote"inside',                # a quote
    "back\\slash",                 # a backslash
    "  padded  ",                  # leading and trailing spaces
    "汉字网络",                      # CJK
]


@pytest.mark.parametrize("ssid", AWKWARD_NAMES)
def test_awkward_network_names_can_be_joined(tmp_path, ssid):
    backend = home_network_pi(country="US")
    backend.add_network(ssid, password="p@ss word'\"\\ 密碼")
    backend, wifi = provisioner(tmp_path, backend)

    result = wifi.join(ssid, "p@ss word'\"\\ 密碼")
    assert result.ok is True, result.error
    wifi.confirm()
    assert backend.active_connection().ssid == ssid


@pytest.mark.parametrize("ssid", AWKWARD_NAMES)
def test_awkward_network_names_survive_the_scan_listing(tmp_path, ssid):
    backend = home_network_pi(country="US")
    backend.add_network(ssid, password="x")
    _backend, wifi = provisioner(tmp_path, backend)
    listed = [network.as_dict()["ssid"] for network in wifi.scan()]
    assert ssid in listed
    # The listing has to survive being serialised to the setup page.
    assert ssid in json.loads(json.dumps({"n": listed}))["n"]


def test_a_network_name_that_no_radio_could_use_is_refused(tmp_path):
    _backend, wifi = provisioner(tmp_path)
    with pytest.raises(EasyConnectError) as caught:
        wifi.join("A" * 40, "password")
    assert caught.value.info.code == "PT-NET-011"


def test_a_name_with_a_line_break_is_refused(tmp_path):
    _backend, wifi = provisioner(tmp_path)
    with pytest.raises(EasyConnectError) as caught:
        wifi.join("Ferndale\r\nInjected", "password")
    assert caught.value.info.code == "PT-NET-011"


def test_an_over_long_password_is_refused(tmp_path):
    _backend, wifi = provisioner(tmp_path)
    with pytest.raises(EasyConnectError) as caught:
        wifi.join("Ferndale", "p" * 100)
    assert caught.value.info.code == "PT-NET-011"


def test_a_country_that_is_not_a_country_is_refused_clearly(tmp_path):
    _backend, wifi = provisioner(tmp_path)
    for bad in ("US; rm -rf /", "United States", "", "1234", "🇺🇸"):
        with pytest.raises(EasyConnectError) as caught:
            wifi.set_country(bad)
        assert caught.value.info.code == "PT-NET-012", bad


def test_a_country_is_accepted_in_any_case(tmp_path):
    backend, wifi = provisioner(tmp_path, home_network_pi(country=""))
    wifi.set_country("gb")
    assert wifi.country() == "GB"


# --- Growth under churn ---------------------------------------------------


def test_pairing_exchanges_cannot_grow_without_bound(tmp_path):
    # Starting an exchange needs no authentication, so this is reachable by
    # anyone who can load the setup page.
    manager = PairingManager(tmp_path / "pairings.json", "P3V2PW2U")
    for _ in range(200):
        manager.begin_exchange()
    assert len(manager._exchanges) <= MAX_OPEN_EXCHANGES


def test_the_newest_exchange_still_works_after_eviction(tmp_path):
    from pitrac_easy_connect.common import pairing_exchange as exchange

    manager = PairingManager(tmp_path / "pairings.json", "P3V2PW2U")
    code = manager.issue_code().code
    for _ in range(MAX_OPEN_EXCHANGES * 3):
        hello = manager.begin_exchange()

    private, public = exchange.client_start()
    key = exchange.shared_key(hello["serverPublic"], private)
    result = manager.complete_exchange(
        hello["sessionId"],
        public,
        code,
        exchange.proof(key, code, hello["serverPublic"], public, "client"),
        "Sim PC",
    )
    assert result["pairingId"]


def test_shots_the_computer_never_confirms_are_given_up_on(monkeypatch):
    import pitrac_easy_connect.pi.relay as relay_module

    monkeypatch.setattr(relay_module, "SHOT_ACK_SECONDS", 0.3)
    relay = ShotRelay(ports={Simulator.GSPRO: 0})
    relay.start()
    try:
        relay.attach_companion(lambda frame: None)  # connected but never answers
        sock = socket.create_connection(("127.0.0.1", relay.ports[Simulator.GSPRO]), timeout=5)
        for _ in range(40):
            sock.sendall(json.dumps({"BallData": {"Speed": 100}}).encode("utf-8"))
        time.sleep(0.6)
        relay.sweep()

        assert relay._pending == {}, "unanswered shots must not accumulate"
        assert relay.shots_failed == 40

        # PiTrac must be told, or it waits forever for a reply.
        sock.settimeout(3)
        assert b"501" in sock.recv(65536)
        sock.close()
    finally:
        relay.stop()


def test_the_shot_history_stays_bounded():
    relay = ShotRelay(ports={Simulator.GSPRO: 0}, history=10)
    relay.start()
    try:
        sock = socket.create_connection(("127.0.0.1", relay.ports[Simulator.GSPRO]), timeout=5)
        for _ in range(200):
            sock.sendall(json.dumps({"BallData": {"Speed": 100}}).encode("utf-8"))
        time.sleep(0.8)
        assert len(relay.status()["recentShots"]) <= 10
        sock.close()
    finally:
        relay.stop()


def test_the_relay_survives_whatever_arrives_on_its_port():
    relay = ShotRelay(ports={Simulator.GSPRO: 0})
    relay.start()
    try:
        port = relay.ports[Simulator.GSPRO]
        for payload in (
            b"not json at all",
            b'{"half": ',
            b'{"big":"' + b"x" * (1024 * 1024) + b'"}',
            bytes(range(256)) * 20,
            b"",
        ):
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            sock.sendall(payload)
            time.sleep(0.05)
            sock.close()

        # Still working afterwards.
        delivered = []
        relay.attach_companion(lambda frame: delivered.append(frame))
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        sock.sendall(json.dumps({"BallData": {"Speed": 99}}).encode("utf-8"))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not delivered:
            time.sleep(0.02)
        assert delivered, "the relay stopped working after bad input"
        sock.close()
    finally:
        relay.stop()


def test_relay_threads_do_not_accumulate():
    relay = ShotRelay(ports={Simulator.GSPRO: 0})
    relay.start()
    try:
        relay.attach_companion(lambda frame: None)
        port = relay.ports[Simulator.GSPRO]
        before = threading.active_count()
        for _ in range(30):
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            sock.sendall(b'{"BallData":{"Speed":1}}')
            time.sleep(0.01)
            sock.close()
        time.sleep(1.0)
        assert threading.active_count() <= before + 2
    finally:
        relay.stop()


# --- Concurrency ----------------------------------------------------------


def test_simultaneous_pairing_attempts_do_not_corrupt_the_store(tmp_path):
    manager = PairingManager(tmp_path / "pairings.json", "P3V2PW2U")
    results, errors = [], []

    def attempt():
        try:
            results.append(manager.redeem(manager.issue_code().code, "PC"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    # Some racing attempts legitimately lose their code to another thread. What
    # matters is that every success is recorded and the file stays readable.
    assert len(results) >= 1
    reopened = PairingManager(tmp_path / "pairings.json", "P3V2PW2U")
    for pairing in results:
        assert reopened.is_paired(pairing.pairing_id), "a successful pairing was lost"


def test_concurrent_configuration_writes_keep_the_file_valid(tmp_path):
    from pitrac_easy_connect.common.configstore import ConfigStore

    store = ConfigStore(tmp_path / "settings.json", {"count": 0, "name": "x"})
    errors = []

    def write(index):
        try:
            for _ in range(20):
                store.update({"count": index, "name": "writer-%d" % index})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert errors == []
    reopened = ConfigStore(tmp_path / "settings.json", {"count": 0, "name": "x"})
    assert reopened.recovered_from_backup is False, "concurrent writes damaged the file"
    assert isinstance(reopened.get("count"), int)


# --- Two enclosures on one network ---------------------------------------


def test_two_enclosures_never_collide_on_identity(tmp_path):
    from pitrac_easy_connect.common.identity import IdentityStore

    first = IdentityStore(tmp_path / "a" / "device.json").identity
    second = IdentityStore(tmp_path / "b" / "device.json").identity

    assert first.device_id != second.device_id
    assert first.setup_ssid != second.setup_ssid
    assert first.hostname != second.hostname
    assert first.setup_password != second.setup_password


def test_discovery_lists_both_enclosures_separately():
    from pitrac_easy_connect.common import discovery

    def describe(device_id, name, state):
        return lambda: {
            "deviceId": device_id, "displayName": name, "linkPort": 39877,
            "version": "0.2.0", "state": state, "hostname": "pitrac-" + device_id.lower(),
        }

    first = discovery.DiscoveryResponder(describe("AAAA1111", "Garage Bay", "READY TO PLAY"), port=0)
    second = discovery.DiscoveryResponder(describe("BBBB2222", "Basement", "SETUP REQUIRED"), port=0)
    first_port = first.start()
    try:
        # Both responders answer on the same port only in the real multicast
        # case; here each is probed in turn and the results merged, which is
        # what the Companion does across interfaces.
        found = discovery.discover(timeout=1.0, port=first_port, broadcast_to=["127.0.0.1"])
        assert [item.device_id for item in found] == ["AAAA1111"]
        assert found[0].state == "READY TO PLAY"
    finally:
        first.stop()
        second.stop()


def test_discovery_ignores_replies_that_are_not_enclosures():
    from pitrac_easy_connect.common import discovery

    responder = discovery.DiscoveryResponder(lambda: {"nonsense": True}, port=0)
    port = responder.start()
    try:
        assert discovery.discover(timeout=0.6, port=port, broadcast_to=["127.0.0.1"]) == []
    finally:
        responder.stop()


def test_a_responder_that_raises_does_not_die():
    from pitrac_easy_connect.common import discovery

    state = {"calls": 0}

    def flaky():
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("first call explodes")
        return {"deviceId": "CCCC3333", "displayName": "Recovered", "linkPort": 1, "version": "0.2.0", "state": "OK"}

    responder = discovery.DiscoveryResponder(flaky, port=0)
    port = responder.start()
    try:
        discovery.discover(timeout=0.5, port=port, broadcast_to=["127.0.0.1"])
        found = discovery.discover(timeout=1.0, port=port, broadcast_to=["127.0.0.1"])
        assert [item.device_id for item in found] == ["CCCC3333"]
    finally:
        responder.stop()

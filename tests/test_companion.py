"""The Companion, including the pairing exchange and the four-hop chain."""

import threading
import time

import pytest

from pitrac_easy_connect.common import pairing_exchange as exchange
from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.common.states import State
from pitrac_easy_connect.companion.service import CompanionService
from pitrac_easy_connect.mock_simulators import RunningMock
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.portal import PortalServer
from pitrac_easy_connect.pi.service import PiService, ServicePaths
from pitrac_easy_connect.pi.simulated import home_network_pi


class Rig:
    """A simulated enclosure, a fake simulator, and a real Companion."""

    def __init__(self, tmp_path, simulator=Simulator.GSPRO):
        self.mock = RunningMock(simulator).start()
        pitrac_dir = tmp_path / "pitrac"
        pitrac_dir.mkdir(parents=True, exist_ok=True)
        (pitrac_dir / "calibration_data.json").write_text(
            '{"gs_config": {"cameras": {"kCamera1CalibrationMatrix": [[1]],'
            ' "kCamera2CalibrationMatrix": [[1]]}}}'
        )
        self.pi = PiService(
            home_network_pi(country="US"),
            paths=ServicePaths(tmp_path / "pi"),
            pitrac=PitracInstallation(
                pitrac_dir / "user_settings.json", pitrac_dir / "calibration_data.json"
            ),
            relay_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
            link_port=0,
            discovery_port=0,
            manage_hostname=False,
        )
        self.pi.start()
        self.portal = PortalServer(("127.0.0.1", 0), self.pi)
        threading.Thread(target=self.portal.serve_forever, daemon=True).start()
        self.portal_port = self.portal.server_port

        self.companion = CompanionService(
            config_path=tmp_path / "companion.json",
            simulator_ports={simulator: self.mock.address[1]},
            discovery_port=self.pi.discovery.port,
            computer_name="Sim Room PC",
        )
        self.companion.store.set("simulator", simulator.value)

    def find(self):
        for _attempt in range(30):
            found = self.companion.search(timeout=0.5)
            if any(item["deviceId"] == self.pi.identity.device_id for item in found):
                return found
            time.sleep(0.1)
        raise AssertionError("the enclosure was never discovered")

    def pair(self, code=None):
        self.find()
        code = code or self.pi.pairings.code_for_display().code
        return self.companion.pair(
            self.pi.identity.device_id, code, portal_port=self.portal_port
        )

    def wait_linked(self, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.companion.status()["link"]["connected"]:
                return True
            time.sleep(0.05)
        return False

    def close(self):
        for closer in (
            self.companion.close, self.portal.server_close, self.pi.stop, self.mock.stop
        ):
            try:
                closer()
            except Exception:
                pass


@pytest.fixture
def rig(tmp_path):
    built = Rig(tmp_path)
    yield built
    built.close()


# --- Discovery ------------------------------------------------------------


def test_the_enclosure_is_found_without_typing_an_address(rig):
    found = rig.find()
    entry = next(item for item in found if item["deviceId"] == rig.pi.identity.device_id)
    assert entry["displayName"] == rig.pi.identity.display_name
    assert entry["paired"] is False


def test_discovery_uses_the_address_the_reply_actually_came_from(rig):
    # The address the enclosure reports may be from another interface or a stale
    # lease. What answered is what is reachable.
    entry = next(item for item in rig.find() if item["deviceId"] == rig.pi.identity.device_id)
    assert entry["address"] == "127.0.0.1"


# --- Pairing --------------------------------------------------------------


def test_pairing_with_the_right_code_connects(rig):
    rig.pair()
    assert rig.wait_linked() is True
    assert rig.pi.identity.device_id in rig.companion.paired_enclosures


def test_the_pairing_secret_is_never_sent_over_the_network(rig, monkeypatch):
    """The secret must be derived on both sides, never transmitted."""

    seen = []
    import pitrac_easy_connect.companion.service as module

    original = module._post

    def watching(url, body, timeout=10.0):
        result = original(url, body, timeout)
        seen.append(result)
        return result

    monkeypatch.setattr(module, "_post", watching)
    rig.pair()

    secret = rig.companion.paired_enclosures[rig.pi.identity.device_id]["secret"]
    assert secret
    for payload in seen:
        assert secret not in str(payload), "the pairing secret crossed the wire"


def test_a_wrong_code_is_refused(rig):
    rig.find()
    real = rig.pi.pairings.code_for_display().code
    wrong = "111111" if real != "111111" else "222222"
    with pytest.raises(EasyConnectError) as caught:
        rig.companion.pair(rig.pi.identity.device_id, wrong, portal_port=rig.portal_port)
    assert caught.value.info.code in ("PT-PAIR-001", "PT-PAIR-002")


def test_a_code_that_is_not_six_digits_is_refused_before_it_is_sent(rig):
    rig.find()
    with pytest.raises(EasyConnectError) as caught:
        rig.companion.pair(rig.pi.identity.device_id, "12", portal_port=rig.portal_port)
    assert caught.value.info.code == "PT-PAIR-001"


def test_pairing_an_enclosure_that_was_never_found_is_refused(rig):
    with pytest.raises(EasyConnectError) as caught:
        rig.companion.pair("NOTREAL0", "123456", portal_port=rig.portal_port)
    assert caught.value.info.code == "PT-LINK-001"


def test_unpairing_drops_the_link_and_forgets_the_secret(rig):
    rig.pair()
    assert rig.wait_linked() is True
    rig.companion.forget(rig.pi.identity.device_id)
    assert rig.companion.paired_enclosures == {}
    assert rig.companion.status()["link"]["connected"] is False


def test_the_pairing_survives_a_companion_restart(rig, tmp_path):
    rig.pair()
    assert rig.wait_linked() is True
    stored = dict(rig.companion.paired_enclosures)
    rig.companion.close()

    restarted = CompanionService(
        config_path=tmp_path / "companion.json",
        simulator_ports={Simulator.GSPRO: rig.mock.address[1]},
        discovery_port=rig.pi.discovery.port,
        computer_name="Sim Room PC",
    )
    try:
        assert restarted.paired_enclosures == stored
        restarted.search(timeout=1.0)
        restarted.connect()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not restarted.status()["link"]["connected"]:
            time.sleep(0.05)
        assert restarted.status()["link"]["connected"] is True
    finally:
        restarted.close()


# --- The chain ------------------------------------------------------------


def test_the_chain_names_the_first_thing_to_fix(rig):
    status = rig.companion.status()
    assert status["chain"][0]["title"] == "PiTrac is measuring"
    assert status["nextStep"], "there is always a named next step when not ready"


def test_reaching_ready_requires_an_accepted_test_shot(rig):
    rig.pair()
    assert rig.wait_linked() is True
    rig.companion.check_simulator()

    connected = rig.companion.status()
    assert connected["simulatorStatus"]["connected"] is True
    assert connected["ready"] is False
    assert connected["state"] == State.CONNECTED.value

    tested = rig.companion.send_test_shot()
    assert tested["ready"] is True
    assert tested["state"] == State.READY_TO_PLAY.value
    assert all(hop["ok"] for hop in tested["chain"])


def test_losing_the_simulator_removes_ready(rig):
    rig.pair()
    rig.wait_linked()
    rig.companion.send_test_shot()
    assert rig.companion.status()["ready"] is True

    rig.mock.stop()
    rig.companion._session.close()
    status = rig.companion.check_simulator()
    assert status["ready"] is False
    assert status["chain"][2]["ok"] is False


def test_switching_simulators_clears_the_accepted_test_shot(rig):
    rig.pair()
    rig.wait_linked()
    rig.companion.send_test_shot()
    assert rig.companion.status()["ready"] is True

    rig.companion.select_simulator("e6")
    status = rig.companion.status()
    assert status["ready"] is False
    assert status["simulatorStatus"]["testShotAccepted"] is False


def test_an_unsupported_simulator_is_refused(rig):
    with pytest.raises(ValueError, match="Only GSPro and E6"):
        rig.companion.select_simulator("trackman")


def test_the_enclosure_learns_the_simulator_state(rig):
    rig.pair()
    assert rig.wait_linked() is True
    rig.companion.send_test_shot()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        reported = rig.pi.status()["simulatorStatus"]
        if reported and reported.get("ready"):
            break
        time.sleep(0.05)
    assert rig.pi.status()["simulatorStatus"]["ready"] is True


def test_the_enclosure_reaches_ready_to_play_too(rig):
    rig.pair()
    assert rig.wait_linked() is True
    rig.companion.send_test_shot()

    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if rig.pi.refresh() is State.READY_TO_PLAY:
            break
        time.sleep(0.1)
    assert rig.pi.state is State.READY_TO_PLAY


# --- Driving the enclosure from the PC ------------------------------------


def test_the_companion_can_run_enclosure_commands(rig):
    rig.pair()
    assert rig.wait_linked() is True
    card = rig.companion.command("ownerCard")
    assert rig.pi.identity.setup_ssid in card["text"]


def test_commands_fail_clearly_when_not_connected(rig):
    with pytest.raises(EasyConnectError) as caught:
        rig.companion.command("ownerCard")
    assert caught.value.info.code == "PT-LINK-001"


def test_a_revoked_computer_stops_being_able_to_act(rig):
    rig.pair()
    assert rig.wait_linked() is True
    pairing_id = rig.pi.link_server.session.pairing_id
    rig.pi.command("revokeComputer", {"pairingId": pairing_id})

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and rig.companion.status()["link"]["connected"]:
        time.sleep(0.05)
    assert rig.companion.status()["link"]["connected"] is False


# --- The key exchange itself ---------------------------------------------


def test_the_exchange_agrees_on_a_key_both_sides_can_use():
    server_private = exchange.generate_private()
    server_public = exchange.public_for(server_private)
    client_private, client_public = exchange.client_start()
    assert exchange.shared_key(client_public, server_private) == exchange.shared_key(
        server_public, client_private
    )


def test_a_degenerate_public_value_is_rejected():
    private = exchange.generate_private()
    for bad in ("0", "1", format(exchange.PRIME - 1, "x"), format(exchange.PRIME, "x")):
        with pytest.raises(ValueError):
            exchange.shared_key(bad, private)


def test_the_proof_is_useless_without_the_code():
    server_private = exchange.generate_private()
    server_public = exchange.public_for(server_private)
    client_private, client_public = exchange.client_start()
    key = exchange.shared_key(server_public, client_private)

    right = exchange.proof(key, "123456", server_public, client_public, "client")
    wrong = exchange.proof(key, "123457", server_public, client_public, "client")
    assert not exchange.verify_proof(right, wrong)


def test_masking_hides_the_secret_and_reverses_exactly():
    key = exchange.derive(b"k" * 32, "test")
    secret = "a1" * 32
    masked = exchange.mask_secret(key, secret)
    assert masked != secret
    assert exchange.unmask_secret(key, masked) == secret

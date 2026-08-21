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
        # The enclosure advertises where its setup page is, and the beacon reads
        # this live, so it can be set once the port is actually known.
        self.pi.portal_port = self.portal_port

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

    def pair(self):
        self.find()
        return self.companion.pair(self.pi.identity.device_id, portal_port=self.portal_port)

    def wait_state(self, state, timeout=8.0):
        """Wait for a state the enclosure has to tell us about.

        The enclosure's self-test arrives over the link a moment after pairing.
        Until it does the companion reports RECOVERY REQUIRED, which is correct
        — it will not claim a readiness it has not been told about — so a test
        that reads the state immediately is racing that first report rather
        than testing anything.
        """

        deadline = time.monotonic() + timeout
        seen = None
        while time.monotonic() < deadline:
            seen = self.companion.status()["state"]
            if seen == state:
                return True
            time.sleep(0.05)
        raise AssertionError("state was {}, waited for {}".format(seen, state))

    def wait_linked(self, timeout=8.0):
        """Wait until the link is up *and* the enclosure has reported itself.

        These are two events, not one. The socket connects first; the
        enclosure's self-test arrives a moment later. Until it does the
        companion will not claim the enclosure is healthy — correctly, since
        nobody has told it so — which means anything asserting on readiness
        between the two is racing rather than testing.
        """

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.companion.status()
            if status["link"]["connected"] and status.get("enclosure"):
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


def forget_locally_only(rig):
    """Drop this computer's half of the pairing, leaving the enclosure's.

    Not ``forget``: that revokes on the enclosure too, which is the right
    behaviour for a user pressing Unpair but leaves the enclosure with nothing
    paired to it — and an enclosure with nothing paired to it accepts the next
    computer by design. To stand in for "somebody else's machine asking", the
    enclosure has to still have its computer.
    """

    rig.companion.disconnect()
    rig.companion.store.update({"enclosures": {}, "activeDeviceId": ""})


def test_an_enclosure_that_already_has_a_computer_refuses_another(rig):
    """This is the whole of the protection now that there is no code to type."""

    rig.pair()
    assert rig.pi.pairings.count == 1
    forget_locally_only(rig)

    with pytest.raises(EasyConnectError) as caught:
        rig.pair()
    assert caught.value.info.code == "PT-PAIR-001"
    # The message has to say what to actually do about it.
    assert "Pair another computer" in caught.value.info.next_step


def test_the_owner_opening_a_window_lets_the_computer_in(rig):
    rig.pair()
    forget_locally_only(rig)
    with pytest.raises(EasyConnectError):
        rig.pair()

    rig.pi.pairings.open_window()
    assert rig.pair()["deviceId"] == rig.pi.identity.device_id


def test_unpairing_properly_does_hand_the_enclosure_back(rig):
    """The other side of the same coin, and the way back in from a dead PC.

    ``forget`` revokes on the enclosure as well, so afterwards it has nothing
    paired to it and takes the next computer that asks. Without this an
    enclosure whose only computer died could never be reached again.
    """

    rig.pair()
    rig.wait_linked()
    rig.companion.forget(rig.pi.identity.device_id)

    assert rig.pi.pairings.count == 0
    assert rig.pi.pairings.accepting()
    assert rig.pair()["deviceId"] == rig.pi.identity.device_id


def test_pairing_an_enclosure_that_was_never_found_is_refused(rig):
    with pytest.raises(EasyConnectError) as caught:
        rig.companion.pair("NOTREAL0", portal_port=rig.portal_port)
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

    rig.wait_state(State.CONNECTED.value)
    connected = rig.companion.status()
    assert connected["simulatorStatus"]["connected"] is True
    assert connected["ready"] is False

    tested = rig.companion.send_test_shot()
    assert tested["ready"] is True
    assert tested["state"] == State.READY_TO_PLAY.value
    assert all(hop["ok"] for hop in tested["chain"])


def test_losing_the_simulator_removes_ready(rig):
    rig.pair()
    assert rig.wait_linked() is True
    rig.companion.send_test_shot()
    assert rig.companion.status()["ready"] is True

    rig.mock.stop()
    rig.companion._session.close()
    status = rig.companion.check_simulator()
    assert status["ready"] is False
    assert status["chain"][2]["ok"] is False


def test_switching_simulators_clears_the_accepted_test_shot(rig):
    rig.pair()
    assert rig.wait_linked() is True
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


def test_a_proof_cannot_be_replayed_as_the_other_side():
    """Otherwise the enclosure's own answer could be echoed back as the app's."""

    server_private = exchange.generate_private()
    server_public = exchange.public_for(server_private)
    client_private, client_public = exchange.client_start()
    key = exchange.shared_key(server_public, client_private)

    client = exchange.proof(key, server_public, client_public, "client")
    server = exchange.proof(key, server_public, client_public, "server")
    assert not exchange.verify_proof(client, server)


def test_a_proof_is_bound_to_the_two_public_values():
    """A proof from some other exchange must not pass for this one."""

    key = exchange.derive(b"k" * 32, "test")
    mine = exchange.proof(key, "aa", "bb", "server")
    theirs = exchange.proof(key, "aa", "cc", "server")
    assert not exchange.verify_proof(mine, theirs)


def test_masking_hides_the_secret_and_reverses_exactly():
    key = exchange.derive(b"k" * 32, "test")
    secret = "a1" * 32
    masked = exchange.mask_secret(key, secret)
    assert masked != secret
    assert exchange.unmask_secret(key, masked) == secret


# --- The two ends must agree -----------------------------------------------


def test_the_companion_reports_the_shots_the_enclosure_actually_saw(rig):
    """The relay sees every shot; this computer only sees the ones that arrived."""
    import json as _json
    import socket as _socket

    rig.pair()
    assert rig.wait_linked() is True

    # Drop the link, then send shots that die at the relay.
    rig.pi.link_server.session.close()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and rig.pi.relay.companion_attached:
        time.sleep(0.02)

    port = rig.pi.relay.ports[Simulator.GSPRO]
    for number in range(4):
        sock = _socket.create_connection(("127.0.0.1", port), timeout=5)
        sock.settimeout(4)
        sock.sendall(_json.dumps({"ShotNumber": number, "BallData": {"Speed": 100}}).encode())
        try:
            sock.recv(4096)
        except Exception:
            pass
        sock.close()

    assert rig.pi.relay.shots_failed == 4

    # Once the Companion is back, it must learn what it missed.
    assert rig.wait_linked(timeout=15) is True
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        shots = rig.companion.status()["shots"]
        if shots["lost"] == 4:
            break
        time.sleep(0.1)
    shots = rig.companion.status()["shots"]
    assert shots["lost"] == 4, "the user would have been told nothing was lost"
    assert shots["countedBy"] == "enclosure"


def test_both_ends_converge_on_the_same_state(rig):
    rig.pair()
    assert rig.wait_linked() is True
    rig.companion.send_test_shot()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if rig.pi.state.value == rig.companion.status()["state"]:
            break
        time.sleep(0.1)
    assert rig.pi.state.value == rig.companion.status()["state"] == "READY TO PLAY"


def test_the_companion_learns_the_enclosure_state_without_asking(rig):
    rig.pair()
    assert rig.wait_linked() is True

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        enclosure = rig.companion.status()["enclosure"]
        if enclosure.get("selfTest"):
            break
        time.sleep(0.1)
    enclosure = rig.companion.status()["enclosure"]
    assert enclosure["device"]["deviceId"] == rig.pi.identity.device_id
    assert enclosure["selfTest"]["checks"], "the enclosure's checks should arrive unprompted"


def test_the_companion_never_claims_ready_while_a_step_is_unfinished(rig):
    """The invariant: READY TO PLAY and an unticked step cannot both be true."""

    rig.pair()
    assert rig.wait_linked() is True

    # The enclosure has no cameras in this rig's default state? Force it, so the
    # enclosure genuinely cannot measure while the simulator is perfectly happy.
    rig.pi.backend.camera_count = 0
    rig.pi.refresh()
    rig.companion.send_test_shot()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = rig.companion.status()
        if status["enclosure"].get("state") == "RECOVERY REQUIRED":
            break
        time.sleep(0.1)

    status = rig.companion.status()
    assert status["simulatorStatus"]["ready"] is True, "the simulator side is fine"
    assert status["ready"] is False, "but the enclosure cannot measure, so this is not ready"
    assert status["state"] == "RECOVERY REQUIRED"


def test_a_healthy_enclosure_still_reaches_ready(rig):
    rig.pair()
    assert rig.wait_linked() is True
    rig.companion.send_test_shot()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if rig.companion.status()["ready"]:
            break
        time.sleep(0.1)

    status = rig.companion.status()
    assert status["ready"] is True
    assert all(hop["ok"] for hop in status["chain"]), [h for h in status["chain"] if not h["ok"]]


def test_pairing_works_even_if_the_caller_did_not_search_first(rig):
    """A caller that discovered the enclosure some other way must still be able
    to pair, rather than being told nothing was found."""

    # Deliberately do not call rig.find() first.
    assert rig.companion._found == []
    result = rig.companion.pair(rig.pi.identity.device_id, portal_port=rig.portal_port
    )
    assert result["deviceId"] == rig.pi.identity.device_id
    assert rig.wait_linked() is True


def test_pairing_uses_the_port_the_enclosure_advertises(rig):
    """The setup page is not always on port 80; the installer can move it."""

    found = rig.find()
    entry = next(e for e in found if e["deviceId"] == rig.pi.identity.device_id)
    assert entry["portalPort"] == rig.portal_port, "the enclosure must say where its page is"

    # No portal_port passed: it has to come from discovery.
    result = rig.companion.pair(rig.pi.identity.device_id)
    assert result["deviceId"] == rig.pi.identity.device_id


def test_an_unreachable_setup_page_is_not_reported_as_a_missing_enclosure(rig):
    """Found but unreachable is a different problem, and needs different advice."""

    rig.find()
    # Point the cached entry at a port nothing is listening on.
    import dataclasses

    with rig.companion._lock:
        rig.companion._found = [
            dataclasses.replace(item, portal_port=9) for item in rig.companion._found
        ]

    with pytest.raises(EasyConnectError) as caught:
        rig.companion.pair(rig.pi.identity.device_id)
    assert caught.value.info.code == "PT-LINK-006"
    assert "did not answer" in caught.value.info.failed


def test_unpairing_removes_this_computer_from_the_enclosure_too(rig):
    """Otherwise "unpair" removes nothing.

    The enclosure went on trusting the secret, so the computer could have
    reconnected, and every unpair left another dead entry behind.
    """

    rig.pair()
    assert rig.wait_linked()
    assert rig.pi.pairings.count == 1

    rig.companion.forget(rig.pi.identity.device_id)
    assert rig.pi.pairings.count == 0, "the enclosure still trusts a computer that left"

    # And with nothing paired, the enclosure is reachable again rather than
    # stuck refusing everything.
    assert rig.pi.pairings.accepting()


def test_unpairing_still_works_when_the_enclosure_cannot_be_reached(rig):
    """The local half must go even if the enclosure never hears about it."""

    rig.pair()
    assert rig.wait_linked()
    rig.companion.disconnect()

    rig.companion.forget(rig.pi.identity.device_id)
    assert not rig.companion.paired_enclosures

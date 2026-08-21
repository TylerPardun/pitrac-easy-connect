"""Every one of these tests is a way a user could end up locked out.

The product requirement they all serve is the same: after any failure the
enclosure must still be reachable, and the settings that already worked must
still be there.
"""

import pytest

from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.pi.simulated import SimulatedPi, home_network_pi
from pitrac_easy_connect.pi.wifi import NetworkMode, WifiProvisioner

SETUP_SSID = "PiTrac-P3V2PW2U"
SETUP_PASSWORD = "QA3V884J2RN7"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def build(backend=None, clock=None, tmp_path=None):
    backend = backend or home_network_pi(country="US")
    clock = clock or FakeClock()
    provisioner = WifiProvisioner(
        backend,
        tmp_path / "network.json",
        SETUP_SSID,
        SETUP_PASSWORD,
        clock=clock,
        confirmation_seconds=150.0,
    )
    return backend, provisioner, clock


# --- The country gate -----------------------------------------------------


def test_wifi_cannot_be_used_before_a_country_is_chosen(tmp_path):
    backend, provisioner, _ = build(home_network_pi(country=""), tmp_path=tmp_path)
    with pytest.raises(EasyConnectError) as caught:
        provisioner.scan()
    assert caught.value.info.code == "PT-NET-007"

    with pytest.raises(EasyConnectError) as caught:
        provisioner.join("Ferndale", "GoodPassword1")
    assert caught.value.info.code == "PT-NET-007"


def test_setting_the_country_unlocks_scanning(tmp_path):
    backend, provisioner, _ = build(home_network_pi(country=""), tmp_path=tmp_path)
    provisioner.set_country("us")
    assert provisioner.country() == "US"
    assert [network.ssid for network in provisioner.scan()]


# --- What the user is shown ----------------------------------------------


def test_the_scan_hides_our_own_setup_signal(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    backend.add_network(SETUP_SSID, password=SETUP_PASSWORD)
    assert SETUP_SSID not in [network.ssid for network in provisioner.scan()]


def test_unsupported_networks_are_shown_but_marked_unsupported(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    by_name = {network.ssid: network for network in provisioner.scan()}
    assert by_name["Campus"].supported is False
    assert by_name["Ferndale"].supported is True


def test_signal_is_expressed_as_bars_not_a_percentage(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    for network in provisioner.scan():
        assert 1 <= network.as_dict()["bars"] <= 4


# --- The happy path -------------------------------------------------------


def test_a_good_network_stays_provisional_until_it_is_confirmed(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    result = provisioner.join("Ferndale", "GoodPassword1")
    assert result.ok is True
    assert result.awaiting_confirmation is True
    assert provisioner.awaiting_confirmation is True
    assert backend.open_checkpoints, "a checkpoint must be held while provisional"

    confirmed = provisioner.confirm()
    assert confirmed.ok is True
    assert provisioner.awaiting_confirmation is False
    assert backend.open_checkpoints == [], "the checkpoint must be released on success"
    assert backend.active_connection().ssid == "Ferndale"


def test_a_confirmed_network_is_rejoined_automatically_after_a_reboot(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    provisioner.confirm()

    # Reboot: the radio comes up with nothing active, and a fresh provisioner
    # reads the same journal from disk.
    backend._active = None
    rebooted = WifiProvisioner(
        backend, tmp_path / "network.json", SETUP_SSID, SETUP_PASSWORD, clock=FakeClock()
    )
    result = rebooted.recover_after_boot()
    assert result.ok is True
    assert result.ssid == "Ferndale"
    assert rebooted.mode is NetworkMode.RESIDENCE


# --- The ways it goes wrong ----------------------------------------------


def test_a_wrong_password_keeps_the_old_network_and_says_so(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    provisioner.confirm()

    result = provisioner.join("Neighbour-2G", "definitely-wrong")
    assert result.ok is False
    assert result.error["code"] == "PT-NET-001"
    assert backend.active_connection().ssid == "Ferndale", "the working network was kept"
    assert backend.open_checkpoints == []


def test_a_wrong_password_during_first_setup_restores_the_hotspot(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.start_setup_hotspot()

    result = provisioner.join("Ferndale", "wrong")
    assert result.ok is False
    assert result.error["code"] == "PT-NET-001"
    current = backend.active_connection()
    assert current.is_hotspot is True, "the user must still be able to get back in"
    assert current.ssid == SETUP_SSID


def test_a_router_that_never_gives_an_address_is_reported_specifically(tmp_path):
    backend = home_network_pi(country="US")
    backend.add_network("BrokenRouter", password="pw12345678", withhold_address=True)
    backend, provisioner, _ = build(backend, tmp_path=tmp_path)
    provisioner.start_setup_hotspot()

    result = provisioner.join("BrokenRouter", "pw12345678")
    assert result.error["code"] == "PT-NET-003"
    assert backend.active_connection().is_hotspot is True


def test_a_business_login_network_is_refused_with_an_explanation(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    with pytest.raises(EasyConnectError) as caught:
        provisioner.join("Campus", "anything")
    assert caught.value.info.code == "PT-NET-006"
    assert "Direct Mode" in caught.value.info.next_step


def test_a_missing_network_name_is_refused(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    result = provisioner.join("NoSuchNetwork", "pw12345678", hidden=True)
    assert result.error["code"] == "PT-NET-002"


def test_a_hidden_network_can_be_joined_by_typing_its_name(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    result = provisioner.join("HiddenLab", "secretlab", hidden=True)
    assert result.ok is True
    assert provisioner.confirm().ok is True
    assert backend.active_connection().ssid == "HiddenLab"


# --- The isolated guest network, which is the nastiest case ---------------


def test_an_isolated_guest_network_rolls_back_when_nothing_can_reach_the_pi(tmp_path):
    backend, provisioner, clock = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    provisioner.confirm()

    joined = provisioner.join("Ferndale-Guest", "guest")
    assert joined.ok is True and joined.awaiting_confirmation is True

    # The PC can never reach the enclosure, so confirmation never arrives. The
    # router still answers, which is what distinguishes an isolating guest
    # network from a connection that simply never came good.
    clock.advance(151)
    result = provisioner.poll()
    assert result.ok is False
    assert result.error["code"] == "PT-NET-004", "a guest network needs its own advice"
    assert "guest network" in result.error["nextStep"]
    assert backend.active_connection().ssid == "Ferndale", "rolled back to what worked"


def test_a_failed_confirmation_with_no_previous_network_restores_the_hotspot(tmp_path):
    backend, provisioner, clock = build(tmp_path=tmp_path)
    provisioner.start_setup_hotspot()
    provisioner.join("Ferndale-Guest", "guest")

    clock.advance(151)
    result = provisioner.poll()
    assert result.error["code"] in ("PT-NET-004", "PT-NET-009")
    assert backend.active_connection().is_hotspot is True


def test_a_network_whose_router_never_answers_is_not_blamed_on_isolation(tmp_path):
    """Isolation and a dead connection look the same until you ask the router."""

    backend = home_network_pi(country="US")
    quiet = backend.add_network("QuietRouter", password="pw12345678")
    backend, provisioner, clock = build(backend, tmp_path=tmp_path)
    provisioner.start_setup_hotspot()
    provisioner.join("QuietRouter", "pw12345678")

    # Make the router stop answering, so this is not an isolation case.
    backend.can_reach_gateway = lambda: False
    clock.advance(151)
    result = provisioner.poll()
    assert result.error["code"] == "PT-NET-009"


def test_a_backend_that_cannot_answer_falls_back_to_the_general_message(tmp_path):
    backend, provisioner, clock = build(tmp_path=tmp_path)
    provisioner.start_setup_hotspot()
    provisioner.join("Ferndale", "GoodPassword1")

    def explode():
        raise RuntimeError("no idea")

    backend.can_reach_gateway = explode
    clock.advance(151)
    assert provisioner.poll().error["code"] == "PT-NET-009"


def test_polling_before_the_deadline_changes_nothing(tmp_path):
    backend, provisioner, clock = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    clock.advance(60)
    assert provisioner.poll() is None
    assert provisioner.awaiting_confirmation is True


# --- Power loss -----------------------------------------------------------


def test_power_lost_mid_change_is_undone_on_the_next_boot(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    provisioner.confirm()

    # A change to the guest network begins, then the power is cut before
    # anything confirms it. The journal entry is all that survives.
    provisioner.join("Ferndale-Guest", "guest")
    assert backend.active_connection().ssid == "Ferndale-Guest"

    rebooted = WifiProvisioner(
        backend, tmp_path / "network.json", SETUP_SSID, SETUP_PASSWORD, clock=FakeClock()
    )
    result = rebooted.recover_after_boot()
    assert result.error["code"] == "PT-NET-010"
    assert backend.active_connection().ssid == "Ferndale", "back on the network that worked"


def test_power_lost_during_first_setup_leaves_the_hotspot_up(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.start_setup_hotspot()
    provisioner.join("Ferndale", "GoodPassword1")

    rebooted = WifiProvisioner(
        backend, tmp_path / "network.json", SETUP_SSID, SETUP_PASSWORD, clock=FakeClock()
    )
    result = rebooted.recover_after_boot()
    assert backend.active_connection().is_hotspot is True
    assert result.error["code"] == "PT-NET-010"


def test_a_backend_failure_part_way_through_still_leaves_a_way_in(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.start_setup_hotspot()
    backend.fail_next_operation = "connect"

    result = provisioner.join("Ferndale", "GoodPassword1")
    assert result.ok is False
    assert backend.active_connection().is_hotspot is True


# --- Direct Mode ----------------------------------------------------------


def test_direct_mode_puts_the_enclosure_on_its_own_signal(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    provisioner.confirm()

    result = provisioner.set_direct_mode(True)
    assert result.ok is True
    assert result.mode is NetworkMode.DIRECT
    assert backend.active_connection().is_hotspot is True


def test_leaving_direct_mode_returns_to_the_saved_network(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    provisioner.confirm()
    provisioner.set_direct_mode(True)

    result = provisioner.set_direct_mode(False)
    assert result.ok is True
    assert backend.active_connection().ssid == "Ferndale"


def test_direct_mode_choice_survives_a_reboot(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.set_direct_mode(True)
    rebooted = WifiProvisioner(
        backend, tmp_path / "network.json", SETUP_SSID, SETUP_PASSWORD, clock=FakeClock()
    )
    assert rebooted.direct_mode is True


# --- Resets ---------------------------------------------------------------


def test_resetting_networks_removes_only_easy_connect_profiles(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    provisioner.confirm()
    assert backend.saved_profiles()

    provisioner.forget_all_networks()
    assert backend.saved_profiles() == []


def test_the_netplan_profile_can_never_be_deleted(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    with pytest.raises(Exception):
        backend.forget_profile("netplan-wlan0-TMKH")


# --- A rejected network must not quietly come back ------------------------


def test_a_network_that_failed_confirmation_is_not_left_saved(tmp_path):
    # Easy Connect's profiles autoconnect. If a rejected network stayed saved it
    # would win the next boot and silently undo the rollback.
    backend, provisioner, clock = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    provisioner.confirm()

    provisioner.join("Ferndale-Guest", "guest")
    clock.advance(151)
    provisioner.poll()

    assert backend.profile_name_for("Ferndale-Guest") not in backend.saved_profiles()
    assert backend.profile_name_for("Ferndale") in backend.saved_profiles()


def test_a_network_abandoned_by_a_power_cut_is_not_left_saved(tmp_path):
    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.start_setup_hotspot()
    provisioner.join("Ferndale", "GoodPassword1")

    rebooted = WifiProvisioner(
        backend, tmp_path / "network.json", SETUP_SSID, SETUP_PASSWORD, clock=FakeClock()
    )
    rebooted.recover_after_boot()

    assert backend.saved_profiles() == []
    assert backend.active_connection().is_hotspot is True


def test_rejoining_the_network_that_already_works_never_deletes_it(tmp_path):
    backend, provisioner, clock = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    provisioner.confirm()

    # The same network is applied again and this time nothing confirms it.
    provisioner.join("Ferndale", "GoodPassword1")
    clock.advance(151)
    provisioner.poll()

    assert backend.profile_name_for("Ferndale") in backend.saved_profiles()
    assert backend.active_connection().ssid == "Ferndale"


def test_the_scan_marks_networks_the_enclosure_already_knows(tmp_path):
    """Someone changing network has to tell theirs from the neighbours'."""

    backend, provisioner, _ = build(tmp_path=tmp_path)
    provisioner.join("Ferndale", "GoodPassword1")
    provisioner.confirm()

    listed = {network.ssid: network for network in provisioner.scan()}
    assert listed["Ferndale"].known, "the saved network should be marked"
    assert listed["Ferndale"].in_use
    assert not listed["Neighbour-2G"].known


def test_a_network_saved_by_netplan_counts_as_known(tmp_path):
    """The Pi's original network belongs to netplan, not to Easy Connect.

    Easy Connect must never change those profiles, but leaving them out of the
    list means the network the Pi came on looks like a stranger's.
    """

    backend = home_network_pi(country="US")
    backend._preexisting_ssids = ["Ferndale"]
    _backend, provisioner, _clock = build(backend, tmp_path=tmp_path)

    listed = {network.ssid: network for network in provisioner.scan()}
    assert listed["Ferndale"].known
    assert backend.saved_profiles() == [], "and Easy Connect still owns nothing"


def test_a_backend_that_cannot_list_known_networks_still_returns_the_networks(tmp_path):
    """Losing the marking is a nuisance; losing the list strands the user."""

    backend, provisioner, _ = build(tmp_path=tmp_path)

    def explode():
        raise RuntimeError("nmcli is having a bad day")

    backend.known_ssids = explode
    listed = provisioner.scan()
    assert listed, "the scan should survive a failure to list saved profiles"
    assert not any(network.known for network in listed)

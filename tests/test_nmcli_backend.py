"""The backend that actually runs on the Raspberry Pi.

Everything else in this suite drives the simulated backend, which is
convenient and proves nothing about the code that touches a real radio. These
tests put a recorder in place of ``nmcli`` and check what is asked of it and
what is made of the answers.

The awkward cases are the point: a Wi-Fi name containing a colon, a backslash,
or a non-ASCII character is legal and does occur, and each of them has a way of
corrupting a naive parser.
"""

import subprocess

import pytest

from pitrac_easy_connect.pi import nmcli_backend
from pitrac_easy_connect.pi.backend import SECURITY_OPEN, BackendError
from pitrac_easy_connect.pi.nmcli_backend import NmcliBackend, split_terse


class FakeNmcli:
    """Stands in for the command line. Records calls, returns canned output."""

    def __init__(self):
        self.calls = []
        self.replies = {}
        self.failures = {}
        self.default = ""

    def reply(self, contains, stdout):
        self.replies[contains] = stdout

    def fail(self, contains, message="nmcli said no", code=1):
        self.failures[contains] = (message, code)

    def __call__(self, command, timeout=30.0, check=True, **kwargs):
        joined = " ".join(command)
        self.calls.append(joined)
        for needle, (message, code) in self.failures.items():
            if needle in joined:
                if check:
                    raise BackendError(message)
                return subprocess.CompletedProcess(command, code, "", message)
        for needle, stdout in self.replies.items():
            if needle in joined:
                return subprocess.CompletedProcess(command, 0, stdout, "")
        return subprocess.CompletedProcess(command, 0, self.default, "")

    def asked(self, *fragments):
        return any(all(f in call for f in fragments) for call in self.calls)


@pytest.fixture
def nmcli(monkeypatch):
    fake = FakeNmcli()
    monkeypatch.setattr(nmcli_backend, "_run", fake)
    return fake


@pytest.fixture
def backend(nmcli):
    return NmcliBackend(device="wlan0")


# --- Parsing what nmcli says ----------------------------------------------


def test_a_plain_record_splits_on_colons():
    assert split_terse("Ferndale:82:WPA2:*:5180") == ["Ferndale", "82", "WPA2", "*", "5180"]


def test_a_network_name_containing_a_colon_survives():
    """nmcli escapes it. Splitting on ':' would cut the name in half."""

    assert split_terse(r"Bob\:s Wi-Fi:70:WPA2::2412")[0] == "Bob:s Wi-Fi"


def test_a_network_name_containing_a_backslash_survives():
    assert split_terse(r"Home\\Net:70:WPA2::2412")[0] == "Home\\Net"


def test_an_empty_field_stays_empty():
    assert split_terse("Ferndale:82:::2412") == ["Ferndale", "82", "", "", "2412"]


# --- Scanning --------------------------------------------------------------


def test_a_scan_reads_the_networks(backend, nmcli):
    nmcli.reply("dev wifi list", "\n".join([
        "Ferndale:82:WPA2:*:5180",
        "Neighbour-2G:41:WPA1 WPA2::2412",
        "CoffeeShop:30:::2412",
    ]))
    networks = {n.ssid: n for n in backend.scan()}

    assert set(networks) == {"Ferndale", "Neighbour-2G", "CoffeeShop"}
    assert networks["Ferndale"].in_use is True
    assert networks["Ferndale"].band == "5 GHz"
    assert networks["Neighbour-2G"].band == "2.4 GHz"
    assert networks["CoffeeShop"].security == SECURITY_OPEN


def test_a_scan_asks_for_a_rescan_when_told_to(backend, nmcli):
    backend.scan(rescan=True)
    assert nmcli.asked("dev wifi list", "--rescan yes")
    backend.scan(rescan=False)
    assert nmcli.asked("dev wifi list", "--rescan no")


def test_hidden_networks_are_left_out_of_the_list(backend, nmcli):
    """A hidden network reports an empty name; it has to be typed in."""

    nmcli.reply("dev wifi list", "\n".join([":55:WPA2::2412", "Ferndale:82:WPA2::5180"]))
    assert [n.ssid for n in backend.scan()] == ["Ferndale"]


def test_a_malformed_scan_line_is_skipped_not_fatal(backend, nmcli):
    nmcli.reply("dev wifi list", "\n".join([
        "rubbish", "Ferndale:82:WPA2::5180", "", "also:bad",
    ]))
    assert [n.ssid for n in backend.scan()] == ["Ferndale"]


def test_a_name_with_a_colon_survives_a_scan(backend, nmcli):
    nmcli.reply("dev wifi list", r"Bob\:s Wi-Fi:70:WPA2::2412")
    assert [n.ssid for n in backend.scan()] == ["Bob:s Wi-Fi"]


def test_the_strongest_signal_wins_for_a_repeated_name(backend, nmcli):
    """A mesh reports the same name once per access point."""

    nmcli.reply("dev wifi list", "\n".join([
        "Ferndale:41:WPA2::2412", "Ferndale:88:WPA2::5180",
    ]))
    networks = backend.scan()
    assert len(networks) == 1 and networks[0].signal == 88


# --- Profile naming --------------------------------------------------------


def test_names_that_reduce_to_the_same_slug_get_different_profiles(backend):
    """'Home WiFi' and 'Home_WiFi' both slug to Home_WiFi. Sharing a profile
    means one network's password overwrites the other's."""

    assert backend.profile_name_for("Home WiFi") != backend.profile_name_for("Home_WiFi")


def test_a_profile_name_is_stable_for_the_same_network(backend):
    assert backend.profile_name_for("Ferndale") == backend.profile_name_for("Ferndale")


def test_a_profile_name_is_safe_on_a_command_line(backend):
    name = backend.profile_name_for("Bob:s Wi-Fi \\ Café")
    assert " " not in name and ":" not in name and "\\" not in name
    assert name.startswith(nmcli_backend.PROFILE_PREFIX)


def test_non_ascii_names_do_not_collide(backend):
    assert backend.profile_name_for("Café") != backend.profile_name_for("Cafe")


# --- What the Pi already knows --------------------------------------------


def test_known_ssids_reads_every_wifi_profile_whoever_made_it(backend, nmcli):
    """netplan owns some profiles and Easy-Connect must not touch them, but
    the person choosing a network still wants to see the Pi knows them."""

    nmcli.reply("-f NAME,TYPE con show", "\n".join([
        "netplan-wlan0-TMKH:802-11-wireless",
        "easyconnect-Ferndale-abc12345:802-11-wireless",
        "netplan-eth0:802-3-ethernet",
        "lo:loopback",
    ]))
    nmcli.reply("con show netplan-wlan0-TMKH", "TMKH")
    nmcli.reply("con show easyconnect-Ferndale-abc12345", "Ferndale")

    assert sorted(backend.known_ssids()) == ["Ferndale", "TMKH"]


def test_one_unreadable_profile_does_not_cost_the_whole_list(backend, nmcli):
    nmcli.reply("-f NAME,TYPE con show", "\n".join([
        "good:802-11-wireless", "broken:802-11-wireless",
    ]))
    nmcli.reply("con show good", "Ferndale")
    nmcli.fail("con show broken")
    assert backend.known_ssids() == ["Ferndale"]


def test_saved_profiles_stops_at_our_own(backend, nmcli):
    """This list governs what may be deleted, so it must never include
    netplan's."""

    nmcli.reply("-f NAME con show", "\n".join([
        "netplan-wlan0-TMKH", "easyconnect-Ferndale-abc12345", "easyconnect-setup",
    ]))
    saved = backend.saved_profiles()
    assert saved == ["easyconnect-Ferndale-abc12345"]
    assert not any(name.startswith("netplan") for name in saved)


# --- Connecting ------------------------------------------------------------


def test_connecting_creates_a_profile_brings_it_up_and_waits_for_an_address(backend, nmcli):
    """The whole sequence, including the wait: a profile that comes up without
    an address is a network that has not actually worked."""

    profile = backend.profile_name_for("Ferndale")
    nmcli.reply("NAME,TYPE,DEVICE con show --active",
                "{}:802-11-wireless:wlan0".format(profile))
    nmcli.reply("dev show wlan0", "\n".join([
        "IP4.ADDRESS[1]:10.0.0.51/24",
        "IP4.GATEWAY:10.0.0.1",
        "GENERAL.CONNECTION:{}".format(profile),
    ]))
    nmcli.reply("802-11-wireless.ssid", "Ferndale")

    connection = backend.connect("Ferndale", "GoodPassword1", timeout=5)

    assert connection.profile == profile
    assert connection.ipv4.startswith("10.0.0.51")
    assert nmcli.asked("con add", "Ferndale")
    assert nmcli.asked("con up", profile)
    # The password goes in the profile, never on a command line where it would
    # land in the shell history of anyone debugging.
    assert any("wifi-sec.psk" in call for call in nmcli.calls)


def test_a_profile_that_comes_up_without_an_address_is_torn_down(backend, nmcli):
    """Associated but no DHCP lease is a failed join, not a success."""

    nmcli.reply("NAME,TYPE,DEVICE con show --active", "")
    with pytest.raises(BackendError):
        backend.connect("Ferndale", "GoodPassword1", timeout=2)
    assert nmcli.asked("con down"), "the half-made connection should be taken down"


def test_a_refused_password_is_reported_as_a_backend_error(backend, nmcli):
    nmcli.fail("con up", "Secrets were required, but not provided")
    with pytest.raises(BackendError):
        backend.connect("Ferndale", "wrong-password")


def test_connecting_without_a_name_is_refused_before_anything_runs(backend, nmcli):
    with pytest.raises(BackendError):
        backend.connect("", "password")
    assert not nmcli.calls, "nothing should have been asked of nmcli"


def test_activating_a_profile_asks_for_that_profile(backend, nmcli):
    nmcli.fail("con up", "no such connection")
    with pytest.raises(BackendError):
        backend.activate_profile("easyconnect-Ferndale-abc12345")
    assert nmcli.asked("con up", "easyconnect-Ferndale-abc12345")


# --- Checkpoints -----------------------------------------------------------


def test_a_checkpoint_is_created_with_the_rollback_window(backend, nmcli, monkeypatch):
    monkeypatch.setattr(nmcli_backend, "find_tool", lambda name: "/usr/bin/" + name)
    nmcli.reply("CheckpointCreate", 'o "/org/freedesktop/NetworkManager/Checkpoint/1"')

    handle = backend.create_checkpoint(240)
    assert handle == "/org/freedesktop/NetworkManager/Checkpoint/1"
    assert nmcli.asked("CheckpointCreate", "240"), nmcli.calls


def test_a_machine_without_busctl_simply_has_no_checkpoint(backend, monkeypatch):
    """Losing the checkpoint must not stop a network change; the journal is
    the safety net that actually matters."""

    monkeypatch.setattr(nmcli_backend, "find_tool", lambda name: None)
    assert backend.create_checkpoint(240) is None


# --- The wireless country --------------------------------------------------


def test_the_country_is_read_from_the_radio(backend, nmcli, monkeypatch):
    monkeypatch.setattr(nmcli_backend, "find_tool", lambda name: "/usr/sbin/" + name)
    nmcli.reply("reg get", "global\ncountry US: DFS-FCC\n")
    assert backend.wifi_country() == "US"


def test_an_unset_country_reads_as_empty(backend, nmcli, monkeypatch):
    """00 is the regulatory domain meaning 'nobody has said', and Easy-Connect
    refuses to scan until somebody has."""

    monkeypatch.setattr(nmcli_backend, "find_tool", lambda name: "/usr/sbin/" + name)
    nmcli.reply("reg get", "global\ncountry 00: DFS-UNSET\n")
    assert backend.wifi_country() == ""


def test_no_iw_on_the_machine_reads_as_empty_rather_than_raising(backend, monkeypatch):
    monkeypatch.setattr(nmcli_backend, "find_tool", lambda name: None)
    assert backend.wifi_country() == ""

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

    profile = backend.profile_name_for("Ferndale") + "-new"
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
    # The passphrase is passed to nmcli as an argument. That is briefly
    # visible in the process list, and the comment here used to claim the
    # opposite. Asserting what actually happens keeps the claim honest.
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


# --- A network that has not proved itself ------------------------------------


def test_joining_never_touches_what_was_already_saved(backend, nmcli):
    """Deleting the old profile first meant one mistyped password threw away
    the password that worked."""

    saved = backend.profile_name_for("Ferndale")
    nmcli.fail("con up", "Secrets were required, but not provided")
    with pytest.raises(BackendError):
        backend.connect("Ferndale", "wrong-password")
    for call in nmcli.calls:
        if "con delete" in call or "con modify" in call:
            assert call.split()[3] == saved + "-new", "touched something else: " + call


def test_an_unproved_profile_does_not_reconnect_by_itself(backend, nmcli):
    nmcli.reply("NAME,TYPE,DEVICE con show --active", "")
    with pytest.raises(BackendError):
        backend.connect("Ferndale", "GoodPassword1", timeout=1)
    added = next(call for call in nmcli.calls if "con add" in call)
    assert "connection.autoconnect no" in added


def test_proving_it_reconnects_first_and_renames_last(backend, nmcli):
    """In that order, so a power cut part way through loses nothing."""

    name = backend.profile_name_for("Ferndale")
    nmcli.reply("-f NAME con show", name + "\n" + name + "-new")
    assert backend.adopt("Ferndale", replacing=name) == name
    steps = [c for c in nmcli.calls if "con modify" in c or "con delete" in c]
    assert [" ".join(step.split()[1:5]) for step in steps] == [
        "con modify {}-new connection.autoconnect".format(name),
        "con delete " + name,
        "con modify {}-new connection.id".format(name),
    ]


def test_proving_it_twice_is_harmless(backend, nmcli):
    name = backend.profile_name_for("Ferndale")
    nmcli.reply("-f NAME con show", name)
    assert backend.adopt("Ferndale") == name
    assert not nmcli.asked("con modify") and not nmcli.asked("con delete")


@pytest.mark.parametrize("saved, replacing, keep, expected", [
    ([], "", "", "n"),                       # the first time
    (["n"], "n", "n", "n"),                  # a new password at the same house
    (["n"], "", "n", "n-other"),             # the same name at another house
    (["n", "n-other"], "n-other", "n-other", "n-other"),
    (["n", "n-other"], "", "n", "n-other"),  # a third: the one in use is kept
    (["n", "n-other"], "", "n-other", "n"),
    ([], "netplan-wlan0-x", "", "n"),        # never take over a profile not ours
])
def test_which_place_a_proved_network_takes(saved, replacing, keep, expected):
    from pitrac_easy_connect.pi.nmcli_backend import adopted_name

    assert adopted_name("n", set(saved), replacing, keep) == expected


# --- What routers and people actually use --------------------------------------


@pytest.mark.parametrize("reported, only", [
    ("WPA3", True), ("WPA2 WPA3", False), ("WPA2", False), ("WPA1 WPA2", False), ("", False),
])
def test_a_wpa3_router_is_joined_the_way_it_requires(backend, nmcli, reported, only):
    nmcli.reply("dev wifi list", "Ferndale:80:{}: :5180".format(reported))
    assert backend.scan()[0].wpa3_only is only
    nmcli.fail("con up", "stop here")
    with pytest.raises(BackendError):
        backend.connect("Ferndale", "GoodPassword1", wpa3_only=only)
    added = next(call for call in nmcli.calls if "con add" in call)
    assert ("key-mgmt sae" if only else "key-mgmt wpa-psk") in added


@pytest.mark.parametrize("password", [
    r"back\slash1", r"ends in \\", "  leading spaces", r"looks like \s a space", "caf\u00e9-caf\u00e9",
    'quotes"and;semi#colons',
])
def test_a_password_survives_being_written_down(tmp_path, password):
    """Read back the way NetworkManager does, which gives backslashes a meaning."""

    path = tmp_path / "p.nmconnection"
    path.write_text("[wifi-security]\nkey-mgmt=wpa-psk\n")
    NmcliBackend._write_passphrase(path, password)
    stored = next(line for line in path.read_text(encoding="utf-8").splitlines()
                  if line.startswith("psk="))[4:]
    assert not stored.startswith(" "), "a keyfile drops leading spaces"
    out, escaped = [], False
    for character in stored:
        if escaped:
            out.append({"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}[character])
            escaped = False
        elif character == "\\":
            escaped = True
        else:
            out.append(character)
    assert "".join(out) == password


def test_the_hotspot_knows_whether_anybody_is_on_it(backend, nmcli, monkeypatch):
    monkeypatch.setattr(nmcli_backend, "find_tool", lambda name: "/usr/sbin/iw")
    nmcli.reply("station dump", "Station aa:bb:cc:dd:ee:ff (on wlan0)\n\tinactive time: 4 ms\n"
                                "Station 11:22:33:44:55:66 (on wlan0)\n")
    assert backend.hotspot_clients() == 2
    monkeypatch.setattr(nmcli_backend, "find_tool", lambda name: None)
    assert backend.hotspot_clients() is None


# --- Asking the system less often -------------------------------------------
#
# A refresh used to ask NetworkManager about the active connection about
# fifteen times and open the camera stack with rpicam-hello every few seconds,
# which can contend with PiTrac for the cameras it is measuring with.


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(nmcli_backend.time, "monotonic", fake)
    return fake


def test_the_active_connection_is_asked_once_per_refresh_not_per_question(backend, nmcli, clock):
    for _ in range(10):
        backend.active_connection()
    asked = len(nmcli.calls)
    assert asked <= 3, "ten questions in one moment should cost one lookup"
    clock.now += nmcli_backend.NETWORK_SECONDS + 0.1
    backend.active_connection()
    assert len(nmcli.calls) > asked, "an old answer must be asked again"


def test_changing_the_network_forgets_what_was_remembered(backend, nmcli, clock):
    backend.active_connection()
    before = len(nmcli.calls)
    backend.forget_profile("easyconnect-Ferndale")
    after_change = len(nmcli.calls)
    backend.active_connection()
    assert len(nmcli.calls) > after_change > before


def test_the_cameras_are_not_reopened_every_few_seconds(backend, nmcli, clock, monkeypatch):
    nmcli.reply("--list-cameras", "Available cameras\n0 : imx296 [1456x1088]\n1 : imx296 [1456x1088]\n")
    monkeypatch.setattr(nmcli_backend, "find_tool", lambda name: "/usr/bin/" + name)
    for _ in range(5):
        assert len(backend.cameras()) == 2
        clock.now += 5
    assert sum("--list-cameras" in call for call in nmcli.calls) == 1


def test_while_pitrac_measures_its_cameras_are_left_alone(backend, nmcli, clock, monkeypatch):
    nmcli.reply("--list-cameras", "0 : imx296 [1456x1088]\n1 : imx296 [1456x1088]\n")
    monkeypatch.setattr(nmcli_backend, "find_tool", lambda name: "/usr/bin/" + name)
    backend.cameras()
    clock.now += nmcli_backend.CAMERAS_FOUND_SECONDS + 1
    monkeypatch.setattr(NmcliBackend, "process_running", lambda self, pattern: pattern == "pitrac_lm")
    assert len(backend.cameras()) == 2
    assert sum("--list-cameras" in call for call in nmcli.calls) == 1
    clock.now += nmcli_backend.CAMERAS_IN_USE_SECONDS
    backend.cameras()
    assert sum("--list-cameras" in call for call in nmcli.calls) == 2

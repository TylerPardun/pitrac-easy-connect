"""Where the Wi-Fi passphrase goes.

Everything handed to nmcli lands in the process list, where any local account
can read it out of /proc. The passphrase goes into the profile's own file
instead, which NetworkManager creates owned by root and readable only by root.

The mechanism was checked against a real Raspberry Pi running NetworkManager
1.52.1: a profile added without a psk, the secret written into its keyfile, and
`nmcli con load` afterwards leaves psk-flags at 0 -- stored, so the enclosure
still rejoins the network by itself after a power cut.
"""

import os
import stat
from pathlib import Path
from unittest import mock

import pytest

from pitrac_easy_connect.pi.nmcli_backend import NmcliBackend

#: Exactly what the Pi answers, including the /run path netplan's profiles use.
REAL_LISTING = (
    "netplan-wlan0-TMKH:/run/NetworkManager/system-connections/netplan-wlan0-TMKH.nmconnection\n"
    "lo:/run/NetworkManager/system-connections/lo.nmconnection\n"
    "netplan-eth0:/run/NetworkManager/system-connections/netplan-eth0.nmconnection\n"
)

KEYFILE = """[connection]
id=pitrac-Home-1a2b3c4d
type=wifi

[wifi]
ssid=Home

[wifi-security]
key-mgmt=wpa-psk
"""


class Result:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.returncode = 0


def test_the_passphrase_is_never_given_to_nmcli(tmp_path):
    """The whole point: it must not appear in any argument list."""

    backend = NmcliBackend()
    keyfile = tmp_path / "pitrac-Home-1a2b3c4d.nmconnection"
    keyfile.write_text(KEYFILE)

    calls = []

    def fake_nmcli(*args, **kwargs):
        calls.append(args)
        if args[:4] == ("-t", "-f", "NAME,FILENAME", "con"):
            return Result("pitrac-Home-1a2b3c4d:{}\n".format(keyfile))
        return Result()

    with mock.patch.object(backend, "_nmcli", side_effect=fake_nmcli):
        backend._store_passphrase("pitrac-Home-1a2b3c4d", "hunter2-the-real-one")

    flat = " ".join(part for call in calls for part in call)
    assert "hunter2-the-real-one" not in flat, "the passphrase reached a command line"
    assert "psk=hunter2-the-real-one" in keyfile.read_text()
    assert ("con", "load", str(keyfile)) == calls[-1][:3]


def test_the_keyfile_is_readable_only_by_root(tmp_path):
    keyfile = tmp_path / "profile.nmconnection"
    keyfile.write_text(KEYFILE)
    NmcliBackend._write_passphrase(keyfile, "secret")
    assert stat.S_IMODE(keyfile.stat().st_mode) == 0o600


def test_a_second_join_replaces_the_passphrase_rather_than_adding_one(tmp_path):
    keyfile = tmp_path / "profile.nmconnection"
    keyfile.write_text(KEYFILE)
    NmcliBackend._write_passphrase(keyfile, "first")
    NmcliBackend._write_passphrase(keyfile, "second")
    body = keyfile.read_text()
    assert body.count("psk=") == 1
    assert "psk=second" in body


def test_a_keyfile_without_the_security_section_still_gets_one(tmp_path):
    keyfile = tmp_path / "profile.nmconnection"
    keyfile.write_text("[connection]\nid=x\n\n[wifi]\nssid=Home\n")
    NmcliBackend._write_passphrase(keyfile, "secret")
    body = keyfile.read_text()
    assert "[wifi-security]" in body and "psk=secret" in body


def test_no_readable_copy_is_left_behind(tmp_path):
    keyfile = tmp_path / "profile.nmconnection"
    keyfile.write_text(KEYFILE)
    NmcliBackend._write_passphrase(keyfile, "secret")
    assert [p.name for p in tmp_path.iterdir()] == ["profile.nmconnection"]


def test_the_profile_file_is_found_in_a_real_listing(tmp_path):
    backend = NmcliBackend()
    real = tmp_path / "netplan-wlan0-TMKH.nmconnection"
    real.write_text(KEYFILE)
    listing = REAL_LISTING.replace(
        "/run/NetworkManager/system-connections/netplan-wlan0-TMKH.nmconnection", str(real)
    )
    with mock.patch.object(backend, "_nmcli", return_value=Result(listing)):
        assert backend._profile_file("netplan-wlan0-TMKH") == real
        assert backend._profile_file("not-a-profile") is None


def test_a_network_name_containing_a_colon_is_not_split_apart(tmp_path):
    """nmcli escapes colons inside a field; a plain split corrupts the path."""

    backend = NmcliBackend()
    keyfile = tmp_path / "odd.nmconnection"
    keyfile.write_text(KEYFILE)
    listing = "pitrac-Cafe\\:Wifi-1a2b3c4d:{}\n".format(keyfile)
    with mock.patch.object(backend, "_nmcli", return_value=Result(listing)):
        assert backend._profile_file("pitrac-Cafe:Wifi-1a2b3c4d") == keyfile


def test_connecting_still_works_when_the_file_cannot_be_written(tmp_path):
    """Wi-Fi matters more than the exposure; it falls back rather than fails."""

    backend = NmcliBackend()
    calls = []

    def fake_nmcli(*args, **kwargs):
        calls.append(args)
        return Result("")          # no FILENAME for this profile

    with mock.patch.object(backend, "_nmcli", side_effect=fake_nmcli):
        backend._store_passphrase("pitrac-Home-1a2b3c4d", "fallback-secret")

    assert any("wifi-sec.psk" in call for call in calls), "it must still set the key"


def test_the_join_itself_hands_nmcli_no_secret(tmp_path):
    """End to end through connect(), which is what the portal calls."""

    backend = NmcliBackend()
    seen = []

    def fake_nmcli(*args, **kwargs):
        seen.append(args)
        return Result("")

    with mock.patch.object(backend, "_nmcli", side_effect=fake_nmcli), \
         mock.patch.object(backend, "_wait_for_address",
                           return_value=mock.Mock(profile="x", ipv4="10.0.0.5")), \
         mock.patch.object(backend, "_store_passphrase") as stored:
        backend.connect("Home", "correct-horse-battery-staple")

    flat = " ".join(part for call in seen for part in call)
    assert "correct-horse-battery-staple" not in flat
    assert stored.called, "the passphrase must still be stored somewhere"

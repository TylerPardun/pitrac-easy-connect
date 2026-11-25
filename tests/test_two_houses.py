"""Carrying one enclosure between houses, and everything that goes wrong.

The same calls the app and the setup page make, against a simulated radio that
behaves the way a real one does where it matters: it cannot scan while it is
being a hotspot, a profile remembers the password it was saved with rather than
whatever the router wants today, and trying a network takes the radio off the
one it was on.
"""

import threading
import time

import pytest

from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.common.states import State
from pitrac_easy_connect.pi.backend import ActiveConnection
from pitrac_easy_connect.pi.portal import PortalHandler
from pitrac_easy_connect.pi.service import PiService, ServicePaths
from pitrac_easy_connect.pi.simulated import FakeAccessPoint, SimulatedPi
from pitrac_easy_connect.pi.wifi import (
    LOST_NETWORK_SECONDS,
    RETRY_SECONDS,
    WATCH_SECONDS,
    NetworkMode,
    WifiProvisioner,
)
from pitrac_easy_connect.models import Simulator

from pitrac_fixture import make_pitrac

HOUSE_A = FakeAccessPoint("House A", password="password-a")
HOUSE_B = FakeAccessPoint("House B", password="password-b")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Enclosure:
    """One enclosure that can be carried about, switched off, and waited on."""

    def __init__(self, tmp_path, *in_range):
        self.path = tmp_path / "network.json"
        self.radio = SimulatedPi(country="US")
        self.clock = Clock()
        self.go_to(*in_range)
        self.start()

    def start(self):
        self.wifi = WifiProvisioner(
            self.radio, self.path, "PiTrac-TEST", "setup-password",
            clock=self.clock, sleep=self.clock.advance,
        )
        return self.wifi.recover_after_boot()

    def go_to(self, *in_range):
        self.radio.access_points = list(in_range)

    def restart(self):
        self.radio.power_cycle()
        return self.start()

    def join(self, ssid, password):
        result = self.wifi.join(ssid, password)
        if result.ok:
            self.wifi.confirm()
        return result

    def wait(self, seconds):
        for _ in range(int(seconds / 2)):
            self.clock.advance(2)
            self.wifi.poll()

    @property
    def on(self):
        current = self.radio.active_connection()
        return None if current is None else "hotspot" if current.is_hotspot else current.ssid


# --- Moving between houses ----------------------------------------------------


def test_the_acceptance_test_two_houses_and_back(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    assert enclosure.on == "hotspot", "new, so it asks to be set up"
    assert enclosure.join("House A", "password-a").ok
    enclosure.restart()
    assert enclosure.on == "House A"

    enclosure.go_to(HOUSE_B)
    enclosure.restart()
    assert enclosure.on == "hotspot", "somewhere new, so it asks again"
    assert enclosure.join("House B", "password-b").ok

    for house, name in ((HOUSE_A, "House A"), (HOUSE_B, "House B"), (HOUSE_A, "House A")):
        enclosure.go_to(house)
        enclosure.restart()
        assert enclosure.on == name, "both houses are remembered"


def test_two_houses_whose_routers_have_the_same_name(tmp_path):
    here = FakeAccessPoint("NETGEAR", password="password-a")
    there = FakeAccessPoint("NETGEAR", password="password-b")
    enclosure = Enclosure(tmp_path, here)
    enclosure.join("NETGEAR", "password-a")
    enclosure.go_to(there)
    enclosure.restart()
    assert enclosure.on == "hotspot"
    enclosure.join("NETGEAR", "password-b")

    for router in (here, there, here):
        enclosure.go_to(router)
        enclosure.restart()
        assert enclosure.on == "NETGEAR", "one house's password was lost to the other's"


def test_a_new_password_at_the_same_house_replaces_the_old_one(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.join("House A", "password-a")
    HOUSE = FakeAccessPoint("House A", password="password-changed")
    enclosure.go_to(HOUSE)
    enclosure.join("House A", "password-changed")
    assert len(enclosure.radio.saved_profiles()) == 1
    enclosure.restart()
    assert enclosure.on == "House A"


def test_a_saved_network_can_be_chosen_without_typing_it_again(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A, HOUSE_B)
    enclosure.join("House A", "password-a")
    enclosure.join("House B", "password-b")
    assert enclosure.join("House A", None).ok
    assert enclosure.on == "House A"
    assert len(enclosure.radio.saved_profiles()) == 2


# --- Mistakes --------------------------------------------------------------------


def test_one_wrong_password_does_not_cost_the_right_one(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.join("House A", "password-a")
    assert enclosure.wifi.join("House A", "typed-it-wrong").ok is False
    assert enclosure.on == "House A"
    enclosure.restart()
    assert enclosure.on == "House A", "the password that worked was thrown away"


def test_an_unconfirmed_move_goes_back_by_itself(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A, HOUSE_B)
    enclosure.join("House A", "password-a")
    enclosure.wifi.join("House B", "password-b")
    enclosure.wait(160)
    assert enclosure.on == "House A"
    assert len(enclosure.radio.saved_profiles()) == 1


@pytest.mark.parametrize("rejoins", [True, False])
def test_power_lost_before_confirming_goes_back(tmp_path, rejoins):
    enclosure = Enclosure(tmp_path, HOUSE_A, HOUSE_B)
    enclosure.join("House A", "password-a")
    enclosure.wifi.join("House B", "password-b")
    enclosure.radio.power_cycle(rejoins)
    enclosure.start()
    assert enclosure.on == "House A"


def test_power_lost_while_settling_keeps_the_network_that_was_proved(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.wifi.join("House A", "password-a")
    enclosure.radio.fail_next_operation = "adopt"
    assert enclosure.wifi.confirm().ok
    enclosure.radio.power_cycle(rejoins=False)
    enclosure.start()
    assert enclosure.on == "House A"
    assert [p for p in enclosure.radio.saved_profiles() if p.endswith("-new")] == []


@pytest.mark.parametrize("password", ["short", "x" * 64, "line\nbreak"])
def test_a_password_no_router_could_have_is_refused_before_anything_moves(tmp_path, password):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.join("House A", "password-a")
    with pytest.raises(EasyConnectError):
        enclosure.wifi.join("House A", password)
    assert enclosure.on == "House A"


# --- Direct Mode -------------------------------------------------------------------


def test_direct_mode_survives_a_restart_beside_a_saved_router(tmp_path):
    """It rejoined the house while everything on screen still said Direct Mode."""

    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.join("House A", "password-a")
    enclosure.wifi.set_direct_mode(True)
    enclosure.restart()
    assert enclosure.on == "hotspot"
    assert enclosure.wifi.mode is NetworkMode.DIRECT
    enclosure.wait(3600)
    assert enclosure.on == "hotspot", "and it stays there"


def test_direct_mode_is_held_if_something_else_moves_the_radio(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.join("House A", "password-a")
    enclosure.wifi.set_direct_mode(True)
    enclosure.radio.stop_hotspot()
    enclosure.radio.activate_profile(enclosure.radio.saved_profiles()[0])
    enclosure.wait(WATCH_SECONDS * 2)
    assert enclosure.on == "hotspot"


def test_leaving_direct_mode_goes_home(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.join("House A", "password-a")
    enclosure.wifi.set_direct_mode(True)
    enclosure.wifi.set_direct_mode(False)
    assert enclosure.on == "House A"
    enclosure.restart()
    assert enclosure.on == "House A"


def test_joining_a_network_is_leaving_direct_mode(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.wifi.set_direct_mode(True)
    enclosure.join("House A", "password-a")
    enclosure.wait(WATCH_SECONDS * 4)
    assert enclosure.on == "House A"
    assert enclosure.wifi.direct_mode is False


def test_a_new_owner_is_not_handed_somebody_elses_direct_mode(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.wifi.set_direct_mode(True)
    enclosure.wifi.forget_all_networks()
    enclosure.restart()
    assert enclosure.wifi.mode is NetworkMode.SETUP_HOTSPOT


# --- Routers that come and go ---------------------------------------------------------


def test_a_router_slower_to_start_than_the_enclosure_is_found_again(tmp_path):
    """After a power cut it is always slower. This used to need a restart."""

    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.join("House A", "password-a")
    enclosure.go_to()
    enclosure.restart()
    assert enclosure.on == "hotspot"
    enclosure.go_to(HOUSE_A)
    enclosure.wait(RETRY_SECONDS[0] + WATCH_SECONDS * 3)
    assert enclosure.on == "House A"


def test_nobody_is_cut_off_while_using_the_hotspot(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.join("House A", "password-a")
    enclosure.go_to()
    enclosure.restart()
    enclosure.go_to(HOUSE_A)

    enclosure.radio.stations = 1
    enclosure.wait(2000)
    assert enclosure.on == "hotspot"

    enclosure.radio.stations = None    # cannot tell, so ask the service
    enclosure.wifi.hotspot_in_use = lambda: True
    enclosure.wait(2000)
    assert enclosure.on == "hotspot"

    enclosure.wifi.hotspot_in_use = lambda: False
    enclosure.wait(700)
    assert enclosure.on == "House A"


def test_the_hotspot_comes_straight_back_when_home_is_not_there(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.join("House A", "password-a")
    enclosure.go_to(HOUSE_B)
    enclosure.restart()
    down = []
    real = enclosure.radio.stop_hotspot
    enclosure.radio.stop_hotspot = lambda: (down.append(1), real())
    enclosure.wait(3600)
    assert enclosure.on == "hotspot"
    assert 2 <= len(down) <= 10, "looked {} times in an hour".format(len(down))


def test_a_router_that_restarts_is_waited_for(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A)
    enclosure.join("House A", "password-a")
    enclosure.radio._active = None
    enclosure.go_to()
    enclosure.wait(LOST_NETWORK_SECONDS - 30)
    assert enclosure.on is None, "gave up on a router that was only restarting"
    enclosure.wait(60)
    assert enclosure.on == "hotspot"


def test_a_hotspot_that_would_not_start_is_tried_again(tmp_path):
    enclosure = Enclosure(tmp_path)
    enclosure.radio.power_cycle()
    enclosure.radio.fail_next_operation = "hotspot"
    enclosure.start()
    assert enclosure.on is None
    enclosure.wait(LOST_NETWORK_SECONDS + WATCH_SECONDS * 3)
    assert enclosure.on == "hotspot", "an enclosure nobody could ever reach"


# --- Choosing a network while standing at the hotspot ------------------------------------


def test_the_list_is_there_although_the_radio_cannot_look(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A, HOUSE_B)
    assert enclosure.on == "hotspot"
    assert enclosure.radio.scan() == [], "a hotspot cannot scan"
    assert sorted(n.ssid for n in enclosure.wifi.scan()) == ["House A", "House B"]


def test_the_list_marks_what_is_already_known(tmp_path):
    enclosure = Enclosure(tmp_path, HOUSE_A, HOUSE_B)
    enclosure.join("House A", "password-a")
    enclosure.wifi.start_setup_hotspot()
    assert {n.ssid: (n.known, n.in_use) for n in enclosure.wifi.scan()} == {
        "House A": (True, False), "House B": (False, False)}


# --- Answering while it happens --------------------------------------------------------------


def test_the_setup_page_answers_while_the_radio_is_still_trying(tmp_path):
    """It took most of a minute to answer anything, so installing over a cable
    was declared a failure and put back."""

    radio = SimulatedPi(country="US")
    release = threading.Event()
    real = radio.active_connection

    def slow_hotspot(*args, **kwargs):
        release.wait(10)
        return SimulatedPi.start_hotspot(radio, *args, **kwargs)

    radio.start_hotspot = slow_hotspot
    service = PiService(
        radio, ServicePaths(tmp_path / "state"), make_pitrac(tmp_path),
        {Simulator.GSPRO: 0, Simulator.E6: 0}, 0, 0, manage_hostname=False, boot_grace=0.0,
    )
    began = time.monotonic()
    service.start(wait_for_network=False)
    try:
        status = service.status()
        assert time.monotonic() - began < 5
        assert status["version"]
        assert service.link_server.listening and service.relay.listening
        assert service.state is State.STARTING, "it has not failed, it has not finished"
        release.set()
        deadline = time.monotonic() + 5
        while real() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert real().is_hotspot
        service.refresh()
        assert service.state is State.SETUP_REQUIRED
    finally:
        release.set()
        service.stop()


# --- Who is standing next to it ---------------------------------------------------------------


class Request:
    """As much of a request as deciding where it came from needs."""

    def __init__(self, backend, caller, local):
        class Service:
            pass

        class Connection:
            @staticmethod
            def getsockname():
                return (local, 80)

        self._svc = Service()
        self._svc.backend = backend
        self.connection = Connection()
        self.client_address = (caller, 50000)

    def _service(self):
        return self._svc


class RealRadio(SimulatedPi):
    simulated = False


@pytest.mark.parametrize("caller, local, allowed", [
    ("10.42.0.57", "10.42.0.1", True),        # on the enclosure's own Wi-Fi
    ("192.168.1.20", "192.168.1.9", False),   # the household network, by cable
    ("192.168.1.20", "10.42.0.1", False),     # reaching across from it
    ("10.42.0.57", "192.168.1.9", False),
    ("127.0.0.1", "127.0.0.1", False),
    ("10.42.0.1", "10.42.0.1", False),        # the enclosure itself
])
def test_only_the_enclosures_own_wifi_counts_as_being_there(caller, local, allowed):
    """With a cable in, anybody on the household network counted too, for as
    long as the hotspot happened to be on."""

    radio = RealRadio(country="US")
    radio.start_hotspot("PiTrac-TEST", "setup-password")
    request = Request(radio, caller, local)
    assert PortalHandler._on_setup_network(request) is allowed


def test_nobody_is_there_when_the_hotspot_is_off():
    radio = RealRadio(country="US")
    radio.add_network("House A", password="password-a")
    radio.save_network("House A", "password-a")
    assert PortalHandler._on_setup_network(Request(radio, "10.0.0.5", "10.0.0.201")) is False


@pytest.mark.parametrize("via, confirmed", [
    ("10.0.0.201", True), ("192.168.1.9", False), ("127.0.0.1", False),
])
def test_arriving_by_cable_does_not_prove_the_wifi(tmp_path, via, confirmed):
    radio = RealRadio(country="US")
    radio.access_points = [HOUSE_A]
    clock = Clock()
    wifi = WifiProvisioner(radio, tmp_path / "n.json", "PiTrac-TEST", "setup-password",
                           clock=clock, sleep=clock.advance)
    wifi.recover_after_boot()
    wifi.join("House A", "password-a")
    if confirmed:
        assert wifi.confirm(via).ok
    else:
        with pytest.raises(EasyConnectError):
            wifi.confirm(via)
        assert wifi.awaiting_confirmation is True, "the window stays open"
        clock.advance(200)
        wifi.poll()
        assert radio.active_connection().is_hotspot


def test_the_address_compared_is_the_one_without_its_prefix():
    assert ActiveConnection("p", "s", "10.0.0.201/24", "").ipv4.split("/")[0] == "10.0.0.201"

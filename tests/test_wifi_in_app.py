"""Wi-Fi setup without leaving the app.

The one thing the app cannot do is put the computer itself on another network,
so that is the only thing it asks somebody to go and do.
"""

import time

import pytest

from pitrac_easy_connect.companion.page import PAGE
from pitrac_easy_connect.companion.service import COMMAND_TIMEOUTS, SETUP_ADDRESS
from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.pi.service import SLOW_COMMANDS

from test_companion import Rig


@pytest.fixture
def rig(tmp_path):
    built = Rig(tmp_path)
    built.companion.select_simulator("local")
    built.pair()
    assert built.wait_linked() is True
    yield built
    built.close()


def network(rig):
    return rig.companion.status()["enclosure"]["network"]


def wait_for(condition, seconds=8.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not condition():
        time.sleep(0.05)
    return bool(condition())


# --- Over the link -------------------------------------------------------------


def test_the_app_can_see_that_wifi_is_needed(rig):
    assert network(rig)["connection"]["isHotspot"] is True
    assert network(rig)["country"] == "US"


def test_the_networks_are_listed_over_the_link(rig):
    listed = rig.companion.command("scanNetworks")["networks"]
    assert {"Ferndale", "CoffeeShop"} <= {n["ssid"] for n in listed}


def test_the_whole_setup_happens_over_the_link(rig):
    joined = rig.companion.command(
        "joinNetwork", {"ssid": "Ferndale", "password": "GoodPassword1"})
    assert joined["ok"] is True
    assert wait_for(lambda: network(rig)["connection"]["ssid"] == "Ferndale")
    assert network(rig)["awaitingConfirmation"] is True

    # The computer follows it to the new network.
    rig.companion.disconnect()
    rig.companion.connect(rig.pi.identity.device_id)
    assert rig.wait_linked(timeout=10)
    assert wait_for(lambda: network(rig)["awaitingConfirmation"] is False)


def test_a_wrong_password_is_told_apart_from_everything_else(rig):
    answer = rig.companion.command(
        "joinNetwork", {"ssid": "Ferndale", "password": "wrong-password"})
    assert answer["ok"] is False
    assert answer["error"]["code"] == "PT-NET-001"
    assert wait_for(lambda: network(rig)["connection"]["isHotspot"] is True)


def test_the_country_is_known_as_soon_as_it_is_chosen(rig):
    rig.pi.backend.country = ""
    rig.pi.refresh()
    assert wait_for(lambda: network(rig)["country"] == "")
    rig.companion.command("setCountry", {"country": "CA"})
    assert wait_for(lambda: network(rig)["country"] == "CA", 2)


def test_direct_mode_is_known_as_soon_as_it_is_chosen(rig):
    rig.companion.command("setDirectMode", {"enabled": True})
    assert wait_for(lambda: network(rig)["directMode"] is True, 2)


def test_the_link_stays_up_while_a_radio_takes_its_time(rig, monkeypatch):
    """A session that answers nothing for that long is taken to be gone."""

    real = rig.pi.provisioner.join
    monkeypatch.setattr(rig.pi.provisioner, "join",
                        lambda *a, **k: (time.sleep(3), real(*a, **k))[1])
    import threading

    done = []
    threading.Thread(target=lambda: done.append(rig.companion.command(
        "joinNetwork", {"ssid": "Ferndale", "password": "GoodPassword1"})), daemon=True).start()
    time.sleep(0.5)
    began = time.monotonic()
    assert rig.companion.command("trustedComputers")["computers"]
    assert time.monotonic() - began < 2, "everything else waited for the radio"
    assert wait_for(lambda: done and done[0]["ok"])


def test_losing_the_link_in_the_middle_of_joining_is_not_a_crash(rig, monkeypatch):
    real = rig.pi.provisioner.join

    def join_and_vanish(*args, **kwargs):
        result = real(*args, **kwargs)
        rig.pi.link_server.session.close()
        return result

    monkeypatch.setattr(rig.pi.provisioner, "join", join_and_vanish)
    with pytest.raises(EasyConnectError) as caught:
        rig.companion.command("joinNetwork", {"ssid": "Ferndale", "password": "GoodPassword1"})
    assert caught.value.info.code.startswith("PT-LINK"), "the page reads this as having worked"
    assert wait_for(lambda: rig.companion.status()["link"]["connected"], 12)
    assert wait_for(lambda: network(rig)["awaitingConfirmation"] is False)
    assert network(rig)["connection"]["ssid"] == "Ferndale"


def test_everything_slow_is_given_long_enough_and_its_own_thread():
    for name in ("scanNetworks", "joinNetwork", "setDirectMode"):
        assert COMMAND_TIMEOUTS[name] >= 60
        assert name in SLOW_COMMANDS
    assert COMMAND_TIMEOUTS["joinNetwork"] > 45 + 30, "shorter than a radio is allowed to take"


def test_a_paired_computer_looks_for_it_on_its_own_wifi(rig):
    """Somewhere new, that is the only place it is."""

    assert SETUP_ADDRESS in rig.companion._link._hosts


# --- In the window ----------------------------------------------------------------


def test_nobody_is_sent_to_a_browser():
    assert "http://10.42.0.1" not in PAGE
    help_text = PAGE.split("const CANNOT_FIND=`")[1].split("`;")[0]
    assert "open" not in help_text.lower().replace("open the wi-fi menu", "")


def test_wifi_comes_before_anything_that_needs_it():
    for view in ("function wizardView(data){", "function present(data){"):
        body = PAGE.split(view)[1].split("\n}")[0]
        assert body.index("wifiView(data)") < body.index("needs attention")


def test_every_step_of_wifi_offers_a_way_on_or_is_waiting_for_the_radio():
    body = PAGE.split("function wifiView(data){")[1].split("\nfunction ")[0]
    views = body.split("return {")[1:]
    assert len(views) == 5
    for view in views:
        assert "actions:[" in view
        if 'wifi:"joining"' not in view:
            assert "actions:[]" not in view


def test_the_password_is_hidden_until_asked_for():
    assert 'type="password" id="wifiPassword"' in PAGE


def test_a_saved_network_does_not_ask_for_its_password_again():
    assert "if(picked.known || !picked.needsPassword) return joinWifi(picked.ssid" in PAGE

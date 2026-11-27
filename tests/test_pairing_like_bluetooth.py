"""Computers pair with PiTrac the way devices pair over Bluetooth.

PiTrac is put into pairing mode -- from a computer it already knows, or with
the owner card -- and the computer that pairs during it is the one connected.
PiTrac talks to one computer at a time and remembers the others. Any of those
can take it back, but only when someone at that computer chooses to; nothing
moves it on its own, so two computers that both remember it never fight.
"""

import time

import pytest

from pitrac_easy_connect.common.errors import (
    LINK_BUSY,
    LINK_TAKEN_OVER,
    PAIR_NOT_ACCEPTING,
    PAIR_OWNER_CARD_WRONG,
    EasyConnectError,
)
from pitrac_easy_connect.common.states import State
from pitrac_easy_connect.companion.service import CompanionService
from test_companion import Rig


def wait_for(check, timeout=10.0, what="the condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.05)
    raise AssertionError("timed out waiting for " + what)


def linked(companion):
    return bool(companion.status()["link"]["connected"])


def link_error(companion):
    return (companion.status()["link"].get("lastError") or {}).get("code")


@pytest.fixture
def rig(tmp_path):
    built = Rig(tmp_path)
    # On the house Wi-Fi, as a real enclosure is. Its own setup network would
    # count as standing next to it, and open pairing mode for anyone.
    built.pi.provisioner.join("Ferndale", "GoodPassword1")
    assert not built.pi.backend.active_connection().is_hotspot
    second = CompanionService(
        config_path=tmp_path / "second.json",
        simulator_ports={},
        discovery_port=built.pi.discovery.port,
        computer_name="Den PC",
        discovery_targets=["127.0.0.1"],
    )
    built.second = second
    yield built
    second.close()
    built.close()


def pair_second(rig, **kwargs):
    for _attempt in range(30):
        found = rig.second.search(timeout=0.5)
        if any(item["deviceId"] == rig.pi.identity.device_id for item in found):
            break
        time.sleep(0.1)
    return rig.second.pair(
        rig.pi.identity.device_id, portal_port=rig.portal_port, **kwargs
    )


def test_a_new_computer_with_the_owner_card_pairs_and_is_the_one_connected(rig):
    rig.pair()
    wait_for(lambda: linked(rig.companion), what="the first computer to connect")

    pair_second(rig, owner_card_password=rig.pi.identity.setup_password)

    wait_for(lambda: linked(rig.second), what="the new computer to connect")
    wait_for(lambda: not linked(rig.companion), what="the first computer to let go")
    assert link_error(rig.companion) == LINK_TAKEN_OVER.code
    assert rig.companion.status()["state"] == State.ANOTHER_COMPUTER_CONNECTED.value
    # Both are remembered.
    assert rig.pi.pairings.count == 2


def test_a_computer_paired_from_pairing_mode_is_the_one_connected(rig):
    """Pair another computer on the connected one, then pair: the new one connects."""

    rig.pair()
    wait_for(lambda: linked(rig.companion), what="the first computer to connect")
    rig.companion.command("openPairing")

    pair_second(rig)

    wait_for(lambda: linked(rig.second), what="the new computer to connect")
    wait_for(lambda: not linked(rig.companion), what="the first computer to let go")


def test_the_computer_let_go_does_not_take_pitrac_back_by_itself(rig):
    rig.pair()
    wait_for(lambda: linked(rig.companion))
    pair_second(rig, owner_card_password=rig.pi.identity.setup_password)
    wait_for(lambda: linked(rig.second))

    # Longer than several reconnect intervals.
    time.sleep(3 * rig.companion._link.reconnect_seconds + 1.0)
    assert linked(rig.second)
    assert not linked(rig.companion)


def test_a_remembered_computer_takes_pitrac_back_when_chosen(rig):
    rig.pair()
    wait_for(lambda: linked(rig.companion))
    pair_second(rig, owner_card_password=rig.pi.identity.setup_password)
    wait_for(lambda: linked(rig.second))

    rig.companion.connect(rig.pi.identity.device_id, take_over=True)

    wait_for(lambda: linked(rig.companion), what="the first computer to take it back")
    wait_for(lambda: not linked(rig.second), what="the second computer to let go")
    assert link_error(rig.second) == LINK_TAKEN_OVER.code


def test_a_remembered_computer_that_did_not_choose_is_told_pitrac_is_busy(rig):
    rig.pair()
    wait_for(lambda: linked(rig.companion))
    pair_second(rig, owner_card_password=rig.pi.identity.setup_password)
    wait_for(lambda: linked(rig.second))

    # An ordinary start-up connection, the kind a computer makes on its own.
    rig.companion.connect(rig.pi.identity.device_id)

    wait_for(lambda: link_error(rig.companion) == LINK_BUSY.code, what="busy")
    assert linked(rig.second)
    assert rig.companion.status()["state"] == State.ANOTHER_COMPUTER_CONNECTED.value


def test_a_wrong_owner_card_password_pairs_nothing(rig):
    rig.pair()
    with pytest.raises(EasyConnectError) as caught:
        pair_second(rig, owner_card_password="not-the-password")
    assert caught.value.info.code == PAIR_OWNER_CARD_WRONG.code
    assert rig.pi.pairings.count == 1
    assert not rig.pi.pairings.accepting()


def test_without_pairing_mode_a_new_computer_is_still_refused(rig):
    rig.pair()
    with pytest.raises(EasyConnectError) as caught:
        pair_second(rig)
    assert caught.value.info.code == PAIR_NOT_ACCEPTING.code
    assert rig.pi.pairings.count == 1

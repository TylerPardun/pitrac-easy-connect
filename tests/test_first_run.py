"""The first run has to lead, and afterwards it has to get out of the way.

Someone who has never seen this before should be able to press the one button
offered, five times, and be playing. Someone who has already set it up should
never see those steps again.
"""

from pathlib import Path

import pytest

from test_companion import rig  # noqa: F401  (fixture)

PAGE = (
    Path(__file__).resolve().parent.parent
    / "src" / "pitrac_easy_connect" / "companion" / "page.py"
).read_text()


def wizard_source():
    return PAGE.split("function wizardView(")[1].split("function renderWizard(")[0]


# --- what the app remembers ------------------------------------------------


def test_a_new_install_starts_in_guided_setup(rig):
    assert rig.companion.status()["setupComplete"] is False


def test_finishing_setup_sticks(rig):
    rig.companion.finish_setup()
    assert rig.companion.status()["setupComplete"] is True


def test_finishing_survives_a_restart(rig, tmp_path):
    """Otherwise every launch would walk the owner through setup again."""

    from pitrac_easy_connect.companion.service import CompanionService
    from pitrac_easy_connect.models import Simulator

    rig.companion.finish_setup()
    config = rig.companion.store.path
    rig.companion.close()

    restarted = CompanionService(
        config_path=config,
        simulator_ports={Simulator.GSPRO: rig.mock.address[1]},
        discovery_port=rig.pi.discovery.port,
        computer_name="Sim Room PC",
        discovery_targets=["127.0.0.1"],
    )
    try:
        assert restarted.status()["setupComplete"] is True
    finally:
        restarted.close()


def test_the_owner_can_go_back_through_setup(rig):
    rig.companion.finish_setup()
    rig.companion.finish_setup(done=False)
    assert rig.companion.status()["setupComplete"] is False


# --- what the window shows -------------------------------------------------


def test_every_step_offers_a_way_forward():
    """A step with nothing to press is a dead end, which is the whole failure
    mode this wizard exists to prevent."""

    source = wizard_source()
    returns = [block for block in source.split("return {")[1:]]
    assert len(returns) >= 6, "expected a view for each step"
    for block in returns:
        assert "actions:[" in block
        assert "actions:[]" not in block


def test_the_steps_are_in_order_and_counted():
    assert '{key:"find"' in PAGE and '{key:"sim"' in PAGE
    assert '{key:"open"' in PAGE and '{key:"test"' in PAGE and '{key:"done"' in PAGE
    rail = PAGE.split("function renderWizard(")[1].split("\n}")[0]
    assert '"Step "+(at+1)+" of "+WIZARD.length' in rail


def test_choosing_a_simulator_is_a_step_rather_than_buried_in_advanced():
    """It used to be reachable only through Advanced, so an E6 owner was told
    to open GSPro and had nowhere obvious to correct it."""

    source = wizard_source()
    assert "Which simulator do you use?" in source
    assert "wizSimGspro" in source and "wizSimE6" in source


def test_a_pi_that_was_never_on_wifi_is_explained():
    """The commonest first run is a Pi that is not on the network yet, so
    'check it is on this network' on its own is a dead end."""

    assert "CANNOT_FIND" in PAGE
    help_text = PAGE.split("const CANNOT_FIND=`")[1].split("`;")[0]
    assert "10.42.0.1" in help_text
    assert "PiTrac-" in help_text


def test_nothing_else_is_clickable_until_the_enclosure_is_found():
    """Deliberately narrowed, from "for the whole of setup" to "until linked".

    Hiding the tabs for all of setup was meant to keep a first run from
    wandering off, and it did that. It also meant the last three steps -- pick
    a simulator, open it, hit a test shot -- were a gate on the whole app,
    because they cannot be finished without a simulator running. Anyone who
    opened this before starting GSPro was held on the guide, unable to reach
    the practice range, which is the part that needs no simulator, no account
    and no internet.

    The line is now drawn where there is something worth reaching: once the
    enclosure has connected. Advanced is unchanged.
    """

    render = PAGE.split("function render(data){")[1].split("function doAction(")[0]
    assert 'const gated = guiding && !beenHere' in render
    assert '$("tabs").classList.toggle("hidden", gated)' in render
    assert 'classList.toggle("hidden", guiding || !data.pairedEnclosures.length)' in render


def test_the_tabs_stay_once_the_enclosure_has_been_seen():
    """A link that drops for a moment must not take the navigation with it."""

    render = PAGE.split("function render(data){")[1].split("function doAction(")[0]
    assert "if(linkedNow) wizard.reachedEnclosure = true;" in render, (
        "the tabs are keyed on the live link rather than on having ever "
        "connected, so they would flicker away with the link"
    )
    assert "(data.pairedEnclosures || []).length" in render, (
        "the latch is session-only, so quitting mid-guide and reopening with "
        "the enclosure switched off would take the navigation away again"
    )


def test_the_simulator_steps_can_be_left_for_later():
    """These two need a simulator running; nothing else in the app does."""

    wizard = wizard_source()
    blocked = [
        block for block in wizard.split("if(")
        if ("!sim.connected" in block or "!sim.ready" in block)
    ]
    assert len(blocked) == 2, "expected the open and test steps, found {}".format(len(blocked))
    for block in blocked:
        assert "wizFinish" in block, (
            "a step that needs a running simulator has no way past it: {}"
            .format(block[:90])
        )


def test_finishing_later_is_not_offered_once_setup_is_done():
    """present() is the settled view; there is nothing left to finish."""

    settled = PAGE.split("function present(")[1].split("\nfunction ")[0]
    assert "Finish later" not in settled


def test_the_wizard_is_skipped_once_setup_is_done():
    render = PAGE.split("function render(data){")[1].split("function doAction(")[0]
    assert "const guiding=!data.setupComplete" in render
    assert "guiding ? wizardView(data) : present(data)" in render


def test_there_is_a_way_back_into_setup():
    assert 'id="setupAgain"' in PAGE
    press = PAGE.split('$("setupAgain").addEventListener')[1].split("}));")[0]
    assert '"/api/finish-setup"' in press and "done:false" in press

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


def test_nothing_else_is_clickable_during_setup():
    render = PAGE.split("function render(data){")[1].split("function doAction(")[0]
    assert 'classList.toggle("hidden", guiding || !linkedNow)' in render
    assert 'classList.toggle("hidden", guiding || !data.pairedEnclosures.length)' in render


def test_the_wizard_is_skipped_once_setup_is_done():
    render = PAGE.split("function render(data){")[1].split("function doAction(")[0]
    assert "const guiding=!data.setupComplete" in render
    assert "guiding ? wizardView(data) : present(data)" in render


def test_there_is_a_way_back_into_setup():
    assert 'id="setupAgain"' in PAGE
    press = PAGE.split('$("setupAgain").addEventListener')[1].split("}));")[0]
    assert '"/api/finish-setup"' in press and "done:false" in press

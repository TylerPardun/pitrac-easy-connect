import json

import pytest

from pitrac_easy_connect.mock_simulators import RunningMock
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.service import CompanionService


def test_selection_is_saved_and_reloaded(tmp_path):
    config = tmp_path / "config.json"
    service = CompanionService(config)
    service.select("e6")
    assert json.loads(config.read_text())["simulator"] == "e6"
    assert CompanionService(config).simulator is Simulator.E6


def test_invalid_simulator_is_rejected(tmp_path):
    service = CompanionService(tmp_path / "config.json")
    with pytest.raises(ValueError, match="Only GSPro and E6"):
        service.select("unknown")


def test_corrupt_config_uses_safe_default(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("not-json")
    assert CompanionService(config).simulator is Simulator.GSPRO


def test_ready_requires_an_accepted_test_shot(tmp_path):
    with RunningMock(Simulator.GSPRO) as mock:
        ports = {Simulator.GSPRO: mock.address[1], Simulator.E6: 2483}
        service = CompanionService(tmp_path / "config.json", ports)
        checked = service.check()
        assert checked["connected"] is True
        assert checked["ready"] is False
        tested = service.test_shot()
        assert tested["connected"] is True
        assert tested["ready"] is True


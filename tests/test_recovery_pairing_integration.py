"""Recovery health, discovery, pairing, and updates are independent concerns."""

import json
import time
import urllib.request

import pytest

from conftest import start_serving
from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.common.updates import PACKAGED, UpdateStatus
from pitrac_easy_connect.companion.service import CompanionService
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.portal import PortalServer
from pitrac_easy_connect.pi.service import PiService, ServicePaths
from pitrac_easy_connect.pi.simulated import home_network_pi


class ExactDesktopUpdater:
    def __init__(self, installed="0.4.4"):
        self.installed = installed

    def check(self, force=False):
        return UpdateStatus(
            self.installed,
            PACKAGED,
            latest="v0.4.4",
            available=False,
            detail="Up to date.",
            download_url="https://example.invalid/v0.4.4",
        )


class ExactPiUpdater:
    def __init__(self):
        self.checked = []
        self.applied = []

    def check(self, target=None):
        self.checked.append(target)
        return UpdateStatus(
            "0.3.0",
            PACKAGED,
            latest="v0.4.4",
            available=True,
            can_apply=True,
            detail="Version 0.4.4 is available.",
        )

    def apply(self, target):
        self.applied.append(target)
        return {"applied": True, "version": "0.4.4"}


class RecoveryRig:
    """One unhealthy enclosure and two genuinely independent computers."""

    def __init__(self, tmp_path, pi_version="0.3.0"):
        self.tmp_path = tmp_path
        self.paths = ServicePaths(tmp_path / "pi-state")
        self.backend = home_network_pi(
            country="US",
            camera_count=0,
            services={"pitrac-web.service": False, "avahi-daemon.service": True},
            running_processes=[],
        )
        self.backend.connect("Ferndale", "GoodPassword1")
        self.pitrac = PitracInstallation(
            tmp_path / "missing" / "user_settings.json",
            tmp_path / "missing" / "calibration_data.json",
        )
        self.models = tmp_path / "missing-models"
        self.models.mkdir()
        self.pi = None
        self.portal = None
        self.stop_portal = None
        self.pi_version = pi_version
        self.start_pi(pi_version)
        self.computers = {
            "owner": self.make_computer("owner", "Owner Mac"),
            "second": self.make_computer("second", "Second PC"),
        }

    def start_pi(self, version):
        self.pi_version = version
        self.pi = PiService(
            self.backend,
            paths=self.paths,
            pitrac=self.pitrac,
            relay_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
            link_port=0,
            discovery_port=0,
            portal_port=0,
            version=version,
            manage_hostname=False,
            boot_grace=0.0,
            models_dir=self.models,
        )
        self.pi.start()
        self.portal = PortalServer(("127.0.0.1", 0), self.pi)
        self.stop_portal = start_serving(self.portal)
        self.pi.portal_port = self.portal.server_port

    def stop_pi(self):
        if self.stop_portal:
            self.stop_portal()
            self.stop_portal = None
        if self.pi:
            self.pi.stop()

    def restart_pi(self, version):
        self.stop_pi()
        self.start_pi(version)
        for computer in self.computers.values():
            computer.discovery_port = self.pi.discovery.port

    def make_computer(self, key, name):
        service = CompanionService(
            config_path=self.tmp_path / "{}.json".format(key),
            simulator_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
            discovery_port=self.pi.discovery.port,
            discovery_targets=["127.0.0.1"],
            computer_name=name,
            version="0.4.4",
            search_seconds=0.2,
            research_seconds=0.2,
        )
        service.updates = ExactDesktopUpdater()
        return service

    def restart_computer(self, key, name):
        self.computers[key].close()
        self.computers[key] = self.make_computer(key, name)
        return self.computers[key]

    def find(self, computer):
        for _attempt in range(20):
            found = computer.search(timeout=0.25)
            match = next(
                (entry for entry in found if entry["deviceId"] == self.pi.identity.device_id),
                None,
            )
            if match:
                return match
            time.sleep(0.05)
        raise AssertionError("the recovery enclosure was never discovered")

    def pair(self, computer):
        self.find(computer)
        return computer.pair(self.pi.identity.device_id)

    def wait_linked(self, computer, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = computer.status()
            if status["link"].get("connected") and status.get("enclosure"):
                return status
            time.sleep(0.05)
        raise AssertionError("the computer never linked to the recovery enclosure")

    def close(self):
        for computer in self.computers.values():
            computer.close()
        self.stop_pi()


@pytest.fixture
def recovery(tmp_path):
    rig = RecoveryRig(tmp_path)
    yield rig
    rig.close()


def test_recovery_state_still_allows_discovery_setup_pairing_status_and_exact_update(recovery):
    owner = recovery.computers["owner"]
    found = recovery.find(owner)
    assert found["version"] == "0.3.0"
    assert found["state"] == "RECOVERY REQUIRED"

    with urllib.request.urlopen(
        "http://127.0.0.1:{}/".format(recovery.portal.server_port), timeout=5
    ) as response:
        assert response.status == 200
        assert b"Pair another computer" in response.read()

    recovery.pair(owner)
    linked = recovery.wait_linked(owner)
    assert linked["state"] == "RECOVERY REQUIRED"
    assert linked["ready"] is False
    assert linked["enclosure"]["selfTest"]["ready"] is False
    assert linked["enclosure"]["selfTest"]["summary"]["failed"] >= 1

    plan = linked["update"]["coordination"]
    assert plan["phase"] == "pi-update-required"
    assert plan["targetVersion"] == "0.4.4"
    assert "0.4.4" in plan["detail"]

    updater = ExactPiUpdater()
    recovery.pi.enclosure_updates = updater
    applied = owner.apply_pi_update("v0.4.4")
    assert applied["targetVersion"] == "0.4.4"
    assert updater.checked[-1] == "v0.4.4"
    assert updater.applied == ["v0.4.4"]
    assert recovery.pi.state.value == "RECOVERY REQUIRED"


def test_two_computers_discover_pair_persist_and_forget_independently(recovery):
    owner = recovery.computers["owner"]
    second = recovery.computers["second"]
    device_id = recovery.pi.identity.device_id

    recovery.pair(owner)
    recovery.wait_linked(owner)
    assert recovery.find(second)["paired"] is False

    with pytest.raises(EasyConnectError) as refused:
        recovery.pair(second)
    assert refused.value.info.code == "PT-PAIR-001"
    assert "Pair another computer" in refused.value.info.next_step

    owner.disconnect()
    open_request = urllib.request.Request(
        "http://127.0.0.1:{}/api/pair-open".format(recovery.portal.server_port),
        data=b"{}",
        headers={"X-PiTrac-Portal": "1", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(open_request, timeout=5) as response:
        assert json.loads(response.read().decode("utf-8"))["accepting"] is True
    recovery.pair(second)
    recovery.wait_linked(second)
    assert recovery.pi.pairings.count == 2
    assert device_id in owner.paired_enclosures
    assert device_id in second.paired_enclosures

    recovery.restart_pi("0.3.0")
    owner = recovery.restart_computer("owner", "Owner Mac")
    second = recovery.restart_computer("second", "Second PC")
    assert device_id in owner.paired_enclosures
    assert device_id in second.paired_enclosures
    assert recovery.pi.pairings.count == 2

    recovery.find(owner)
    owner.connect(device_id)
    recovery.wait_linked(owner)
    owner.forget(device_id)
    assert recovery.pi.pairings.count == 1
    assert device_id not in owner.paired_enclosures
    assert device_id in second.paired_enclosures

    recovery.find(second)
    second.connect(device_id)
    assert recovery.wait_linked(second)["state"] == "RECOVERY REQUIRED"


def test_compatible_030_pairing_reconnects_as_044_without_changing_health(recovery):
    owner = recovery.computers["owner"]
    device_id = recovery.pi.identity.device_id
    recovery.pair(owner)
    before = recovery.wait_linked(owner)
    assert before["version"] == "0.4.4"
    assert before["enclosure"]["version"] == "0.3.0"
    assert before["update"]["versionsMatch"] is False

    recovery.restart_pi("0.4.4")
    recovery.find(owner)
    owner.connect(device_id)
    after = recovery.wait_linked(owner)
    assert after["enclosure"]["version"] == "0.4.4"
    assert after["update"]["versionsMatch"] is True
    assert after["update"]["coordination"]["phase"] == "synchronized"
    assert after["state"] == "RECOVERY REQUIRED"
    assert after["ready"] is False

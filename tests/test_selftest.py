"""READY TO PLAY has to be earned, and has to be lost the moment it stops being true."""

import pytest

from pitrac_easy_connect.common.states import State
from pitrac_easy_connect.models import Simulator
from pitrac_fixture import make_pitrac
from pitrac_easy_connect.pi.selftest import (
    FAIL,
    PASS,
    UNAVAILABLE,
    WARN,
    SelfTest,
    state_for,
)
from pitrac_easy_connect.pi.pitrac_api import PitracUnsupported
from pitrac_easy_connect.pi.simulated import home_network_pi

RELAY_PORTS = {Simulator.GSPRO: 9210, Simulator.E6: 9248}


def build(tmp_path, **overrides):
    backend = home_network_pi(country="US")
    backend.connect("Ferndale", "GoodPassword1")

    pitrac = make_pitrac(tmp_path, calibrated=True, relay_ports=RELAY_PORTS)

    # A healthy enclosure has the detection models installed. They are licensed
    # separately from PiTrac and are not installed with it, so a unit can be
    # perfectly built and still be missing them.
    models = tmp_path / "models"
    for name in ("yolo26-ball-detector", "spin-predictor"):
        (models / name).mkdir(parents=True)
        (models / name / "best.ncnn.bin").write_bytes(b"weights")
        (models / name / "best.ncnn.param").write_text("graph")

    options = {
        "models_dir": models,
        "network_status": lambda: {
            "connection": {"ssid": "Ferndale", "isHotspot": False},
            "directMode": False,
            "awaitingConfirmation": False,
        },
        "companion_connected": lambda: True,
        "simulator_status": lambda: {
            "connected": True,
            "ready": True,
            "simulatorLabel": "GSPro",
        },
        "config_problems": lambda: [],
    }
    options.update(overrides)
    return backend, pitrac, SelfTest(backend, pitrac, RELAY_PORTS, **options)


def find(report, key):
    return next(check for check in report.checks if check.key == key)


# --- The healthy enclosure ------------------------------------------------


def test_a_healthy_enclosure_is_ready(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path)
    report = selftest.run()
    assert report.ready is True, [c.as_dict() for c in report.blocking]
    assert report.as_dict()["summary"]["failed"] == 0


def test_every_check_reports_something(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path)
    report = selftest.run()
    assert len(report.checks) == 16
    assert all(check.status in (PASS, FAIL, WARN, UNAVAILABLE) for check in report.checks)


# --- Each way readiness is lost -------------------------------------------


def test_unplugging_a_camera_removes_readiness(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.camera_count = 1
    report = selftest.run()
    assert report.ready is False
    assert find(report, "cameras").error.code == "PT-PI-001"
    assert report.first_problem.key == "cameras"


def test_missing_calibration_removes_readiness(tmp_path):
    _backend, pitrac, selftest = build(tmp_path)
    pitrac.api.calibration = {}
    report = selftest.run()
    assert report.ready is False
    assert find(report, "calibration").error.code == "PT-PI-002"


def test_half_a_calibration_is_not_a_calibration(tmp_path):
    """Lens and position are separate procedures, and both are needed."""

    _backend, pitrac, selftest = build(tmp_path)
    del pitrac.api.calibration["gs_config"]["cameras"]["kCamera2Angles"]
    check = find(selftest.run(), "calibration")
    assert check.status == FAIL
    assert check.detail == "Not calibrated yet: camera 2 position"


def test_an_uncalibrated_strobe_removes_readiness(tmp_path):
    _backend, pitrac, selftest = build(tmp_path)
    pitrac.api.strobe = {"required": True, "safe": False, "reason": "V3 board requires strobe calibration"}
    report = selftest.run()
    assert report.ready is False
    assert find(report, "strobe").error.code == "PT-PI-014"


def test_a_pitrac_that_does_not_answer_is_unknown_not_uncalibrated(tmp_path):
    """Telling somebody to calibrate again because a service was restarting
    would cost them an hour for nothing."""

    _backend, pitrac, selftest = build(tmp_path)
    pitrac.api.reachable = False
    report = selftest.run()
    assert report.ready is False
    assert report.first_problem.key == "pitracWeb"
    for key in ("calibration", "strobe", "pitracTarget"):
        assert find(report, key).status == UNAVAILABLE
        assert find(report, key).error.code == "PT-PI-004"


def test_a_pitrac_this_release_cannot_use_says_so(tmp_path):
    _backend, pitrac, selftest = build(tmp_path)
    pitrac.api.error = PitracUnsupported("PiTrac does not offer /api/sims")
    report = selftest.run()
    assert report.ready is False
    assert report.first_problem.error.code == "PT-PI-015"
    assert state_for(report, {"connection": {"ssid": "x"}}, True) is State.RECOVERY_REQUIRED


def test_stopping_pitrac_removes_readiness(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.running_processes = []
    report = selftest.run()
    assert report.ready is False
    assert find(report, "pitracMeasurement").error.code == "PT-PI-003"


def test_a_full_memory_card_removes_readiness(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.free_bytes = 500 * 1024**2
    report = selftest.run()
    assert report.ready is False
    assert find(report, "storage").error.code == "PT-PI-005"


def test_losing_the_computer_removes_readiness(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path, companion_connected=lambda: False)
    report = selftest.run()
    assert report.ready is False
    assert find(report, "companion").status == FAIL


def test_restarting_the_simulator_removes_readiness(tmp_path):
    _backend, _pitrac, selftest = build(
        tmp_path,
        simulator_status=lambda: {
            "connected": False,
            "ready": False,
            "message": "GSPro is not accepting connections",
            "errorCode": "PT-SIM-001",
        },
    )
    report = selftest.run()
    assert report.ready is False
    assert find(report, "simulator").error.code == "PT-SIM-001"


def test_a_connected_simulator_with_no_accepted_test_shot_is_not_ready(tmp_path):
    _backend, _pitrac, selftest = build(
        tmp_path,
        simulator_status=lambda: {"connected": True, "ready": False, "simulatorLabel": "GSPro"},
    )
    report = selftest.run()
    assert report.ready is False
    assert find(report, "simulator").status == WARN


def test_pitrac_pointed_somewhere_else_removes_readiness(tmp_path):
    _backend, pitrac, selftest = build(tmp_path)
    pitrac.api.remove_sims()
    report = selftest.run()
    assert report.ready is False
    assert find(report, "pitracTarget").status == FAIL
    assert find(report, "pitracTarget").error.code == "PT-PI-016"


@pytest.mark.parametrize("change, said", [
    ({"on": False}, "turned off"),
    ({"status": "error"}, "not connected"),
    ({"status": "connecting"}, "not connected"),
])
def test_a_configured_target_that_is_not_delivering_is_not_ready(tmp_path, change, said):
    """Configured is not connected. The old check stopped at configured."""

    _backend, pitrac, selftest = build(tmp_path)
    pitrac.api._sims[0].update(change)
    check = find(selftest.run(), "pitracTarget")
    assert check.status == FAIL
    assert said in check.detail


def test_a_second_route_to_gspro_is_mentioned_but_does_not_stop_play(tmp_path):
    _backend, pitrac, selftest = build(tmp_path)
    pitrac.api.add_sim("gspro", "192.168.1.50", 921, name="Sim PC")
    report = selftest.run()
    assert report.ready is True
    assert "192.168.1.50:921" in find(report, "pitracTarget").detail


def test_unsupported_hardware_removes_readiness(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.model = "Raspberry Pi 3 Model B"
    report = selftest.run()
    assert report.ready is False
    assert find(report, "hardware").error.code == "PT-PI-010"


# --- Things worth saying that do not stop play ---------------------------


def test_a_warm_enclosure_warns_but_still_plays(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.temperature_c = 78.0
    report = selftest.run()
    assert report.ready is True
    assert find(report, "temperature").status == WARN


def test_a_throttled_enclosure_stops_play(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.throttled_flags = 0x4
    report = selftest.run()
    assert report.ready is False
    assert find(report, "temperature").error.code == "PT-PI-006"


def test_low_power_recorded_earlier_is_only_a_warning(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.throttled_flags = 0x10000
    report = selftest.run()
    assert report.ready is True
    assert find(report, "power").status == WARN


def test_low_power_right_now_stops_play(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.throttled_flags = 0x1
    report = selftest.run()
    assert report.ready is False
    assert find(report, "power").error.code == "PT-PI-007"


def test_an_unset_clock_warns_but_still_plays(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.clock_synchronized = False
    report = selftest.run()
    assert report.ready is True
    assert find(report, "clock").status == WARN


def test_recovered_settings_are_reported_without_stopping_play(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path, config_problems=lambda: ["settings.json"])
    report = selftest.run()
    assert report.ready is True
    assert find(report, "configuration").status == WARN


# --- Checks that cannot run are never counted as passes -------------------


def test_a_check_that_cannot_run_is_marked_unavailable_not_passed(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path, simulator_status=lambda: None)
    report = selftest.run()
    assert find(report, "simulator").status == UNAVAILABLE
    assert report.ready is False, "an unavailable critical check cannot count as ready"


def test_a_check_that_raises_does_not_stop_the_others(tmp_path):
    def explode():
        raise RuntimeError("the sensor is on fire")

    _backend, _pitrac, selftest = build(tmp_path, config_problems=explode)
    report = selftest.run()
    assert len(report.checks) == 16
    assert find(report, "configuration").status == UNAVAILABLE


def test_a_dashboard_that_is_not_answering_removes_readiness(tmp_path):
    """Every measured shot goes through it on its way out."""

    backend, pitrac, selftest = build(tmp_path)
    pitrac.api.reachable = False
    for services, said in (({}, "not installed"), ({"pitrac-web.service": True}, "not answering")):
        backend.services = services
        check = find(selftest.run(), "pitracWeb")
        assert check.status == FAIL
        assert said in check.detail


# --- The word the user sees ----------------------------------------------


def test_a_healthy_enclosure_says_ready_to_play(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path)
    report = selftest.run()
    network = {"connection": {"ssid": "Ferndale", "isHotspot": False}, "directMode": False}
    assert state_for(report, network, True) is State.READY_TO_PLAY


def test_an_enclosure_on_its_setup_signal_says_setup_required(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path, companion_connected=lambda: False)
    report = selftest.run()
    network = {"connection": {"ssid": "PiTrac-X", "isHotspot": True}, "directMode": False}
    assert state_for(report, network, False) is State.SETUP_REQUIRED


def test_a_missing_camera_says_recovery_required(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.camera_count = 0
    report = selftest.run()
    network = {"connection": {"ssid": "Ferndale", "isHotspot": False}, "directMode": False}
    assert state_for(report, network, True) is State.RECOVERY_REQUIRED


def test_a_stopped_simulator_says_the_simulator_needs_attention(tmp_path):
    _backend, _pitrac, selftest = build(
        tmp_path,
        simulator_status=lambda: {"connected": False, "ready": False, "errorCode": "PT-SIM-001"},
    )
    report = selftest.run()
    network = {"connection": {"ssid": "Ferndale", "isHotspot": False}, "directMode": False}
    assert state_for(report, network, True) is State.SIMULATOR_ACTION_REQUIRED


def test_a_network_change_in_progress_says_connecting(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path, companion_connected=lambda: False)
    report = selftest.run()
    network = {
        "connection": {"ssid": "Ferndale", "isHotspot": False},
        "directMode": False,
        "awaitingConfirmation": True,
    }
    assert state_for(report, network, False) is State.CONNECTING


def test_every_state_has_words_a_person_can_read():
    for state in State:
        assert len(state.headline) > 3
        assert len(state.detail) > 20


# --- A relay that is not listening is the worst silent failure -------------


def test_a_relay_that_failed_to_bind_removes_readiness(tmp_path):
    # PiTrac pointed at a port with nothing behind it loses every shot without
    # any error, so this must be caught explicitly.
    _backend, _pitrac, selftest = build(tmp_path)
    selftest.relay_listening = lambda: False
    report = selftest.run()
    assert report.ready is False
    assert find(report, "pitracTarget").status == FAIL
    assert "not listening" in find(report, "pitracTarget").detail


def test_a_listening_relay_and_correct_config_together_pass(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path)
    selftest.relay_listening = lambda: True
    assert find(selftest.run(), "pitracTarget").status == PASS


def test_a_connected_computer_ends_the_setup_phase_even_on_the_hotspot(tmp_path):
    # A user who paired over the enclosure's own signal is set up. Continuing to
    # say SETUP REQUIRED hides whatever is actually still wrong.
    _backend, _pitrac, selftest = build(
        tmp_path,
        simulator_status=lambda: {"connected": False, "ready": False, "errorCode": "PT-SIM-001"},
    )
    report = selftest.run()
    network = {"connection": {"ssid": "PiTrac-X", "isHotspot": True}, "directMode": False}
    assert state_for(report, network, companion=True) is State.SIMULATOR_ACTION_REQUIRED


def test_hardware_problems_outrank_the_simulator_once_a_computer_is_connected(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.camera_count = 0
    report = selftest.run()
    network = {"connection": {"ssid": "PiTrac-X", "isHotspot": True}, "directMode": False}
    assert state_for(report, network, companion=True) is State.RECOVERY_REQUIRED


def test_with_no_computer_the_hotspot_still_means_setup_required(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path, companion_connected=lambda: False)
    report = selftest.run()
    network = {"connection": {"ssid": "PiTrac-X", "isHotspot": True}, "directMode": False}
    assert state_for(report, network, companion=False) is State.SETUP_REQUIRED


# --- The detection models -------------------------------------------------


def test_missing_detection_models_stop_it_claiming_to_be_ready(tmp_path):
    """A unit sold without the models is otherwise perfectly healthy.

    The models are licensed separately and are not installed with PiTrac, so
    without this check the enclosure reports every green tick it has and then
    does nothing at all on the first swing.
    """

    _backend, _pitrac, selftest = build(tmp_path, models_dir=tmp_path / "empty")
    report = selftest.run()

    assert report.ready is False
    check = find(report, "pitracModels")
    assert check.error.code == "PT-PI-011"
    assert "yolo26-ball-detector" in check.detail
    # The message has to say where they come from; they are not ours to supply.
    assert "PiTracLM" in check.error.next_step


def test_one_model_present_is_still_not_ready(tmp_path):
    """Half the models is not most of the way there."""

    models = tmp_path / "half"
    (models / "spin-predictor").mkdir(parents=True)
    (models / "spin-predictor" / "best.ncnn.bin").write_bytes(b"weights")

    _backend, _pitrac, selftest = build(tmp_path, models_dir=models)
    report = selftest.run()

    assert report.ready is False
    check = find(report, "pitracModels")
    assert "yolo26-ball-detector" in check.detail
    assert "spin-predictor" not in check.detail


# --- A check that crashes -----------------------------------------------------


@pytest.mark.parametrize("name", [
    "_hardware", "_storage", "_temperature", "_power", "_cameras", "_pitrac_web", "_calibration",
    "_strobe", "_pitrac_measurement", "_pitrac_models", "_pitrac_target", "_network", "_companion",
    "_simulator",
])
def test_not_being_able_to_check_stops_play(tmp_path, monkeypatch, name):
    """A camera check that crashed left the enclosure ready."""

    from pitrac_easy_connect.pi.selftest import WHAT_CHECKS_ARE

    _backend, _pitrac, selftest = build(tmp_path)
    key = WHAT_CHECKS_ARE[name][0]
    assert key in {check.key for check in selftest.run().checks}, "called something else"

    def explode():
        raise RuntimeError("it fell over")

    explode.__name__ = name
    monkeypatch.setattr(selftest, name, explode)
    report = selftest.run()
    assert report.ready is False
    assert find(report, key).status == UNAVAILABLE
    assert "it fell over" in find(report, key).detail


def test_every_check_has_a_name_for_when_it_cannot_give_its_own(tmp_path):
    from pitrac_easy_connect.pi.selftest import WHAT_CHECKS_ARE

    # The update check runs only on an installed enclosure, so give it one.
    _backend, _pitrac, selftest = build(tmp_path, update_problems=lambda: [])
    assert {check.key for check in selftest.run().checks} == {
        key for key, _title, _critical in WHAT_CHECKS_ARE.values()}


def test_updates_that_could_not_be_installed_are_said_before_one_is_tried(tmp_path):
    _backend, _pitrac, selftest = build(
        tmp_path, update_problems=lambda: ["This service is not allowed to switch to 'nobody'."]
    )
    report = selftest.run()
    check = find(report, "updates")
    assert check.status == "warn" and "nobody" in check.detail
    # Worth fixing, but not a reason to stop play.
    assert check not in report.blocking


def test_the_update_check_is_absent_where_updates_do_not_replace_anything(tmp_path):
    _backend, _pitrac, selftest = build(tmp_path)
    assert "updates" not in {check.key for check in selftest.run().checks}

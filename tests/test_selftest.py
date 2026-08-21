"""READY TO PLAY has to be earned, and has to be lost the moment it stops being true."""

import pytest

from pitrac_easy_connect.common.states import State
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.selftest import (
    FAIL,
    PASS,
    UNAVAILABLE,
    WARN,
    SelfTest,
    state_for,
)
from pitrac_easy_connect.pi.simulated import home_network_pi

RELAY_PORTS = {Simulator.GSPRO: 9210, Simulator.E6: 9248}


def build(tmp_path, **overrides):
    backend = home_network_pi(country="US")
    backend.connect("Ferndale", "GoodPassword1")

    settings = tmp_path / "user_settings.json"
    calibration = tmp_path / "calibration_data.json"
    pitrac = PitracInstallation(settings, calibration)
    pitrac.point_at_relay(RELAY_PORTS)
    calibration.write_text(
        '{"gs_config": {"cameras": {"kCamera1CalibrationMatrix": [[1]],'
        ' "kCamera2CalibrationMatrix": [[1]]}}}'
    )

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
    assert len(report.checks) == 15
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
    pitrac.calibration_path.unlink()
    report = selftest.run()
    assert report.ready is False
    assert find(report, "calibration").error.code == "PT-PI-002"


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
    pitrac.settings_path.write_text("{}")
    report = selftest.run()
    assert report.ready is False
    assert find(report, "pitracTarget").status == FAIL


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
    assert len(report.checks) == 15
    assert find(report, "configuration").status == UNAVAILABLE


def test_a_missing_dashboard_service_is_unavailable_not_failed(tmp_path):
    backend, _pitrac, selftest = build(tmp_path)
    backend.services = {}
    report = selftest.run()
    assert find(report, "pitracWeb").status == UNAVAILABLE
    assert report.ready is True, "the dashboard is not needed to hit a ball"


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

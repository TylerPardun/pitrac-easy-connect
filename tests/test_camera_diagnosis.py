"""Why a camera is missing, worked out from the Pi's own evidence."""

from pitrac_easy_connect.pi import camera_diagnosis as cd
from pitrac_easy_connect.pi.camera_diagnosis import CameraEvidence, diagnose


def test_cameras_that_never_answered_at_power_on_are_a_connection_problem():
    # This enclosure's case: auto-detect on, no driver loaded, nothing in the kernel.
    found = diagnose(CameraEvidence(listed=0, config_found=True, auto_detect=True))
    assert found.cause == "nothing-answered-at-power-on"
    assert "none" in found.finding and "not a software one" in found.finding
    assert "22-pin to 15-pin" in found.fix


def test_a_loaded_driver_whose_camera_does_not_answer_points_at_that_cable():
    found = diagnose(CameraEvidence(
        listed=1, expected_sensors=["imx296", "imx296"], bound_sensors=["imx296 6-001a"],
        kernel_lines=["imx296 4-001a: failed to read chip id, error -121"],
    ))
    assert found.cause == "camera-not-answering"
    assert "1 did not answer" in found.finding
    assert "-121" in found.finding


def test_cameras_the_kernel_has_but_the_software_cannot_use():
    found = diagnose(CameraEvidence(
        listed=0, expected_sensors=["imx296", "imx296"],
        bound_sensors=["imx296 4-001a", "imx296 6-001a"],
        rpicam_message="ERROR: *** no cameras available ***",
    ))
    assert found.cause == "camera-software"
    assert "no cameras available" in found.finding


def test_detection_turned_off_with_no_camera_named():
    found = diagnose(CameraEvidence(listed=0, config_found=True, auto_detect=False))
    assert found.cause == "not-configured"
    assert "camera_auto_detect=1" in found.fix


def test_a_named_camera_that_was_not_loaded():
    found = diagnose(CameraEvidence(
        listed=0, config_found=True, auto_detect=False, overlays=["imx296,cam0"],
    ))
    assert found.cause == "overlay-not-loaded"


def test_missing_camera_software_is_said_first():
    found = diagnose(CameraEvidence(listed=0, rpicam_installed=False))
    assert found.cause == "no-camera-software"


def test_two_working_cameras_need_no_diagnosis():
    assert diagnose(CameraEvidence(listed=2)).cause == "ok"


def test_config_reads_only_what_a_pi_5_reads():
    text = """
    # comment camera_auto_detect=0
    [pi4]
    camera_auto_detect=0
    dtoverlay=ov5647
    [pi5]
    dtoverlay=imx296,cam0
    dtoverlay=vc4-kms-v3d
    [all]
    camera_auto_detect=1  # on
    """
    parsed = cd.parse_config(text)
    assert parsed == {"autoDetect": True, "overlays": ["imx296,cam0"]}


def test_config_with_detection_off():
    assert cd.parse_config("camera_auto_detect=0\n")["autoDetect"] is False


def test_device_tree_and_bound_sensors_are_read_from_their_trees(tmp_path):
    tree = tmp_path / "dt"
    on = tree / "axi" / "i2c@80000" / "imx296@1a"
    off = tree / "axi" / "i2c@88000" / "imx296@1a"
    other = tree / "axi" / "gpio"
    for node in (on, off, other):
        node.mkdir(parents=True)
    (on / "compatible").write_bytes(b"sony,imx296\0")
    (off / "compatible").write_bytes(b"sony,imx296\0")
    (off / "status").write_bytes(b"disabled\0")
    (other / "compatible").write_bytes(b"brcm,bcm2712-gpio\0")
    assert cd.device_tree_sensors(str(tree)) == ["imx296"]

    v4l = tmp_path / "v4l"
    for entry, name in (("v4l-subdev0", "imx296 4-001a"), ("video0", "rp1-cfe-csi2_ch0")):
        (v4l / entry).mkdir(parents=True)
        (v4l / entry / "name").write_text(name + "\n")
    assert cd.bound_sensors(str(v4l)) == ["imx296 4-001a"]


def test_gather_reads_every_level(tmp_path):
    config = tmp_path / "config.txt"
    config.write_text("camera_auto_detect=1\n")
    kernel = "\n".join([
        "Booting Linux",
        "rp1-cfe 1f00128000.csi: found subdevice",
        "imx296 4-001a: failed to read chip id, error -121",
        "usb 1-1: new device",
    ])

    def run(command, timeout):
        if command[0].endswith("rpicam-hello"):
            return 0, "", "No cameras available!"
        if command[0] == "journalctl":
            return 0, kernel, ""
        return 1, "", ""

    evidence = cd.gather(
        run, lambda name: "/usr/bin/" + name, listed=0,
        config_paths=[str(config)], device_tree=str(tmp_path / "none"),
        video4linux=str(tmp_path / "none"),
    )
    assert evidence.rpicam_message == "No cameras available!"
    assert evidence.auto_detect is True and evidence.config_found
    assert evidence.kernel_lines == [
        "rp1-cfe 1f00128000.csi: found subdevice",
        "imx296 4-001a: failed to read chip id, error -121",
    ]
    assert diagnose(evidence).cause == "nothing-answered-at-power-on"


def test_the_camera_check_says_why_and_what_to_do(tmp_path):
    from test_selftest import build

    backend, _pitrac, selftest = build(tmp_path)
    backend.camera_count = 0
    check = next(c for c in selftest.run().as_dict()["checks"] if c["key"] == "cameras")
    assert check["status"] == "fail"
    assert check["detail"].startswith("0 of 2 cameras detected. When the Pi started")
    assert "22-pin to 15-pin" in check["error"]["nextStep"]
    assert check["error"]["code"] == "PT-PI-001"
    assert check["diagnosis"]["cause"] == "nothing-answered-at-power-on"


def test_a_diagnosis_that_cannot_be_worked_out_leaves_the_count(tmp_path):
    from test_selftest import build

    backend, _pitrac, selftest = build(tmp_path)
    backend.camera_count = 0

    def broken(listed, required):
        raise OSError("no /proc here")

    backend.camera_evidence = broken
    check = next(c for c in selftest.run().as_dict()["checks"] if c["key"] == "cameras")
    assert check["detail"] == "0 of 2 cameras detected"
    assert "diagnosis" not in check


def test_this_enclosures_real_boot_log_is_read_as_neither_camera_answering():
    """Recorded on the user's Pi 5 with explicit imx296 overlays, 2026-11-27."""

    kernel = "\n".join([
        "[    2.851937] rp1-cfe 1f00110000.csi: found subdevice /axi/pcie@1000120000/rp1/i2c@88000/imx296@1a",
        "[    2.852984] rp1-cfe 1f00128000.csi: found subdevice /axi/pcie@1000120000/rp1/i2c@80000/imx296@1a",
        "[    3.519083] imx296 11-001a: 8-bit write to 0x3000 failed: -121",
        "[    3.519093] imx296 11-001a: failed to get sensor out of standby (-121)",
        "[    3.519220] imx296 11-001a: probe with driver imx296 failed with error -121",
        "[    4.035077] imx296 10-001a: 8-bit write to 0x3000 failed: -121",
        "[    4.035087] imx296 10-001a: failed to get sensor out of standby (-121)",
        "[    4.035227] imx296 10-001a: probe with driver imx296 failed with error -121",
    ])
    lines = [line for line in kernel.splitlines() if cd.KERNEL_CAMERA.search(line)]
    found = diagnose(CameraEvidence(
        listed=0, config_found=True, auto_detect=True,
        overlays=["imx296,cam0", "imx296,cam1"],
        expected_sensors=["imx296", "imx296"], bound_sensors=[],
        kernel_lines=lines[-cd.KERNEL_LINES_KEPT:],
    ))
    assert found.cause == "camera-not-answering"
    assert "2 did not answer" in found.finding
    assert "-121" in found.finding

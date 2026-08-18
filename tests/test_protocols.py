import math

from pitrac_easy_connect.mock_simulators import RunningMock
from pitrac_easy_connect.models import Simulator, TEST_SHOT
from pitrac_easy_connect.protocols import (
    check_socket,
    e6_ball_message,
    gspro_message,
    send_e6_test_shot,
    send_gspro_test_shot,
)


def test_gspro_message_contains_required_ball_data():
    message = gspro_message(TEST_SHOT, shot_number=7)
    assert message["ShotNumber"] == 7
    assert message["BallData"]["Speed"] == TEST_SHOT.speed_mph
    assert message["BallData"]["VLA"] == TEST_SHOT.vertical_launch_deg
    assert message["BallData"]["HLA"] == TEST_SHOT.horizontal_launch_deg
    expected_spin = math.hypot(TEST_SHOT.back_spin_rpm, TEST_SHOT.side_spin_rpm)
    assert message["BallData"]["TotalSpin"] == round(expected_spin, 1)
    assert message["ShotDataOptions"]["ContainsBallData"] is True


def test_e6_message_matches_pitrac_field_names():
    message = e6_ball_message(TEST_SHOT)
    assert message["Type"] == "SetBallData"
    assert message["BallData"] == {
        "BackSpin": TEST_SHOT.back_spin_rpm,
        "BallSpeed": TEST_SHOT.speed_mph,
        "LaunchAngle": TEST_SHOT.vertical_launch_deg,
        "LaunchDirection": TEST_SHOT.horizontal_launch_deg,
        "SideSpin": TEST_SHOT.side_spin_rpm,
    }


def test_gspro_mock_accepts_test_shot():
    with RunningMock(Simulator.GSPRO) as mock:
        result = send_gspro_test_shot(*mock.address, TEST_SHOT)
        assert result.accepted is True
        assert result.response["Code"] == 200
        assert mock.received[0]["DeviceID"] == "PiTrac Easy Connect"


def test_e6_mock_accepts_required_message_sequence():
    with RunningMock(Simulator.E6) as mock:
        result = send_e6_test_shot(*mock.address, TEST_SHOT)
        assert result.accepted is True
        assert [message["Type"] for message in mock.received] == [
            "Handshake",
            "SetBallData",
            "SetClubData",
            "SendShot",
        ]


def test_connection_check_fails_when_no_server_is_listening():
    with RunningMock(Simulator.GSPRO) as mock:
        host, port = mock.address
    result = check_socket(host, port, timeout=0.2)
    assert result.accepted is False
    assert "Could not reach" in result.message


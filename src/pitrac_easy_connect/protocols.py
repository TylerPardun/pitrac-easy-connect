"""The exact messages GSPro and E6 expect for a shot.

Only the message formats live here. Sending them is
:mod:`pitrac_easy_connect.companion.simulator_session`, which holds one
connection open for the life of a session rather than dialling per shot.

These are also the formats PiTrac itself produces, so a message travelling
through the relay is byte-for-byte what PiTrac sent. Nothing here rewrites it.
"""

from typing import Any, Dict

from .models import ShotData


def gspro_message(shot: ShotData, shot_number: int = 1) -> Dict[str, Any]:
    shot.validate()
    total_spin = (shot.back_spin_rpm**2 + shot.side_spin_rpm**2) ** 0.5
    spin_axis = 0.0
    if total_spin:
        # GSPro accepts spin axis with total spin. atan2 gives the correct sign
        # for left/right curvature while remaining stable near zero spin.
        import math

        spin_axis = math.degrees(math.atan2(shot.side_spin_rpm, shot.back_spin_rpm))
    return {
        "DeviceID": "PiTrac Easy Connect",
        "Units": "Yards",
        "ShotNumber": shot_number,
        "APIversion": "1",
        "BallData": {
            "Speed": round(shot.speed_mph, 2),
            "SpinAxis": round(spin_axis, 2),
            "TotalSpin": round(total_spin, 1),
            "BackSpin": shot.back_spin_rpm,
            "SideSpin": shot.side_spin_rpm,
            "HLA": round(shot.horizontal_launch_deg, 2),
            "VLA": round(shot.vertical_launch_deg, 2),
        },
        "ClubData": {},
        "ShotDataOptions": {
            "ContainsBallData": True,
            "ContainsClubData": False,
            "LaunchMonitorIsReady": True,
            "LaunchMonitorBallDetected": True,
            "IsHeartBeat": False,
        },
    }


def e6_ball_message(shot: ShotData) -> Dict[str, Any]:
    shot.validate()
    return {
        "Type": "SetBallData",
        "BallData": {
            "BackSpin": shot.back_spin_rpm,
            "BallSpeed": round(shot.speed_mph, 2),
            "LaunchAngle": round(shot.vertical_launch_deg, 2),
            "LaunchDirection": round(shot.horizontal_launch_deg, 2),
            "SideSpin": shot.side_spin_rpm,
        },
    }


def e6_club_message() -> Dict[str, Any]:
    return {
        "Type": "SetClubData",
        "ClubData": {
            "ClubHeadSpeed": 0.0,
            "ClubAngleFace": 0.0,
            "ClubAnglePath": 0.0,
            "ClubHeadSpeedMPH": 0.0,
        },
    }

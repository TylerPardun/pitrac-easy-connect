import json
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .models import ShotData, Simulator


class SimulatorConnectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SimulatorResult:
    accepted: bool
    message: str
    response: Optional[Dict[str, Any]] = None


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


class JsonSocket:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buffer = ""
        self.decoder = json.JSONDecoder()

    def send(self, message: Dict[str, Any]) -> None:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        self.sock.sendall(payload)

    def receive(self, timeout: float) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            stripped = self.buffer.lstrip()
            if stripped:
                try:
                    value, consumed = self.decoder.raw_decode(stripped)
                    self.buffer = stripped[consumed:]
                    if not isinstance(value, dict):
                        raise SimulatorConnectionError("Simulator returned non-object JSON")
                    return value
                except json.JSONDecodeError:
                    pass

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SimulatorConnectionError("Simulator did not respond before the timeout")
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(8192)
            except socket.timeout as exc:
                raise SimulatorConnectionError("Simulator did not respond before the timeout") from exc
            if not chunk:
                raise SimulatorConnectionError("Simulator closed the connection without responding")
            try:
                self.buffer += chunk.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SimulatorConnectionError("Simulator returned invalid text") from exc


def check_socket(host: str, port: int, timeout: float = 1.0) -> SimulatorResult:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return SimulatorResult(True, "Simulator connection is available")
    except OSError as exc:
        return SimulatorResult(False, _friendly_socket_error(host, port, exc))


def send_gspro_test_shot(
    host: str, port: int, shot: ShotData, timeout: float = 2.0
) -> SimulatorResult:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            stream = JsonSocket(sock)
            stream.send(gspro_message(shot))
            response = stream.receive(timeout)
    except (OSError, SimulatorConnectionError) as exc:
        return SimulatorResult(False, _friendly_socket_error(host, port, exc))

    code = response.get("Code")
    if code == 200:
        return SimulatorResult(True, "GSPro accepted the test shot", response)
    return SimulatorResult(False, "GSPro responded, but did not accept the test shot", response)


def send_e6_test_shot(
    host: str, port: int, shot: ShotData, timeout: float = 2.0
) -> SimulatorResult:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            stream = JsonSocket(sock)
            stream.send({"Type": "Handshake"})
            handshake = stream.receive(timeout)
            if handshake.get("Type") not in {"Handshake", "HandshakeAck"}:
                return SimulatorResult(False, "E6 returned an unexpected handshake", handshake)

            stream.send(e6_ball_message(shot))
            time.sleep(0.05)
            stream.send(e6_club_message())
            time.sleep(0.05)
            stream.send({"Type": "SendShot"})
            response = stream.receive(timeout)
    except (OSError, SimulatorConnectionError) as exc:
        return SimulatorResult(False, _friendly_socket_error(host, port, exc))

    if response.get("Type") in {"ShotComplete", "ShotAccepted"}:
        return SimulatorResult(True, "E6 accepted the test shot", response)
    return SimulatorResult(False, "E6 responded, but did not confirm the test shot", response)


def send_test_shot(
    simulator: Simulator,
    endpoint: Tuple[str, int],
    shot: ShotData,
) -> SimulatorResult:
    if simulator is Simulator.GSPRO:
        return send_gspro_test_shot(endpoint[0], endpoint[1], shot)
    return send_e6_test_shot(endpoint[0], endpoint[1], shot)


def _friendly_socket_error(host: str, port: int, error: BaseException) -> str:
    if isinstance(error, SimulatorConnectionError):
        detail = str(error)
    elif isinstance(error, ConnectionRefusedError):
        detail = "nothing is listening at that address"
    elif isinstance(error, socket.timeout):
        detail = "the connection timed out"
    else:
        detail = str(error) or error.__class__.__name__
    return "Could not reach the simulator at {}:{}: {}".format(host, port, detail)


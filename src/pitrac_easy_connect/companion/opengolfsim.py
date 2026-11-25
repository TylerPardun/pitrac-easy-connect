"""Talking to OpenGolfSim on this computer.

PiTrac sends one simulator's format, GSPro's, and everything here starts from
that. OpenGolfSim has its own, so this is the one place a shot is translated
rather than passed on.

What its documentation leaves out, and this depends on:

* **One message per read.** It parses each packet as a whole message, so two
  arriving together are both dropped. Messages are spaced out.
* **Positive is right**, for the launch direction and the spin axis both. A
  comment in its examples says otherwise about the axis. Its own published
  result settles it: 1.2 degrees one way and an axis of -2.5 finishing within a
  hand's breadth of the target line needs them to be measured the same way.
* **A reply is not a shot played.** It answers every message, whether or not it
  is showing anything a ball could be hit on. Only a result means that.
"""

import json
import math
import re
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from ..common.errors import SIM_NOT_PLAYED, SIM_REJECTED_SHOT
from ..models import ShotData, Simulator
from ..protocols import gspro_message
from .simulator_session import ACCEPTED, PLAYED, REJECTED, UNKNOWN, Delivery, SimulatorSession

#: Two messages inside one read are both lost, so never closer together than this.
MESSAGE_GAP = 0.12

#: It takes a silent monitor to be gone. PiTrac's own sender uses the same.
KEEPALIVE_SECONDS = 5.0

#: How long to wait for what was said before a shot to be answered.
SETTLE_SECONDS = 0.5

#: How long a shot may still be in the air, or rolling, or being watched.
RESULT_SECONDS = 60.0

#: A test shot is worth waiting this long to see played.
TEST_RESULT_SECONDS = 20.0

ANGLE_LIMIT = 45.0
METRES_TO_YARDS = 1.0 / 0.9144


def shot_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A GSPro-format shot as OpenGolfSim takes it, or ``None`` without a ball."""

    ball = payload.get("BallData")
    if not isinstance(ball, dict):
        return None
    speed = _number(ball.get("Speed"))
    if speed is None or speed <= 0:
        return None
    back = _number(ball.get("BackSpin")) or 0.0
    side = _number(ball.get("SideSpin")) or 0.0
    total = _number(ball.get("TotalSpin"))
    if total is None:
        total = math.hypot(back, side)
    axis = math.degrees(math.atan2(side, back)) if back or side else 0.0
    return {
        "type": "shot",
        "unit": "imperial",
        "shot": {
            "ballSpeed": round(speed, 1),
            "verticalLaunchAngle": round(_within(_number(ball.get("VLA")) or 0.0, 0, ANGLE_LIMIT), 1),
            "horizontalLaunchAngle": round(
                _within(_number(ball.get("HLA")) or 0.0, -ANGLE_LIMIT, ANGLE_LIMIT), 1),
            "spinSpeed": round(total),
            "spinAxis": round(_within(axis, -ANGLE_LIMIT, ANGLE_LIMIT), 1),
        },
    }


def device_message(ready: bool) -> Dict[str, Any]:
    return {"type": "device", "status": "ready" if ready else "busy"}


def gspro_club(identifier: Any) -> str:
    """OpenGolfSim's ``7I`` as the ``I7`` the rest of this program reads."""

    text = str(identifier or "").strip().upper()
    match = re.fullmatch(r"(\d{1,2})\s*([WHI])", text)
    if match:
        return match.group(2) + match.group(1)
    return "PT" if text.startswith("PUTT") else text


def club_of(message: Dict[str, Any]) -> Optional[str]:
    """The club a player update names, in this program's terms."""

    data = message.get("data")
    club = data.get("club") if isinstance(data, dict) else None
    if not isinstance(club, dict):
        return None
    return gspro_club(club.get("id") or club.get("name")) or None


def result_of(message: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Where it says the ball went, in yards. It always reports metres."""

    data = message.get("data")
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        return None
    found = {}
    for ours, theirs in (("simCarry", "carry"), ("simTotal", "total"), ("simOffline", "lateral")):
        value = _number(result.get(theirs))
        if value is not None:
            found[ours] = round(value * METRES_TO_YARDS, 1)
    return found or None


class OpenGolfSimSession(SimulatorSession):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_result: Optional[Callable[[str, Dict[str, float]], None]] = None,
    ):
        super().__init__(Simulator.OGS, host, port, on_message)
        self.on_result = on_result
        self._ready = False
        # Held for a whole exchange, so that nothing else is said between a
        # shot and its answer and mistaken for part of it.
        self._gap_lock = threading.RLock()
        self._unanswered = 0
        self._last_sent = 0.0
        self._airborne: List[Dict[str, Any]] = []
        self._keepalive: Optional[threading.Thread] = None

    # --- Connecting -------------------------------------------------------

    def connect(self) -> None:
        already = self.connected
        super().connect()
        if already:
            return
        self.send(device_message(self._ready))
        if self._keepalive is None or not self._keepalive.is_alive():
            self._keepalive = threading.Thread(target=self._keep_alive, daemon=True)
            self._keepalive.start()

    def _keep_alive(self) -> None:
        while not self._stop.wait(KEEPALIVE_SECONDS):
            if not self.connected:
                return
            try:
                self.send(device_message(self._ready))
            except OSError:
                return

    def set_ready(self, ready: bool) -> None:
        """Whether there is a ball to hit."""

        self._ready = ready
        if self.connected:
            try:
                self.send(device_message(ready))
            except OSError:
                pass

    # --- Sending ----------------------------------------------------------

    def _encode(self, message: Dict[str, Any]) -> bytes:
        return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")

    def _prepare(self, sock: socket.socket) -> None:
        # A packet each, rather than as many as fit.
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def send(self, message: Dict[str, Any]) -> None:
        with self._gap_lock:
            wait = self._last_sent + MESSAGE_GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._unanswered += 1
            super().send(message)
            self._last_sent = time.monotonic()

    def _settle(self) -> None:
        """Let anything already said be answered first. Answers have no names on
        them, so the next one is taken to be about the latest message."""

        deadline = time.monotonic() + SETTLE_SECONDS
        while self._unanswered > 0 and self.connected and time.monotonic() < deadline:
            time.sleep(0.01)
        self._unanswered = 0

    def deliver(self, payload: Dict[str, Any], shot_id: str = "") -> Delivery:
        message = shot_message(payload)
        if message is None:
            return Delivery(REJECTED, "there was no ball in that shot")
        with self._lock:
            now = time.monotonic()
            self._airborne = [s for s in self._airborne if now - s["at"] < RESULT_SECONDS]
            self._airborne.append({"at": now, "shot": message["shot"], "id": shot_id})
        with self._gap_lock:
            self._settle()
            reply = self._answer_to(message, lambda reply: "status" in reply)
        if reply is None:
            return Delivery(UNKNOWN, "sent to OpenGolfSim, which has not answered")
        if reply.get("status") == 200:
            return Delivery(ACCEPTED, "OpenGolfSim took it")
        self._forget(shot_id)
        return Delivery(REJECTED, str(reply.get("error") or "OpenGolfSim refused it"))

    def _forget(self, shot_id: str) -> None:
        with self._lock:
            self._airborne = [s for s in self._airborne if s["id"] != shot_id]

    # --- Hearing back -----------------------------------------------------

    def _dispatch(self, message: Dict[str, Any]) -> None:
        if "status" in message:
            self._unanswered = max(0, self._unanswered - 1)
        if message.get("type") == "result":
            self._landed(message)
        super()._dispatch(message)

    def _landed(self, message: Dict[str, Any]) -> None:
        """Match a result to the shot it is for.

        By the numbers it echoes, not by which came last. Somebody using a mouse
        or another monitor also makes results, and those belong to no shot here.
        """

        result = result_of(message)
        echoed = message["data"].get("shot") if isinstance(message.get("data"), dict) else None
        if result is None or not isinstance(echoed, dict):
            return
        now = time.monotonic()
        with self._lock:
            found = next((s for s in self._airborne
                          if now - s["at"] < RESULT_SECONDS and _same(s["shot"], echoed)), None)
            if found is None:
                return
            self._airborne.remove(found)
        if self.on_result is not None:
            try:
                self.on_result(found["id"], result)
            except Exception:
                pass

    def send_test_shot(self, shot: ShotData) -> Dict[str, Any]:
        played = threading.Event()
        seen: List[Dict[str, float]] = []
        real = self.on_result

        def landed(shot_id: str, result: Dict[str, float]) -> None:
            if shot_id == "test":
                seen.append(result)
                played.set()
            elif real is not None:
                real(shot_id, result)

        self.on_result = landed
        try:
            delivery = self.deliver(gspro_message(shot), "test")
            if delivery.outcome == REJECTED:
                return {"accepted": False, "code": SIM_REJECTED_SHOT.code, "response": None}
            if played.wait(TEST_RESULT_SECONDS):
                return {"accepted": True, "code": "", "response": seen[0]}
            return {"accepted": False, "code": SIM_NOT_PLAYED.code, "response": None}
        finally:
            self.on_result = real
            self._forget("test")


def _same(sent: Dict[str, Any], echoed: Dict[str, Any]) -> bool:
    for key, tolerance in (("ballSpeed", 0.15), ("verticalLaunchAngle", 0.15),
                           ("horizontalLaunchAngle", 0.15), ("spinSpeed", 2.0)):
        theirs = _number(echoed.get(key))
        if theirs is None or abs(theirs - sent[key]) > tolerance:
            return False
    return True


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _within(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


__all__ = ["OpenGolfSimSession", "PLAYED", "club_of", "shot_message"]

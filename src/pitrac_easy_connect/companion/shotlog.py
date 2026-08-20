"""A record of the shots that passed through, so they can be looked at later.

PiTrac measures the ball and keeps its own history. This is not a copy of that;
it is the one thing this side knows and the enclosure does not: **which club was
in your hands.**

Simulators tell the launch monitor when the player changes club — GSPro sends
player information down the same connection it uses to acknowledge shots — and
every one of those messages already passes through the relay on its way back to
PiTrac. So the club can be attached to each shot without asking anyone to type
anything.

The log is written to disk so a session survives closing the app, and is capped
so it cannot grow without bound on someone's PC.
"""

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common.configstore import ConfigStore

#: How many shots to keep. Comfortably more than a long session, small enough
#: that the file stays trivial to read and write.
MAX_SHOTS = 500

#: Clubs as simulators name them, mapped to something readable. Anything not
#: listed is passed through as-is rather than dropped.
CLUB_NAMES = {
    "DR": "Driver", "D": "Driver", "DRIVER": "Driver",
    "W2": "2 wood", "W3": "3 wood", "W4": "4 wood", "W5": "5 wood", "W7": "7 wood",
    "H2": "2 hybrid", "H3": "3 hybrid", "H4": "4 hybrid", "H5": "5 hybrid",
    "I1": "1 iron", "I2": "2 iron", "I3": "3 iron", "I4": "4 iron", "I5": "5 iron",
    "I6": "6 iron", "I7": "7 iron", "I8": "8 iron", "I9": "9 iron",
    "PW": "Pitching wedge", "GW": "Gap wedge", "AW": "Approach wedge",
    "SW": "Sand wedge", "LW": "Lob wedge", "PT": "Putter", "PUTTER": "Putter",
}


def readable_club(raw: Optional[str]) -> str:
    if not raw:
        return ""
    key = str(raw).strip().upper()
    return CLUB_NAMES.get(key, str(raw).strip())


def club_from_simulator_message(message: Dict[str, Any]) -> Optional[str]:
    """Pull a club out of whatever the simulator sent, if there is one.

    Written to be forgiving. Simulators differ, versions differ, and a message
    shape that is not recognised should mean "no club here" rather than an
    error in the middle of someone's round.
    """

    if not isinstance(message, dict):
        return None

    player = message.get("Player")
    if isinstance(player, dict):
        for key in ("Club", "club", "ClubType"):
            if player.get(key):
                return str(player[key])

    for key in ("Club", "ClubType", "club"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value

    club_data = message.get("ClubData")
    if isinstance(club_data, dict):
        for key in ("Club", "ClubType", "Name"):
            if club_data.get(key):
                return str(club_data[key])
    return None


def ball_from_shot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The numbers worth keeping, from either simulator's shot format."""

    ball = payload.get("BallData")
    if isinstance(ball, dict) and ball:
        return {
            "speed": _number(ball.get("Speed") or ball.get("BallSpeed")),
            "launch": _number(ball.get("VLA") or ball.get("LaunchAngle")),
            "direction": _number(ball.get("HLA") or ball.get("LaunchDirection")),
            "backSpin": _number(ball.get("BackSpin")),
            "sideSpin": _number(ball.get("SideSpin")),
            "totalSpin": _number(ball.get("TotalSpin")),
        }
    return {}


def _number(value: Any) -> Optional[float]:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


@dataclass
class Shot:
    at: float
    club: str = ""
    simulator: str = ""
    delivered: bool = True
    ball: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "at": self.at,
            "timeText": time.strftime("%H:%M:%S", time.localtime(self.at)),
            "club": self.club,
            "simulator": self.simulator,
            "delivered": self.delivered,
            **self.ball,
        }


class ShotLog:
    def __init__(self, path: Path, limit: int = MAX_SHOTS):
        self._lock = threading.RLock()
        self._limit = limit
        self._store = ConfigStore(path, defaults={"shots": [], "club": ""})
        self._club = str(self._store.get("club") or "")

    # --- Recording --------------------------------------------------------

    @property
    def club(self) -> str:
        with self._lock:
            return self._club

    def note_simulator_message(self, message: Dict[str, Any]) -> Optional[str]:
        """Watch the return path for a club change. Returns the club if it changed."""

        club = club_from_simulator_message(message)
        if not club:
            return None
        readable = readable_club(club)
        with self._lock:
            if readable == self._club:
                return None
            self._club = readable
            self._store.set("club", readable)
        return readable

    def set_club(self, club: str) -> str:
        """Set the club by hand, for when the simulator does not report one."""

        readable = readable_club(club)
        with self._lock:
            self._club = readable
            self._store.set("club", readable)
        return readable

    def record(self, payload: Dict[str, Any], simulator: str, delivered: bool = True) -> Shot:
        shot = Shot(
            at=time.time(),
            club=self.club,
            simulator=simulator,
            delivered=delivered,
            ball=ball_from_shot(payload),
        )
        with self._lock:
            shots = list(self._store.get("shots") or [])
            shots.append(shot.as_dict())
            del shots[: max(0, len(shots) - self._limit)]
            self._store.set("shots", shots)
        return shot

    # --- Reading ----------------------------------------------------------

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            shots = list(self._store.get("shots") or [])
        return list(reversed(shots[-limit:]))

    def by_club(self) -> List[Dict[str, Any]]:
        """Averages per club, which is the reason for keeping any of this."""

        with self._lock:
            shots = list(self._store.get("shots") or [])

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for shot in shots:
            if not shot.get("delivered"):
                continue
            grouped.setdefault(shot.get("club") or "Not recorded", []).append(shot)

        summary = []
        for club, entries in grouped.items():
            speeds = _values(entries, "speed")
            summary.append(
                {
                    "club": club,
                    "shots": len(entries),
                    "speed": _average(entries, "speed"),
                    "launch": _average(entries, "launch"),
                    "backSpin": _average(entries, "backSpin"),
                    "sideSpin": _average(entries, "sideSpin"),
                    "direction": _average(entries, "direction"),
                    "bestSpeed": round(max(speeds), 1) if speeds else None,
                    "worstSpeed": round(min(speeds), 1) if speeds else None,
                    # How tightly the strikes cluster. A driver at 148, 149, 150
                    # is a different player from one at 130, 148, 168, and the
                    # average alone hides that entirely.
                    "spread": round(max(speeds) - min(speeds), 1) if len(speeds) > 1 else None,
                    "lastAt": max(entry.get("at") or 0 for entry in entries),
                }
            )
        # Most recently used first: that is the club they are hitting now.
        return sorted(summary, key=lambda item: item["lastAt"], reverse=True)

    def clear(self) -> None:
        with self._lock:
            self._store.set("shots", [])

    def status(self, limit: int = 25) -> Dict[str, Any]:
        return {
            "club": self.club,
            "recent": self.recent(limit),
            "byClub": self.by_club(),
            "total": len(self._store.get("shots") or []),
        }


def _values(entries: List[Dict[str, Any]], key: str) -> List[float]:
    return [entry[key] for entry in entries if isinstance(entry.get(key), (int, float))]


def _average(entries: List[Dict[str, Any]], key: str) -> Optional[float]:
    values = _values(entries, key)
    if not values:
        return None
    return round(sum(values) / len(values), 1)

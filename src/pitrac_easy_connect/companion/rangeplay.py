"""The practice range: what has been hit, and where it went.

Holds a session in memory only. A range session is a bucket of balls, not a
record worth keeping, and writing every shot to disk twice -- the shot log
already keeps them -- would be the wrong trade.

The trajectory is computed here rather than in the browser so it can be tested,
so there is one implementation rather than one per platform, and so the page
stays pure presentation. A trajectory is roughly 120 points after
downsampling, which is a few kilobytes over loopback, so the round trip costs
nothing worth measuring.
"""

import math
import threading
import time
from typing import Any, Dict, List, Optional

from . import flight

#: How many shots stay on the range. Enough to show a dispersion pattern,
#: bounded so a long session cannot grow without limit.
MAX_SHOTS = 60

#: Distances offered as one press, in yards. Any other can be dialled in.
TARGETS = (50, 75, 100, 125, 150, 175, 200, 225)
NEAREST_TARGET, FARTHEST_TARGET, DEFAULT_TARGET = 20, 300, 150

#: How far from the flag still counts as on the green, in yards.
GREEN_RADIUS = 11.0

#: Distance markers, in yards.
MARKERS = (50, 100, 150, 200, 250, 300)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _measured(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class RangeSession:
    """Shots hit since the range was last cleared."""

    def __init__(self, limit: int = MAX_SHOTS):
        self._lock = threading.RLock()
        self._revision = 0
        self._limit = limit
        self._shots: List[Dict[str, Any]] = []
        self._next_id = 1
        self._unflown: Optional[Dict[str, Any]] = None
        self._target = DEFAULT_TARGET
        self.conditions = {
            "pressurePa": flight.STANDARD_PRESSURE_PA,
            "temperatureC": flight.STANDARD_TEMPERATURE_C,
            "relativeHumidity": 0.0,
        }

    # --- Conditions -------------------------------------------------------

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    @property
    def density(self) -> float:
        with self._lock:
            return flight.air_density(
                self.conditions["pressurePa"],
                self.conditions["temperatureC"],
                self.conditions["relativeHumidity"],
            )

    def set_conditions(
        self,
        pressure_pa: Optional[float] = None,
        temperature_c: Optional[float] = None,
        relative_humidity: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Set the air the ball flies through. Affects every later shot."""

        with self._lock:
            self._revision += 1
            if pressure_pa is not None:
                self.conditions["pressurePa"] = max(10000.0, min(110000.0, _finite(
                    pressure_pa, flight.STANDARD_PRESSURE_PA)))
            if temperature_c is not None:
                self.conditions["temperatureC"] = max(-40.0, min(60.0, _finite(
                    temperature_c, flight.STANDARD_TEMPERATURE_C)))
            if relative_humidity is not None:
                self.conditions["relativeHumidity"] = max(0.0, min(1.0, _finite(
                    relative_humidity, 0.0)))
            return dict(self.conditions, density=self.density)

    # --- The target -------------------------------------------------------

    @property
    def target(self) -> int:
        with self._lock:
            return self._target

    def set_target(self, yards: Any) -> int:
        """Where the flag stands. Shots already hit keep the one they were for."""

        wanted = int(round(_finite(yards, DEFAULT_TARGET)))
        with self._lock:
            self._revision += 1
            self._target = max(NEAREST_TARGET, min(FARTHEST_TARGET, wanted))
            return self._target

    # --- Recording --------------------------------------------------------

    def record(self, ball: Dict[str, Any], club: str = "") -> Optional[Dict[str, Any]]:
        """Fly one measured shot and add it to the range.

        ``ball`` is the normalised shape the shot log produces. A shot the
        model cannot fly is not added as a flat line, because a dot on the tee
        looks like a bug. It is remembered as the latest one instead, so that a
        putt does not look like a swing that was missed.
        """

        measured = {
            key: _measured(ball.get(key))
            for key in ("speed", "launch", "direction", "backSpin", "sideSpin")
        }

        result = flight.simulate(
            _finite(ball.get("speed")),
            _finite(ball.get("launch")),
            _finite(ball.get("direction")),
            _finite(ball.get("backSpin")),
            _finite(ball.get("sideSpin")),
            density=self.density,
        )
        if not result["points"]:
            with self._lock:
                self._revision += 1
                self._unflown = {"at": time.time(), "club": club or "", "ball": measured}
            return None

        with self._lock:
            self._revision += 1
            shot = {
                "id": self._next_id,
                "at": time.time(),
                "club": club or "",
                # None where the launch monitor gave nothing. The flight above
                # has to assume zero for those; the numbers shown must not
                # claim zero was measured.
                "ball": measured,
                **{key: value for key, value in result.items() if key != "points"},
                **self._against_target(result),
                "points": result["points"],
            }
            self._next_id += 1
            self._unflown = None
            self._shots.append(shot)
            del self._shots[: max(0, len(self._shots) - self._limit)]
            return shot

    def _against_target(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """How close it finished, by the flight model's own estimate of the roll."""

        away = math.hypot(result["totalYards"] - self._target, result["offlineYards"])
        return {"target": self._target, "toPinYards": away, "onGreen": away <= GREEN_RADIUS}

    def clear(self) -> Dict[str, Any]:
        with self._lock:
            self._revision += 1
            self._shots = []
            self._unflown = None
        return self.status()

    # --- Reading ----------------------------------------------------------

    def shots(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._shots)

    def by_club(self) -> List[Dict[str, Any]]:
        """Per-club averages and dispersion over the session."""

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for shot in self.shots():
            grouped.setdefault(shot["club"] or "Unknown", []).append(shot)

        summary = []
        for club, shots in grouped.items():
            carries = [s["carryYards"] for s in shots]
            offsets = [s["offlineYards"] for s in shots]
            summary.append({
                "club": club,
                "shots": len(shots),
                "carryAvg": sum(carries) / len(carries),
                "carryBest": max(carries),
                "carrySpread": max(carries) - min(carries),
                "offlineAvg": sum(offsets) / len(offsets),
                # Two standard deviations either side is the ellipse a golfer
                # recognises as "where my shots go".
                "carrySigma": _sigma(carries),
                "offlineSigma": _sigma(offsets),
                "apexAvg": sum(s["apexFeet"] for s in shots) / len(shots),
            })
        summary.sort(key=lambda row: row["carryAvg"], reverse=True)
        return summary

    def status(self, trace_limit: int = 12) -> Dict[str, Any]:
        """Everything the page draws.

        Only the most recent few shots carry their full trajectory; the rest
        are reduced to where they landed. A session of sixty full traces is a
        payload nobody needs three times a second.
        """

        shots = self.shots()
        recent = shots[-trace_limit:]
        keep = {shot["id"] for shot in recent}
        return {
            "shots": [
                shot if shot["id"] in keep else _without_points(shot)
                for shot in shots
            ],
            "byClub": self.by_club(),
            "target": self.target,
            "targets": list(TARGETS),
            "greenRadius": GREEN_RADIUS,
            "markers": list(MARKERS),
            "conditions": dict(self.conditions, density=self.density),
            "count": len(shots),
            "unflown": self._unflown,
        }


def _without_points(shot: Dict[str, Any]) -> Dict[str, Any]:
    trimmed = dict(shot)
    trimmed["points"] = []
    return trimmed


def _sigma(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))

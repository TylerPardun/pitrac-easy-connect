"""Where a golf ball goes, from the five numbers PiTrac measures.

Pure functions. No I/O, no state, no dependency outside the standard library,
so it can be tested directly and gives the same answer everywhere.

The model is drag plus Magnus lift, integrated with fourth-order Runge-Kutta.
Inputs are ball speed, vertical and horizontal launch angle, backspin and
sidespin, which is exactly what the relay already carries.

**On air density.** Carry depends on it directly, and it is the one piece of
real meteorology a golf shot needs: the same swing carries about a tenth
further in Denver than at sea level, and a cold morning is measurably shorter
than a hot afternoon. Density is computed from station pressure, temperature
and humidity through the virtual temperature, using the constants a
meteorologist would expect (``rd`` 287.04, ``rv`` 461.5).

A ball never leaves the surface layer -- apex is around 30 m -- so surface-layer
similarity is the right scale for anything to do with wind, if wind is ever
added. A cloud-resolving model is three orders of magnitude too large for this
problem and could not run inside a desktop app in any case.

The drag and lift coefficients were fitted to published PGA Tour launch
conditions and carries across the bag, and landed inside the range wind-tunnel
work reports for dimpled spheres, so they describe physics rather than being
tuned to hit six numbers. Across the six clubs it was fitted against, carry
is within about 8 yards and apex within about 6 feet; the worst case is the
driver, which comes up short.
"""

import math
from typing import Dict, List, Tuple

# --- The ball, and the air it flies through -------------------------------

#: Kilograms. The R&A and USGA maximum, which is what a ball is built to.
BALL_MASS_KG = 0.04593
#: Metres. Half the minimum legal diameter of 42.67 mm.
BALL_RADIUS_M = 0.021335
BALL_AREA_M2 = math.pi * BALL_RADIUS_M**2

GRAVITY = 9.80665
#: Dry air gas constant, J/(kg K).
R_DRY = 287.04
#: Water vapour gas constant, J/(kg K).
R_VAPOUR = 461.5
#: Sea level standard atmosphere.
STANDARD_PRESSURE_PA = 101325.0
STANDARD_TEMPERATURE_C = 15.0
STANDARD_DENSITY = 1.225

MPH_TO_MS = 0.44704
RPM_TO_RADS = 2.0 * math.pi / 60.0
M_TO_YARDS = 1.0 / 0.9144
M_TO_FEET = 1.0 / 0.3048

# --- Aerodynamics ----------------------------------------------------------

_CD_BASE = 0.2160
_CD_SPIN = 0.2870
_CD_REYNOLDS = 0.0035
_CD_FLOOR = 0.15
_CL_MAX = 0.3254
_CL_RATE = 7.6231
_REFERENCE_SPEED = 60.0
#: Spin bleeds off in flight. Per second, as a fraction.
_SPIN_DECAY = 0.0343
#: Above this the fits are extrapolation, so they are held flat rather than
#: allowed to run away.
_MAX_SPIN_RATIO = 0.6


def air_density(
    pressure_pa: float = STANDARD_PRESSURE_PA,
    temperature_c: float = STANDARD_TEMPERATURE_C,
    relative_humidity: float = 0.0,
) -> float:
    """Air density from station pressure, temperature and humidity.

    Through the virtual temperature, so humid air is correctly lighter than dry
    air at the same pressure and temperature.
    """

    kelvin = temperature_c + 273.15
    if kelvin <= 0 or pressure_pa <= 0:
        return STANDARD_DENSITY

    # Saturation vapour pressure, Bolton (1980).
    saturation = 611.2 * math.exp(17.67 * temperature_c / (temperature_c + 243.5))
    vapour = max(0.0, min(1.0, relative_humidity)) * saturation
    mixing = (R_DRY / R_VAPOUR) * vapour / max(pressure_pa - vapour, 1.0)
    virtual_kelvin = kelvin * (1.0 + mixing / (R_DRY / R_VAPOUR)) / (1.0 + mixing)
    return pressure_pa / (R_DRY * virtual_kelvin)


def _coefficients(spin_ratio: float, speed: float) -> Tuple[float, float]:
    ratio = min(max(spin_ratio, 0.0), _MAX_SPIN_RATIO)
    drag = (
        _CD_BASE
        + _CD_SPIN * ratio
        + _CD_REYNOLDS * (_REFERENCE_SPEED / max(speed, 12.0) - 1.0)
    )
    lift = _CL_MAX * (1.0 - math.exp(-_CL_RATE * ratio))
    return max(drag, _CD_FLOOR), lift


def _acceleration(
    velocity: Tuple[float, float, float],
    spin: Tuple[float, float, float],
    density: float,
) -> Tuple[float, float, float]:
    vx, vy, vz = velocity
    speed = math.sqrt(vx * vx + vy * vy + vz * vz)
    if speed < 1e-9:
        return (0.0, -GRAVITY, 0.0)

    omega = math.sqrt(sum(component * component for component in spin))
    drag_c, lift_c = _coefficients(omega * BALL_RADIUS_M / speed, speed)
    pressure = 0.5 * density * BALL_AREA_M2 * speed * speed

    ax = -drag_c * pressure * vx / speed
    ay = -drag_c * pressure * vy / speed
    az = -drag_c * pressure * vz / speed

    # Magnus force acts along the spin axis crossed with the direction of travel.
    sx, sy, sz = spin
    cx = sy * vz - sz * vy
    cy = sz * vx - sx * vz
    cz = sx * vy - sy * vx
    cross = math.sqrt(cx * cx + cy * cy + cz * cz)
    if cross > 1e-9:
        ax += lift_c * pressure * cx / cross
        ay += lift_c * pressure * cy / cross
        az += lift_c * pressure * cz / cross

    return (ax / BALL_MASS_KG, ay / BALL_MASS_KG - GRAVITY, az / BALL_MASS_KG)


# --- The flight itself -----------------------------------------------------

#: Seconds. Small enough that halving it moves carry by well under a yard, and
#: large enough that a whole flight is a few thousand steps.
TIMESTEP = 0.002
#: A ball that is still up after this was not a golf shot.
MAX_FLIGHT_SECONDS = 15.0
#: What gets sent to the page. Enough to draw a smooth arc, few enough to stay
#: a small payload.
TRACE_POINTS = 120


def _roll_out(landing_speed: float, descent_deg: float) -> float:
    """A rough run-out after landing, in metres.

    Deliberately simple, and labelled as an estimate wherever it is shown. Real
    run-out depends on turf, moisture and slope, none of which the enclosure can
    know. A steeply descending wedge stops; a shallow driver runs.
    """

    if landing_speed <= 0:
        return 0.0
    steepness = max(0.0, min(1.0, math.sin(math.radians(max(descent_deg, 0.0)))))
    return max(0.0, landing_speed * 0.34 * (1.0 - steepness) ** 1.6)


def simulate(
    ball_speed_mph: float,
    launch_angle_deg: float,
    azimuth_deg: float = 0.0,
    backspin_rpm: float = 0.0,
    sidespin_rpm: float = 0.0,
    density: float = STANDARD_DENSITY,
    timestep: float = TIMESTEP,
) -> Dict[str, object]:
    """Fly one shot and report where it went.

    ``azimuth_deg`` is positive to the right. ``sidespin_rpm`` is positive for
    spin that curves the ball to the right, so a slice for a right-hander.

    Anything unusable -- no speed, a shot hit straight into the ground --
    returns an empty trajectory rather than raising, because a launch monitor
    does produce nonsense occasionally and the range should shrug.
    """

    speed = float(ball_speed_mph) * MPH_TO_MS
    if not math.isfinite(speed) or speed <= 0.0:
        return _nothing()

    launch = math.radians(_finite(launch_angle_deg))
    azimuth = math.radians(_finite(azimuth_deg))
    if launch <= 0.0:
        return _nothing()

    velocity = (
        speed * math.cos(launch) * math.cos(azimuth),
        speed * math.sin(launch),
        speed * math.cos(launch) * math.sin(azimuth),
    )
    # Backspin turns about the axis across the line of flight; sidespin about
    # the vertical. Negated so that positive sidespin curves right.
    spin = (
        0.0,
        -_finite(sidespin_rpm) * RPM_TO_RADS,
        _finite(backspin_rpm) * RPM_TO_RADS,
    )

    position = (0.0, 0.0, 0.0)
    points: List[Tuple[float, float, float]] = [position]
    apex = 0.0
    elapsed = 0.0
    decay = 1.0 - _SPIN_DECAY * timestep

    while position[1] >= 0.0 and elapsed < MAX_FLIGHT_SECONDS:
        position, velocity = _step(position, velocity, spin, density, timestep)
        spin = (spin[0] * decay, spin[1] * decay, spin[2] * decay)
        points.append(position)
        apex = max(apex, position[1])
        elapsed += timestep

    # The last step went under the ground; land it exactly on the surface.
    if len(points) >= 2 and points[-1][1] < 0.0:
        points[-1] = _ground_crossing(points[-2], points[-1])

    landing_speed = math.sqrt(sum(component * component for component in velocity))
    descent = math.degrees(math.atan2(-velocity[1], math.hypot(velocity[0], velocity[2]) or 1e-9))
    carry = points[-1][0]
    roll = _roll_out(landing_speed, descent)

    return {
        "carryYards": carry * M_TO_YARDS,
        "totalYards": (carry + roll * math.cos(math.atan2(points[-1][2], carry or 1e-9))) * M_TO_YARDS,
        "offlineYards": points[-1][2] * M_TO_YARDS,
        "apexFeet": apex * M_TO_FEET,
        "flightSeconds": elapsed,
        "descentDegrees": descent,
        "landingSpeedMph": landing_speed / MPH_TO_MS,
        "points": _downsample(points, TRACE_POINTS),
    }


def _step(position, velocity, spin, density, dt):
    """One Runge-Kutta 4 step.

    Worth the four evaluations: with plain Euler the carry depends visibly on
    the timestep, which makes the physics feel arbitrary.
    """

    def derivatives(pos, vel):
        return vel, _acceleration(vel, spin, density)

    k1p, k1v = derivatives(position, velocity)
    k2p, k2v = derivatives(_add(position, k1p, dt / 2), _add(velocity, k1v, dt / 2))
    k3p, k3v = derivatives(_add(position, k2p, dt / 2), _add(velocity, k2v, dt / 2))
    k4p, k4v = derivatives(_add(position, k3p, dt), _add(velocity, k3v, dt))

    new_position = tuple(
        position[i] + dt / 6 * (k1p[i] + 2 * k2p[i] + 2 * k3p[i] + k4p[i]) for i in range(3)
    )
    new_velocity = tuple(
        velocity[i] + dt / 6 * (k1v[i] + 2 * k2v[i] + 2 * k3v[i] + k4v[i]) for i in range(3)
    )
    return new_position, new_velocity


def _add(vector, delta, scale):
    return tuple(vector[i] + delta[i] * scale for i in range(3))


def _ground_crossing(above, below):
    """Where the line between the last two samples meets the ground."""

    span = above[1] - below[1]
    if span <= 0:
        return (below[0], 0.0, below[2])
    fraction = above[1] / span
    return (
        above[0] + (below[0] - above[0]) * fraction,
        0.0,
        above[2] + (below[2] - above[2]) * fraction,
    )


def _downsample(points, count):
    """Keep the shape, drop the samples. The last point is always kept."""

    if len(points) <= count:
        return [[round(c, 3) for c in point] for point in points]
    step = (len(points) - 1) / float(count - 1)
    picked = [points[min(int(round(i * step)), len(points) - 1)] for i in range(count)]
    picked[-1] = points[-1]
    return [[round(c, 3) for c in point] for point in picked]


def _finite(value: float) -> float:
    number = float(value)
    return number if math.isfinite(number) else 0.0


def _nothing() -> Dict[str, object]:
    return {
        "carryYards": 0.0, "totalYards": 0.0, "offlineYards": 0.0,
        "apexFeet": 0.0, "flightSeconds": 0.0, "descentDegrees": 0.0,
        "landingSpeedMph": 0.0, "points": [],
    }

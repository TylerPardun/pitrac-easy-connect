"""Ball flight, against numbers that exist outside this project.

A physics model is easy to make self-consistent and wrong. These check it
against published PGA Tour launch conditions and carries, so the model has to
agree with reality rather than with itself.
"""

import math

import pytest

from pitrac_easy_connect.companion import flight

#: Trackman's published Tour averages: ball speed mph, launch degrees, backspin
#: rpm, carry yards, apex feet.
TOUR = [
    ("driver", 167.0, 10.9, 2686, 275, 102),
    ("3 wood", 158.0, 9.2, 3655, 243, 95),
    ("5 iron", 132.0, 12.1, 5280, 194, 94),
    ("7 iron", 120.0, 16.3, 7097, 172, 90),
    ("9 iron", 112.0, 20.4, 8647, 148, 89),
    ("pitching wedge", 102.0, 24.2, 9304, 136, 87),
]


# --- T1, T2: it agrees with reality ---------------------------------------


@pytest.mark.parametrize("club,speed,launch,spin,carry,apex", TOUR, ids=[c[0] for c in TOUR])
def test_carry_matches_tour_averages(club, speed, launch, spin, carry, apex):
    result = flight.simulate(speed, launch, 0.0, spin, 0.0)
    assert abs(result["carryYards"] - carry) <= 10, "{}: {:.0f} vs {}".format(
        club, result["carryYards"], carry
    )


@pytest.mark.parametrize("club,speed,launch,spin,carry,apex", TOUR, ids=[c[0] for c in TOUR])
def test_apex_matches_tour_averages(club, speed, launch, spin, carry, apex):
    result = flight.simulate(speed, launch, 0.0, spin, 0.0)
    assert abs(result["apexFeet"] - apex) <= 10, "{}: {:.0f} vs {}".format(
        club, result["apexFeet"], apex
    )


def test_the_clubs_stay_in_order():
    """Whatever the absolute error, a driver must out-carry a wedge."""

    carries = [
        flight.simulate(speed, launch, 0.0, spin, 0.0)["carryYards"]
        for _club, speed, launch, spin, _carry, _apex in TOUR
    ]
    assert carries == sorted(carries, reverse=True)


# --- T3: spin does what a golfer expects ----------------------------------


def test_sidespin_curves_the_ball_right():
    straight = flight.simulate(120, 16.3, 0.0, 7097, 0)
    sliced = flight.simulate(120, 16.3, 0.0, 7097, 1500)
    assert sliced["offlineYards"] > straight["offlineYards"] + 5


def test_sidespin_the_other_way_curves_it_left():
    hooked = flight.simulate(120, 16.3, 0.0, 7097, -1500)
    assert hooked["offlineYards"] < -5


def test_more_sidespin_curves_further():
    offsets = [
        flight.simulate(120, 16.3, 0.0, 7097, rpm)["offlineYards"]
        for rpm in (0, 500, 1000, 2000)
    ]
    assert offsets == sorted(offsets)


def test_aim_is_separate_from_curve():
    """Azimuth starts the ball right; sidespin bends it. They are not the same."""

    aimed = flight.simulate(120, 16.3, 5.0, 7097, 0)
    assert aimed["offlineYards"] > 10
    assert abs(aimed["carryYards"] - flight.simulate(120, 16.3, 0.0, 7097, 0)["carryYards"]) < 2


def test_backspin_keeps_the_ball_up():
    low = flight.simulate(150, 12.0, 0.0, 1500, 0)
    high = flight.simulate(150, 12.0, 0.0, 4000, 0)
    assert high["apexFeet"] > low["apexFeet"]


# --- T4, T6: it is a model, not a random number generator -----------------


def test_the_same_shot_gives_the_same_answer():
    first = flight.simulate(150, 12.0, 1.5, 3000, 250)
    second = flight.simulate(150, 12.0, 1.5, 3000, 250)
    assert first == second


def test_halving_the_timestep_barely_moves_the_answer():
    """If the answer depends on the timestep, it is arithmetic, not physics."""

    coarse = flight.simulate(167, 10.9, 0.0, 2686, 0, timestep=0.004)
    fine = flight.simulate(167, 10.9, 0.0, 2686, 0, timestep=0.0005)
    assert abs(coarse["carryYards"] - fine["carryYards"]) < 1.0


def test_the_trajectory_is_small_enough_to_send():
    result = flight.simulate(167, 10.9, 0.0, 2686, 0)
    assert 2 <= len(result["points"]) <= flight.TRACE_POINTS
    assert result["points"][0] == [0.0, 0.0, 0.0]
    assert result["points"][-1][1] == pytest.approx(0.0, abs=0.01), "it must land on the ground"


def test_the_trajectory_actually_arcs():
    points = flight.simulate(120, 16.3, 0.0, 7097, 0)["points"]
    heights = [p[1] for p in points]
    peak = heights.index(max(heights))
    assert 0 < peak < len(heights) - 1
    assert heights[:peak] == sorted(heights[:peak])


# --- T5: rubbish in, nothing out, never an exception ----------------------


@pytest.mark.parametrize(
    "arguments",
    [
        (0, 12, 0, 3000, 0),
        (-40, 12, 0, 3000, 0),
        (150, 0, 0, 3000, 0),
        (150, -10, 0, 3000, 0),
        (float("nan"), 12, 0, 3000, 0),
        (float("inf"), 12, 0, 3000, 0),
        (150, float("nan"), 0, 3000, 0),
    ],
)
def test_an_impossible_shot_returns_nothing_rather_than_raising(arguments):
    result = flight.simulate(*arguments)
    assert result["carryYards"] == 0.0
    assert result["points"] == []


def test_an_enormous_shot_still_terminates():
    result = flight.simulate(400, 45, 0, 20000, 5000)
    assert result["flightSeconds"] <= flight.MAX_FLIGHT_SECONDS
    assert math.isfinite(result["carryYards"])


# --- Air density ----------------------------------------------------------


def test_standard_atmosphere_is_the_standard_value():
    assert flight.air_density() == pytest.approx(1.225, abs=0.002)


def test_altitude_adds_distance():
    """The reason a shot carries further in Denver, and the commonest question
    anyone asks about a launch monitor's numbers."""

    sea = flight.simulate(167, 10.9, 0, 2686, 0, density=flight.air_density())
    denver = flight.simulate(
        167, 10.9, 0, 2686, 0, density=flight.air_density(83000, 25.0)
    )
    gain = denver["carryYards"] - sea["carryYards"]
    assert 15 < gain < 40, "expected roughly a club's worth, got {:.0f} yd".format(gain)


def test_cold_air_is_shorter_than_warm():
    cold = flight.air_density(101325, 0.0)
    warm = flight.air_density(101325, 30.0)
    assert cold > warm


def test_humid_air_is_lighter_than_dry():
    """Counter-intuitive to most people, and correct: water vapour is lighter
    than the nitrogen and oxygen it displaces."""

    dry = flight.air_density(101325, 25.0, 0.0)
    humid = flight.air_density(101325, 25.0, 1.0)
    assert humid < dry


def test_nonsense_conditions_fall_back_to_standard():
    assert flight.air_density(0, -500) == flight.STANDARD_DENSITY

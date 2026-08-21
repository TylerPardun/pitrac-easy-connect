"""The practice range: session state, and the shot path that feeds it."""

import pytest

from pitrac_easy_connect.companion import flight
from pitrac_easy_connect.companion.rangeplay import RangeSession
from test_companion import rig  # noqa: F401  (fixture)

SEVEN_IRON = {"speed": 120.0, "launch": 16.3, "direction": 0.0,
              "backSpin": 7097.0, "sideSpin": 0.0}


def test_a_shot_lands_on_the_range():
    session = RangeSession()
    shot = session.record(SEVEN_IRON, "7 iron")
    assert shot["club"] == "7 iron"
    assert 160 < shot["carryYards"] < 180
    assert len(shot["points"]) > 2


def test_shots_are_numbered_so_the_page_can_tell_them_apart():
    """The page animates a shot only when a new id appears."""

    session = RangeSession()
    ids = [session.record(SEVEN_IRON, "7 iron")["id"] for _ in range(3)]
    assert ids == [1, 2, 3]


def test_an_unflyable_shot_is_dropped_rather_than_drawn_flat():
    """A dot sitting on the tee looks like a bug, not like a bad swing."""

    session = RangeSession()
    assert session.record({"speed": 0, "launch": 0}, "Driver") is None
    assert session.status()["count"] == 0


def test_a_shot_with_missing_numbers_does_not_raise():
    session = RangeSession()
    session.record({}, "")
    session.record({"speed": None, "launch": "nonsense"}, "")
    assert session.status()["count"] == 0


def test_the_range_does_not_grow_without_bound():
    session = RangeSession(limit=5)
    for _ in range(20):
        session.record(SEVEN_IRON, "7 iron")
    assert session.status()["count"] == 5


def test_clearing_empties_it():
    session = RangeSession()
    session.record(SEVEN_IRON, "7 iron")
    assert session.clear()["count"] == 0


# --- What the page receives ------------------------------------------------


def test_only_recent_shots_carry_their_trajectory():
    """Sixty full traces polled once a second is a payload nobody needs."""

    session = RangeSession()
    for _ in range(20):
        session.record(SEVEN_IRON, "7 iron")

    status = session.status(trace_limit=5)
    with_points = [s for s in status["shots"] if s["points"]]
    assert len(with_points) == 5
    # The newest is always one of them.
    assert status["shots"][-1]["points"]


def test_every_shot_keeps_where_it_landed():
    """Old shots lose their arc but stay as a dispersion pattern."""

    session = RangeSession()
    for _ in range(10):
        session.record(SEVEN_IRON, "7 iron")
    for shot in session.status(trace_limit=2)["shots"]:
        assert shot["carryYards"] > 0
        assert "offlineYards" in shot


def test_the_page_is_told_where_the_targets_are():
    status = RangeSession().status()
    assert status["targets"] and status["markers"]
    assert max(status["markers"]) >= max(status["targets"])


# --- Per-club grouping -----------------------------------------------------


def test_shots_group_by_club():
    session = RangeSession()
    session.record(SEVEN_IRON, "7 iron")
    session.record(SEVEN_IRON, "7 iron")
    session.record({"speed": 167, "launch": 10.9, "direction": 0,
                    "backSpin": 2686, "sideSpin": 0}, "Driver")

    rows = {row["club"]: row for row in session.by_club()}
    assert rows["7 iron"]["shots"] == 2
    assert rows["Driver"]["shots"] == 1
    assert rows["Driver"]["carryAvg"] > rows["7 iron"]["carryAvg"]


def test_the_longest_club_is_listed_first():
    session = RangeSession()
    session.record(SEVEN_IRON, "7 iron")
    session.record({"speed": 167, "launch": 10.9, "direction": 0,
                    "backSpin": 2686, "sideSpin": 0}, "Driver")
    assert session.by_club()[0]["club"] == "Driver"


def test_dispersion_reflects_how_scattered_the_shots_were():
    tight, loose = RangeSession(), RangeSession()
    for offset in (0, 0, 0):
        tight.record(dict(SEVEN_IRON, sideSpin=offset), "7 iron")
    for offset in (-1500, 0, 1500):
        loose.record(dict(SEVEN_IRON, sideSpin=offset), "7 iron")
    assert loose.by_club()[0]["offlineSigma"] > tight.by_club()[0]["offlineSigma"]


def test_a_club_with_one_shot_has_no_spread():
    session = RangeSession()
    session.record(SEVEN_IRON, "7 iron")
    assert session.by_club()[0]["offlineSigma"] == 0.0


def test_shots_with_no_club_are_still_grouped():
    session = RangeSession()
    session.record(SEVEN_IRON, "")
    assert session.by_club()[0]["club"] == "Unknown"


# --- Conditions ------------------------------------------------------------


def test_conditions_change_how_far_the_ball_goes():
    sea, denver = RangeSession(), RangeSession()
    denver.set_conditions(pressure_pa=83000, temperature_c=25.0)
    assert (denver.record(SEVEN_IRON, "7 iron")["carryYards"]
            > sea.record(SEVEN_IRON, "7 iron")["carryYards"] + 5)


def test_absurd_conditions_are_clamped_rather_than_believed():
    session = RangeSession()
    session.set_conditions(pressure_pa=-1, temperature_c=9999, relative_humidity=44)
    assert 10000 <= session.conditions["pressurePa"] <= 110000
    assert -40 <= session.conditions["temperatureC"] <= 60
    assert 0 <= session.conditions["relativeHumidity"] <= 1
    assert session.density > 0


def test_conditions_start_at_a_standard_atmosphere():
    assert RangeSession().density == pytest.approx(flight.STANDARD_DENSITY, abs=0.002)


# --- T9: a real shot reaches the range -------------------------------------


def test_a_shot_through_the_relay_reaches_the_range(rig):
    """The whole point: hit a ball, see it on the range.

    Driven from the enclosure end, so this exercises the same path a real shot
    takes rather than calling the range directly.
    """

    rig.pair()
    assert rig.wait_linked() is True
    assert rig.companion.status()["setupComplete"] is False

    before = rig.companion.range.status()["count"]
    # The path a measured shot actually takes: the enclosure forwards it and
    # the companion relays it on. send_test_shot bypasses this deliberately,
    # so a diagnostic never lands in the history.
    rig.companion._forward_shot(1, "gspro", {
        "BallData": {"Speed": 120.0, "VLA": 16.3, "HLA": 1.2,
                     "BackSpin": 7097, "SideSpin": 300},
    })

    after = rig.companion.range.status()
    assert after["count"] == before + 1
    landed = after["shots"][-1]
    assert landed["carryYards"] > 0
    assert landed["points"], "the newest shot must carry its trajectory"


def test_the_range_survives_a_shot_it_cannot_fly(rig):
    """A launch monitor does produce nonsense, and it must not break delivery."""

    rig.pair()
    assert rig.wait_linked() is True
    rig.companion._forward_shot(1, "gspro", {
        "BallData": {"Speed": 0, "VLA": 0, "HLA": 0, "BackSpin": 0, "SideSpin": 0},
    })
    assert rig.companion.range.status()["count"] == 0


def test_a_broken_range_never_costs_a_delivered_shot(rig, monkeypatch):
    """Delivery is the product. Drawing is a nicety and must not outrank it."""

    rig.pair()
    assert rig.wait_linked() is True

    def explode(*_args, **_kwargs):
        raise RuntimeError("the range is on fire")

    monkeypatch.setattr(rig.companion.range, "record", explode)
    result = rig.companion._forward_shot(1, "gspro", {
        "BallData": {"Speed": 120.0, "VLA": 16.3, "HLA": 0.0,
                     "BackSpin": 7097, "SideSpin": 0},
    })
    assert result.get("accepted") is True, "delivery must survive a broken range"
    assert rig.companion.shots.recent(1), "and the shot must still be logged"


def test_the_renderer_maps_the_physics_axes_onto_the_scene():
    """The model flies down +x; the scene is built down +z.

    Getting this wrong draws every shot sideways across the range, and it looks
    plausible enough in a still that it survived until somebody looked at it.
    """

    import pathlib

    page = (
        pathlib.Path(__file__).resolve().parent.parent
        / "src" / "pitrac_easy_connect" / "companion" / "page.py"
    ).read_text()
    tracer = page.split("// Tracers, oldest faintest.")[1].split("function upload(")[0]
    assert "pts[i-1][2],pts[i-1][1],pts[i-1][0]" in tracer, "downrange must map to scene z"
    assert "pos.push(end[2], 0.05, end[0])" in tracer, "and so must the landing mark"


def test_the_opening_camera_is_one_a_button_can_reproduce():
    """The range used to open on a camera no view button could restore, because
    the declaration and setView held separate copies of the numbers."""

    import pathlib

    page = (
        pathlib.Path(__file__).resolve().parent.parent
        / "src" / "pitrac_easy_connect" / "companion" / "page.py"
    ).read_text()
    assert "orbit=Object.assign({}, VIEWS.behind)" in page
    setview = page.split("function setView(")[1].split("\n  }")[0]
    assert "VIEWS[name]" in setview
    assert "yaw:0.62" not in setview, "the numbers belong in VIEWS, once"


# --- The stand-in launch monitor -------------------------------------------


def test_the_ball_machine_produces_shots_the_relay_understands():
    """It stands in for the hardware, so it must speak the hardware's protocol."""

    from pitrac_easy_connect import ballmachine
    from pitrac_easy_connect.models import Simulator
    from pitrac_easy_connect.pi.relay import is_shot_message

    shot = ballmachine.one_shot("7 iron")
    assert is_shot_message(Simulator.GSPRO, shot["payload"])
    ball = shot["payload"]["BallData"]
    for field in ("Speed", "VLA", "HLA", "BackSpin", "SideSpin"):
        assert field in ball


def test_every_ball_machine_club_actually_flies():
    """A club whose numbers the model rejects would be a silent hole in testing."""

    from pitrac_easy_connect import ballmachine

    for name, _s, _l, _sp, _sd, _d in ballmachine.CLUBS:
        for _attempt in range(20):
            shot = ballmachine.one_shot(name)["payload"]["BallData"]
            result = flight.simulate(shot["Speed"], shot["VLA"], shot["HLA"],
                                     shot["BackSpin"], shot["SideSpin"])
            assert result["carryYards"] > 0, "{} produced an unflyable shot".format(name)


def test_the_clubs_come_out_in_a_sensible_order():
    """If a wedge out-carried a driver the test data would be misleading."""

    from pitrac_easy_connect import ballmachine

    carries = {}
    for name, _s, _l, _sp, _sd, _d in ballmachine.CLUBS:
        runs = []
        for _attempt in range(40):
            b = ballmachine.one_shot(name)["payload"]["BallData"]
            runs.append(flight.simulate(b["Speed"], b["VLA"], b["HLA"],
                                        b["BackSpin"], b["SideSpin"])["carryYards"])
        carries[name] = sum(runs) / len(runs)
    ordered = [carries[c[0]] for c in ballmachine.CLUBS]
    assert ordered == sorted(ordered, reverse=True), carries

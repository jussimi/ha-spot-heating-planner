"""How the room warms and cools."""

import math

import pytest

from custom_components.spot_heating_planner.core import thermal

from .example import HEATED_ROOM


def test_reproduces_the_example_cooling() -> None:
    # The example space: 15 -> 13 deg C in 5 h at 5 deg C outside
    assert thermal.temperature_after(15, 5, 5, HEATED_ROOM) == pytest.approx(
        13, abs=0.01
    )


def test_example_heating_hour_matches_the_docs() -> None:
    # One hour of heating at -5 deg C outside, from 5 deg C
    after = thermal.temperature_after(5, -5, 1, HEATED_ROOM, heating_minutes=60)
    assert after == pytest.approx(6.3, abs=0.05)


def test_heating_settles_at_outdoor_plus_max_rise() -> None:
    after = thermal.temperature_after(10, -5, 300, HEATED_ROOM, heating_minutes=18000)
    assert after == pytest.approx(-5 + HEATED_ROOM.max_rise, abs=0.1)


def test_derived_quantities() -> None:
    assert HEATED_ROOM.cooling_rate == pytest.approx(0.0446)
    assert HEATED_ROOM.max_rise == pytest.approx(40)
    assert HEATED_ROOM.half_life_hours == pytest.approx(math.log(2) / 0.0446)


def test_coasting_hours_match_the_closed_form() -> None:
    # From 15 deg C at -10 outside down to 3 deg C: ln(25/13) / k
    expected = math.log(25 / 13) / HEATED_ROOM.cooling_rate
    hours = thermal.coasting_hours(15, [-10] * 48, 3, HEATED_ROOM)
    assert hours == pytest.approx(expected, abs=0.3)


def test_no_end_to_coasting_when_outside_is_warmer_than_the_lower_limit() -> None:
    assert thermal.coasting_hours(15, [5] * 48, 3, HEATED_ROOM) is None

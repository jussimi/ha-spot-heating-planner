"""Dew point, relative humidity and the sliding limits."""

import pytest

from custom_components.spot_heating_planner.core import humidity

from .example import CFG


def test_dew_point_matches_known_values() -> None:
    assert humidity.dew_point(18, 80) == pytest.approx(14.5, abs=0.05)
    assert humidity.dew_point(-5, 90) == pytest.approx(-6.4, abs=0.05)


def test_relative_humidity_is_the_inverse_of_dew_point() -> None:
    dew_point = humidity.dew_point(10, 70)
    assert humidity.relative_humidity(10, dew_point) == pytest.approx(70)


def test_limits_slide_with_temperature() -> None:
    assert humidity.limits(20, CFG.humidity) == (65, 75)
    assert humidity.limits(15, CFG.humidity) == (65, 75)
    assert humidity.limits(10, CFG.humidity) == (70, 80)
    assert humidity.limits(0, CFG.humidity) == (80, 90)  # capped


def test_warm_enough_meets_the_limits() -> None:
    dew_point = humidity.dew_point(5, 85)
    warm = humidity.warm_enough(dew_point, CFG.humidity)
    target, _ = humidity.limits(warm.target, CFG.humidity)
    _, critical = humidity.limits(warm.critical, CFG.humidity)
    rh_at_target = humidity.relative_humidity(warm.target, dew_point)
    rh_at_critical = humidity.relative_humidity(warm.critical, dew_point)
    assert rh_at_target == pytest.approx(target, abs=0.1)
    assert rh_at_critical == pytest.approx(critical, abs=0.1)


def test_target_needs_more_warmth_than_critical() -> None:
    warm = humidity.warm_enough(humidity.dew_point(5, 85), CFG.humidity)
    assert warm.critical < warm.target
    assert warm.target > 5

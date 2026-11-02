"""Sanity checks on sensor readings."""

from dataclasses import replace
from datetime import timedelta

from custom_components.spot_heating_planner.core.learning import StepSample
from custom_components.spot_heating_planner.core.sensors import (
    plausible_humidity,
    plausible_temperature,
    stuck_while_heating,
)

from .example import CFG, NOW


def step(i: int, t_start: float, t_end: float, share: float) -> StepSample:
    return StepSample(
        start=NOW + i * timedelta(minutes=15),
        minutes=15,
        indoor_temperature_start=t_start,
        indoor_temperature_end=t_end,
        outdoor_temperature=-5,
        heat_share=share,
    )


def test_impossible_temperatures_are_dropped() -> None:
    assert plausible_temperature(4.2, CFG.sensors) == 4.2
    assert plausible_temperature(-80.0, CFG.sensors) is None
    assert plausible_temperature(None, CFG.sensors) is None


def test_impossible_humidity_is_dropped() -> None:
    assert plausible_humidity(70.0) == 70.0
    assert plausible_humidity(0.0) is None
    assert plausible_humidity(120.0) is None


def test_unchanged_through_an_hour_of_heating_is_stuck() -> None:
    steps = [step(i, 5.0, 5.0, 1.0) for i in range(4)]
    assert stuck_while_heating(steps, CFG.sensors)


def test_unchanged_while_coasting_is_not_stuck() -> None:
    # A cold space can sit at the same reading for hours without heating
    steps = [step(i, 5.0, 5.0, 0.0) for i in range(12)]
    assert not stuck_while_heating(steps, CFG.sensors)


def test_a_moving_reading_is_not_stuck() -> None:
    steps = [step(i, 5.0 + 0.3 * i, 5.3 + 0.3 * i, 1.0) for i in range(4)]
    assert not stuck_while_heating(steps, CFG.sensors)


def test_only_the_latest_stretch_counts() -> None:
    # Moved an hour ago, then stopped moving through another hour of heating
    earlier = [step(i, 4.0 + 0.3 * i, 4.3 + 0.3 * i, 1.0) for i in range(4)]
    later = [step(4 + i, 5.0, 5.0, 1.0) for i in range(4)]
    assert stuck_while_heating(earlier + later, CFG.sensors)
    assert not stuck_while_heating(earlier + later[:2], CFG.sensors)


def test_the_threshold_is_a_setting() -> None:
    steps = [step(i, 5.0, 5.0, 1.0) for i in range(2)]  # 30 min of heating
    assert not stuck_while_heating(steps, CFG.sensors)
    assert stuck_while_heating(steps, replace(CFG.sensors, stuck_heating_minutes=30))

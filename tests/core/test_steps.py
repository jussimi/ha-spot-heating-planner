"""Collecting one learning step."""

from datetime import timedelta

import pytest

from custom_components.spot_heating_planner.core.steps import OpenStep, is_boundary

from .example import NOW


def fifteen_minutes(
    *, heating_minutes: int, outdoor_temperature: float | None
) -> OpenStep:
    step = OpenStep(start=NOW, indoor_temperature_start=5.0, energy_start_kwh=100.0)
    for minute in range(15):
        step.add_minute(
            heating=minute < heating_minutes, outdoor_temperature=outdoor_temperature
        )
    return step


def test_a_full_step() -> None:
    step = fifteen_minutes(heating_minutes=5, outdoor_temperature=-10.0)
    sample = step.close(
        NOW + timedelta(minutes=15), indoor_temperature_end=5.4, energy_end_kwh=100.08
    )
    assert sample is not None
    assert sample.minutes == 15
    assert sample.heat_share == pytest.approx(1 / 3)
    assert sample.outdoor_temperature == -10.0
    assert sample.energy_kwh == pytest.approx(0.08)


def test_no_step_without_the_outdoor_sensor() -> None:
    step = fifteen_minutes(heating_minutes=5, outdoor_temperature=None)
    end = NOW + timedelta(minutes=15)
    assert step.close(end, indoor_temperature_end=5.4, energy_end_kwh=None) is None


def test_no_step_without_the_indoor_temperature_at_the_end() -> None:
    step = fifteen_minutes(heating_minutes=0, outdoor_temperature=-10.0)
    end = NOW + timedelta(minutes=15)
    assert step.close(end, indoor_temperature_end=None, energy_end_kwh=None) is None


def test_a_counter_reset_means_no_energy_reading() -> None:
    step = fifteen_minutes(heating_minutes=15, outdoor_temperature=-10.0)
    sample = step.close(
        NOW + timedelta(minutes=15), indoor_temperature_end=5.6, energy_end_kwh=0.2
    )
    assert sample is not None
    assert sample.energy_kwh is None


def test_boundaries_every_step() -> None:
    assert is_boundary(NOW, 15)
    assert is_boundary(NOW + timedelta(minutes=45), 15)
    assert not is_boundary(NOW + timedelta(minutes=10), 15)

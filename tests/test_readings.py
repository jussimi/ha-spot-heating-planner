"""Reading sensor states."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from custom_components.spot_heating_planner import readings


def test_celsius_passes_through() -> None:
    state = State("sensor.t", "4.2", {"unit_of_measurement": "°C"})
    assert readings.temperature(state) == 4.2


def test_fahrenheit_is_converted() -> None:
    state = State("sensor.t", "41", {"unit_of_measurement": "°F"})
    assert readings.temperature(state) == pytest.approx(5.0)


def test_unavailable_and_junk_are_missing() -> None:
    assert readings.temperature(State("sensor.t", "unavailable")) is None
    assert readings.temperature(State("sensor.t", "warm")) is None
    assert readings.temperature(None) is None


def test_a_unit_that_isnt_a_temperature_is_missing() -> None:
    state = State("sensor.t", "4.2", {"unit_of_measurement": "kWh"})
    assert readings.temperature(state) is None


def test_energy_in_wh_is_converted() -> None:
    state = State("sensor.e", "1500", {"unit_of_measurement": "Wh"})
    assert readings.energy(state) == pytest.approx(1.5)


async def test_total_energy_needs_every_meter(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.a", "1.0", {"unit_of_measurement": "kWh"})
    hass.states.async_set("sensor.b", "2.5", {"unit_of_measurement": "kWh"})
    assert readings.total_energy(hass, ["sensor.a", "sensor.b"]) == 3.5
    hass.states.async_set("sensor.b", "unavailable")
    assert readings.total_energy(hass, ["sensor.a", "sensor.b"]) is None


def test_median_ignores_a_single_odd_reading() -> None:
    now = dt_util.utcnow()
    smoothed = readings.Smoothed()
    for minute, value in enumerate([5.0, 5.1, 25.0, 5.0, 5.1]):
        smoothed.add(now + timedelta(minutes=minute), value)
    assert smoothed.value(now + timedelta(minutes=4)) == 5.1


def test_median_forgets_old_readings() -> None:
    now = dt_util.utcnow()
    smoothed = readings.Smoothed()
    smoothed.add(now, 5.0)
    assert smoothed.value(now + timedelta(minutes=29)) == 5.0
    assert smoothed.value(now + timedelta(minutes=31)) is None


def test_missing_readings_are_skipped() -> None:
    now = dt_util.utcnow()
    smoothed = readings.Smoothed()
    smoothed.add(now, None)
    assert smoothed.value(now) is None

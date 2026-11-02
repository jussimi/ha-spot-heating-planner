"""The hourly weather forecast."""

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.spot_heating_planner.core import humidity
from custom_components.spot_heating_planner.sources.forecast import fetch_forecast

WEATHER = "weather.home"


def register_weather(hass: HomeAssistant, entries: list[dict[str, Any]]) -> None:
    """A fake weather.get_forecasts returning these hourly entries."""

    async def handle(call: ServiceCall) -> dict[str, Any]:
        del call
        return {WEATHER: {"forecast": entries}}

    hass.services.async_register(
        "weather", "get_forecasts", handle, supports_response=SupportsResponse.ONLY
    )


def hour(offset: int) -> str:
    return (dt_util.utcnow() + timedelta(hours=offset)).isoformat()


async def test_reads_temperature_and_dew_point(hass: HomeAssistant) -> None:
    register_weather(
        hass, [{"datetime": hour(1), "temperature": -5.0, "dew_point": -8.0}]
    )
    [point] = await fetch_forecast(hass, WEATHER)
    assert point.temperature == -5.0
    assert point.dew_point == -8.0


async def test_dew_point_from_humidity_when_missing(hass: HomeAssistant) -> None:
    register_weather(hass, [{"datetime": hour(1), "temperature": -5.0, "humidity": 90}])
    [point] = await fetch_forecast(hass, WEATHER)
    assert point.dew_point == pytest.approx(humidity.dew_point(-5.0, 90))


async def test_fahrenheit_is_converted(hass: HomeAssistant) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    register_weather(hass, [{"datetime": hour(1), "temperature": 23.0}])
    [point] = await fetch_forecast(hass, WEATHER)
    assert point.temperature == pytest.approx(-5.0)


async def test_entries_without_a_temperature_are_skipped(hass: HomeAssistant) -> None:
    register_weather(
        hass, [{"datetime": hour(1)}, {"datetime": hour(2), "temperature": -3.0}]
    )
    points = await fetch_forecast(hass, WEATHER)
    assert [p.temperature for p in points] == [-3.0]


async def test_no_weather_entity_means_no_forecast(hass: HomeAssistant) -> None:
    assert await fetch_forecast(hass, WEATHER) == []

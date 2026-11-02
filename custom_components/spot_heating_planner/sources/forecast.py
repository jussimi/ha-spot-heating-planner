"""The hourly weather forecast, from any weather entity.

`weather.get_forecasts` returns temperatures in Home Assistant's unit
system; they are converted to deg C. The dew point is taken from the
forecast if it has one, else worked out from its humidity.
"""

from typing import TYPE_CHECKING, Any

from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from ..const import HORIZON
from ..core import humidity
from ..core.planner import ForecastPoint

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

WEATHER_DOMAIN = "weather"
GET_FORECASTS = "get_forecasts"
HOURLY = "hourly"


async def fetch_forecast(
    hass: HomeAssistant, weather_entity: str
) -> list[ForecastPoint]:
    """Hourly forecast points up to HORIZON; [] if there's no forecast."""
    try:
        response = await hass.services.async_call(
            WEATHER_DOMAIN,
            GET_FORECASTS,
            {"type": HOURLY},
            target={"entity_id": weather_entity},
            blocking=True,
            return_response=True,
        )
    except HomeAssistantError:
        return []
    entries = _entries(response, weather_entity)
    unit = hass.config.units.temperature_unit
    horizon = dt_util.utcnow() + HORIZON
    points = [_parse(entry, unit) for entry in entries]
    return [p for p in points if p is not None and p.time < horizon]


def _entries(response: Any, weather_entity: str) -> list[Any]:  # noqa: ANN401 - JSON
    """The list of forecast entries in the response, or [] if it's malformed."""
    if not isinstance(response, dict):
        return []
    forecast = response.get(weather_entity, {})
    entries = forecast.get("forecast") if isinstance(forecast, dict) else None
    return entries if isinstance(entries, list) else []


def _parse(entry: Any, unit: str) -> ForecastPoint | None:  # noqa: ANN401 - JSON
    """One forecast hour in deg C; None if it has no time or temperature."""
    if not isinstance(entry, dict):
        return None
    time = dt_util.parse_datetime(str(entry.get("datetime", "")))
    temperature = _celsius(entry.get("temperature"), unit)
    if time is None or temperature is None:
        return None
    dew_point = _celsius(entry.get("dew_point"), unit)
    relative_humidity = _number(entry.get("humidity"))
    if dew_point is None and relative_humidity is not None and relative_humidity > 0:
        dew_point = humidity.dew_point(temperature, relative_humidity)
    return ForecastPoint(dt_util.as_utc(time), temperature, dew_point)


def _number(value: Any) -> float | None:  # noqa: ANN401 - JSON
    return float(value) if isinstance(value, int | float) else None


def _celsius(value: Any, unit: str) -> float | None:  # noqa: ANN401 - JSON
    number = _number(value)
    if number is None:
        return None
    return TemperatureConverter.convert(number, unit, UnitOfTemperature.CELSIUS)

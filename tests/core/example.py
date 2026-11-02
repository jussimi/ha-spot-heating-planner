"""The example space used across the tests and in docs/physics.md.

A 20 m2 insulated storage building. Made-up but realistic numbers: the room
loses 25 W per deg C above outside (UA) and stores 0.56 kWh per deg C (C).

With its 1 kW heater that means:
- coasting from 15 to 13 deg C takes 5 hours at 5 deg C outside
  (it cools at k = UA / C = 0.0446 /h);
- a full hour of heating at -5 deg C outside lifts it from 5 to about
  6.3 deg C, and heating for ever would hold it G = P / UA = 40 deg C above
  outside.
"""

from datetime import UTC, datetime, timedelta

from custom_components.spot_heating_planner.core.config import Config
from custom_components.spot_heating_planner.core.planner import ForecastPoint, Inputs
from custom_components.spot_heating_planner.core.thermal import HeatedRoom, Room

CFG = Config()
ROOM = Room(heat_loss_kw=0.025, heat_capacity_kwh=0.025 / 0.0446)
HEATED_ROOM = HeatedRoom(room=ROOM, heater_power_kw=1.0)
NOW = datetime(2026, 1, 15, 14, 0, tzinfo=UTC)
CHEAP, NORMAL, PEAK = 3.0, 8.0, 50.0


def prices(
    pattern: tuple[float, ...], start: datetime = NOW
) -> list[tuple[datetime, float]]:
    """Hourly prices from `start`."""
    return [(start + timedelta(hours=h), p) for h, p in enumerate(pattern)]


def forecast(
    temp: float, hours: int = 48, start: datetime = NOW, dew: float | None = None
) -> list[ForecastPoint]:
    """A flat hourly forecast from `start`."""
    return [ForecastPoint(start + timedelta(hours=h), temp, dew) for h in range(hours)]


def inputs(  # noqa: PLR0913 - a test helper with defaults for every input
    *,
    indoor_temperature: float = 10.0,
    indoor_humidity: float | None = None,
    outdoor_temperature: float | None = -10.0,
    outdoor_dew_point: float | None = None,
    price_pattern: tuple[float, ...] = (NORMAL,) * 24,
    override_until: datetime | None = None,
    now: datetime = NOW,
) -> Inputs:
    """Inputs with a flat forecast at the outdoor temperature."""
    start = now.replace(minute=0)
    return Inputs(
        now=now,
        indoor_temperature=indoor_temperature,
        indoor_humidity=indoor_humidity,
        outdoor_temperature=outdoor_temperature,
        outdoor_dew_point=outdoor_dew_point,
        prices=prices(price_pattern, start),
        forecast=forecast(
            -10.0 if outdoor_temperature is None else outdoor_temperature, start=start
        ),
        override_until=override_until,
    )

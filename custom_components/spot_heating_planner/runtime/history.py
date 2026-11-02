"""Past hours, read from Home Assistant's long-term statistics.

Sensors with a state class keep an hourly mean (measurements) or hourly
change (totals) for good, so the comparison can reach back as far as those
sensors have existed, even before this integration was installed.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.helpers.recorder import get_instance

from ..core.comparison import HourHistory

if TYPE_CHECKING:
    from homeassistant.components.recorder.statistics import StatisticsRow
    from homeassistant.core import HomeAssistant

HOUR = timedelta(hours=1)
UNITS = {"temperature": "°C", "energy": "kWh"}
"""Ask for every value in the units the core works in."""

type Kind = Literal["mean", "change"]


@dataclass(frozen=True, kw_only=True)
class Sources:
    """Which statistics hold what."""

    outdoor_temperature: str | None
    price: str | None
    energy_meters: list[str]
    indoor_temperature: str | None


async def read(
    hass: HomeAssistant, sources: Sources, *, start: datetime, end: datetime
) -> list[HourHistory]:
    """Every hour from `start` to `end`, with what the statistics hold for it."""
    means = {
        s
        for s in (
            sources.outdoor_temperature,
            sources.price,
            sources.indoor_temperature,
        )
        if s
    }
    changes = set(sources.energy_meters)
    mean_rows = await _rows(hass, means, "mean", start=start, end=end)
    change_rows = await _rows(hass, changes, "change", start=start, end=end)

    def value(statistic: str | None, at: datetime) -> float | None:
        return None if statistic is None else mean_rows.get(statistic, {}).get(at)

    hours = []
    at = start
    while at < end:
        hours.append(
            HourHistory(
                start=at,
                outdoor_temperature=value(sources.outdoor_temperature, at),
                price=value(sources.price, at),
                energy_kwh=_energy(sources.energy_meters, change_rows, at),
                indoor_temperature=value(sources.indoor_temperature, at),
            )
        )
        at += HOUR
    return hours


def _energy(
    meters: list[str], rows: dict[str, dict[datetime, float]], at: datetime
) -> float | None:
    """All meters' kWh in the hour; None if any of them has no reading."""
    readings = [rows.get(meter, {}).get(at) for meter in meters]
    if not readings or any(r is None for r in readings):
        return None
    return sum(r for r in readings if r is not None)


async def _rows(
    hass: HomeAssistant, ids: set[str], kind: Kind, *, start: datetime, end: datetime
) -> dict[str, dict[datetime, float]]:
    """Statistic id -> hour start -> value, for one kind of value."""
    if not ids:
        return {}

    def query() -> dict[str, list[StatisticsRow]]:
        return statistics_during_period(hass, start, end, ids, "hour", UNITS, {kind})

    raw = await get_instance(hass).async_add_executor_job(query)
    return {
        statistic: {
            datetime.fromtimestamp(row["start"], UTC): value
            for row in rows
            if (value := row.get(kind)) is not None
        }
        for statistic, rows in raw.items()
    }

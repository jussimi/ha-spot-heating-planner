"""Past hours, read from Home Assistant's long-term statistics.

Sensors with a state class keep an hourly mean (measurements) or hourly
change (totals) for good. The comparison reads every input from there, each
as it was in that hour: the outdoor temperature, the energy price and the
room this integration had learned at the time.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.helpers.recorder import get_instance

from ..core.comparison import HourHistory
from ..core.thermal import WATTS_PER_KW

if TYPE_CHECKING:
    from homeassistant.components.recorder.statistics import StatisticsRow
    from homeassistant.core import HomeAssistant

HOUR = timedelta(hours=1)
UNITS = {"temperature": "°C", "energy": "kWh", "power": "kW"}
"""Ask for every value in the units the core works in."""

type Kind = Literal["mean", "change"]


@dataclass(frozen=True, kw_only=True)
class Sources:
    """Which statistics hold what."""

    outdoor_temperature: str | None
    energy_price: str | None
    heat_loss: str | None
    """The space's heat loss sensor, W per deg C."""

    heater_power: str | None
    energy_meters: list[str]
    indoor_temperature: str | None


async def read(
    hass: HomeAssistant, sources: Sources, *, start: datetime, end: datetime
) -> list[HourHistory]:
    """Every hour from `start` up to `end`, with what the statistics hold."""
    means = {
        s
        for s in (
            sources.outdoor_temperature,
            sources.energy_price,
            sources.heat_loss,
            sources.heater_power,
            sources.indoor_temperature,
        )
        if s
    }
    changes = set(sources.energy_meters)
    mean_rows = await _rows(hass, means, "mean", start=start, end=end)
    change_rows = await _rows(hass, changes, "change", start=start, end=end)

    def mean(statistic: str | None, at: datetime) -> float | None:
        return None if statistic is None else mean_rows.get(statistic, {}).get(at)

    hours = []
    at = start
    while at < end:
        heat_loss_w = mean(sources.heat_loss, at)
        hours.append(
            HourHistory(
                start=at,
                outdoor_temperature=mean(sources.outdoor_temperature, at),
                energy_price=mean(sources.energy_price, at),
                heat_loss_kw=None
                if heat_loss_w is None
                else heat_loss_w / WATTS_PER_KW,
                heater_power_kw=mean(sources.heater_power, at),
                energy_kwh=_energy(sources.energy_meters, change_rows, at),
                indoor_temperature=mean(sources.indoor_temperature, at),
            )
        )
        at += HOUR
    return hours


async def read_in_chunks(
    hass: HomeAssistant,
    sources: Sources,
    *,
    start: datetime,
    end: datetime,
    chunk: timedelta,
) -> list[HourHistory]:
    """The same as `read`, querying the statistics a chunk at a time."""
    hours: list[HourHistory] = []
    while start < end:
        chunk_end = min(start + chunk, end)
        hours += await read(hass, sources, start=start, end=chunk_end)
        start = chunk_end
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

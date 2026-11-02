"""Keeping the comparison series up to date from Home Assistant's statistics.

For each comparison temperature: what a plain thermostat would have used and
cost, hour by hour. Plus the metered cost: the heaters' own meters priced the
same way, the real curve to set them against.

Every input of an hour is fixed in history, so a written hour never needs
rewriting. Each run only appends the hours after the last one written,
continuing the running totals. Only a change of the temperatures means starting over
from the first recorded hour, and even then the hours of temperatures that
stay come out the same.
"""

from typing import TYPE_CHECKING

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..core import comparison
from . import history, statistics
from .history import HOUR

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ..core.comparison import HourHistory, HourResult
    from .space import Space, SpaceEntities
    from .storage import Memory


def own_sensor(hass: HomeAssistant, entry: ConfigEntry, key: str) -> str | None:
    """The entity id of one of the space's own sensors, by its key."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")


def sources(
    hass: HomeAssistant, entry: ConfigEntry, entities: SpaceEntities
) -> history.Sources:
    """Where each kind of history lives for this space."""
    return history.Sources(
        outdoor_temperature=entities.outdoor_temperature,
        energy_price=own_sensor(hass, entry, "energy_price"),
        heat_loss=own_sensor(hass, entry, "heat_loss"),
        heater_power=own_sensor(hass, entry, "heater_power"),
        energy_meters=entities.energy_sensors,
        indoor_temperature=entities.indoor_temperature,
    )


async def update(space: Space) -> None:
    """Append the hours since the last run; start over if the list changed."""
    hass, entry, memory = space.hass, space.entry, space.memory
    if statistics.RECORDER not in hass.config.components:
        return
    temperatures = list(space.cfg.comparison.temperatures)
    if memory.comparison_temperatures != temperatures:
        memory.comparison_through = None
        memory.comparison_totals = {}
        memory.comparison_temperatures = temperatures

    end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    hours = await history.read(
        hass,
        sources(hass, entry, space.entities),
        start=memory.comparison_through,
        end=end,
    )
    series_values = [(statistics.metered_cost(space.currency), costs(metered(hours)))]
    for temperature in temperatures:
        results = thermostat_results(hours, temperature)
        series_values += [
            (statistics.thermostat_cost(temperature, space.currency), costs(results)),
            (statistics.thermostat_energy(temperature), energies(results)),
        ]
    for series, values in series_values:
        _append(space, memory, series, values)
    # Up to the last hour actually written: hours whose statistics weren't
    # compiled yet are picked up by the next run, not skipped
    written = [start for _, values in series_values for start, _ in values]
    if written:
        memory.comparison_through = max(written) + HOUR
    space.save_soon()


def metered(hours: list[HourHistory]) -> list[HourResult | None]:
    """The metered cost, hour by hour; None where data is missing."""
    return [comparison.metered_hour(h) for h in hours]


def thermostat_results(
    hours: list[HourHistory], temperature: float
) -> list[HourResult | None]:
    """The comparison thermostat, hour by hour; None where data is missing."""
    return [comparison.thermostat_hour(h, temperature) for h in hours]


def costs(results: list[HourResult | None]) -> list[tuple[datetime, float]]:
    """(hour, cost) of the hours that could be counted."""
    return [(r.start, r.cost) for r in results if r is not None]


def energies(results: list[HourResult | None]) -> list[tuple[datetime, float]]:
    """(hour, kWh) of the hours that could be counted."""
    return [(r.start, r.energy_kwh) for r in results if r is not None]


def _append(
    space: Space,
    memory: Memory,
    series: statistics.Series,
    values: list[tuple[datetime, float]],
) -> None:
    """Write the hours, continuing the series' running total."""
    start_total = memory.comparison_totals.get(series.key, 0.0)
    hours = statistics.running_totals(values, start_total=start_total)
    statistics.write_hours(space.hass, space.entry, series, hours)
    if hours:
        memory.comparison_totals[series.key] = hours[-1].total

"""Rebuilding the comparison series from Home Assistant's statistics.

For each comparison temperature: what a plain thermostat would have used and
cost, hour by hour, as far back as the outdoor temperature and price
history go. Plus the metered cost: the heaters' own meters priced the same
way, so the real curve reaches back before this integration too.

The whole history is rewritten each time, so the series always follow the
latest learned room and the current list of temperatures.
"""

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..core import comparison
from . import history, statistics

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ..core.comparison import HourHistory, HourResult
    from ..core.thermal import HeatedRoom
    from .space import Space, SpaceEntities

HISTORY = timedelta(days=400)
"""How far back the series reach: a year, plus a month to compare it with."""


def price_statistic(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """The space's own spot price sensor, whose statistics hold the prices."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_spot_price"
    )


def sources(
    hass: HomeAssistant, entry: ConfigEntry, entities: SpaceEntities
) -> history.Sources:
    """Where each kind of history lives for this space."""
    return history.Sources(
        outdoor_temperature=entities.outdoor_temperature,
        price=price_statistic(hass, entry),
        energy_meters=entities.energy_sensors,
        indoor_temperature=entities.indoor_temperature,
    )


async def rebuild(space: Space) -> None:
    """Rewrite every comparison series, and the metered cost, from history."""
    hass, entry, cfg = space.hass, space.entry, space.cfg
    if statistics.RECORDER not in hass.config.components:
        return
    end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    hours = await history.read(
        hass, sources(hass, entry, space.entities), start=end - HISTORY, end=end
    )
    fixed = cfg.prices.fixed_energy_cost
    metered = [comparison.metered_hour(h, fixed) for h in hours]
    _write(hass, entry, metered, cost=statistics.metered_cost(space.currency))
    heated_room = space.heated_room
    if heated_room is None:
        return  # comparisons need the learned room
    for temperature in cfg.comparison.temperatures:
        results = thermostat_results(hours, heated_room, temperature, fixed)
        _write(
            hass,
            entry,
            results,
            cost=statistics.thermostat_cost(temperature, space.currency),
            energy=statistics.thermostat_energy(temperature),
        )


def thermostat_results(
    hours: list[HourHistory], heated_room: HeatedRoom, temperature: float, fixed: float
) -> list[HourResult | None]:
    """The comparison thermostat, hour by hour; None where data is missing."""
    return [
        comparison.thermostat_hour(h, heated_room, temperature, fixed) for h in hours
    ]


def _write(
    hass: HomeAssistant,
    entry: ConfigEntry,
    results: list[HourResult | None],
    *,
    cost: statistics.Series,
    energy: statistics.Series | None = None,
) -> None:
    """Write the counted hours as running totals; missing hours are left out."""
    counted = [r for r in results if r is not None]
    statistics.write_hours(
        hass,
        entry,
        cost,
        statistics.running_totals([(r.start, r.cost) for r in counted]),
    )
    if energy is not None:
        energy_hours = [(r.start, r.energy_kwh) for r in counted]
        statistics.write_hours(
            hass, entry, energy, statistics.running_totals(energy_hours)
        )

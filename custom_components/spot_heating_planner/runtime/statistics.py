"""Hourly series written into Home Assistant's long-term statistics.

External statistics (`<domain>:<id>`) show up in the Statistics graph card
like any sensor's history, and may be written for past hours too. Without
the recorder (it is on by default) nothing is written.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy, UnitOfTemperature

from ..const import DOMAIN

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

RECORDER = "recorder"


@dataclass(frozen=True, kw_only=True)
class Series:
    """One hourly series of a space."""

    key: str
    """Part of the statistic id, e.g. "day_ahead_energy"."""

    name: str
    """Shown after the space's name, e.g. "day-ahead energy"."""

    unit: str | None
    unit_class: str | None
    cumulative: bool
    """True: a running total (energy, cost). False: an hourly mean."""


DAY_AHEAD_ENERGY = Series(
    key="day_ahead_energy",
    name="day-ahead energy",
    unit=UnitOfEnergy.KILO_WATT_HOUR,
    unit_class="energy",
    cumulative=True,
)
DAY_AHEAD_TEMPERATURE = Series(
    key="day_ahead_temperature",
    name="day-ahead temperature",
    unit=UnitOfTemperature.CELSIUS,
    unit_class="temperature",
    cumulative=False,
)


def day_ahead_cost(currency: str) -> Series:
    """The day-ahead cost series, in the space's currency."""
    return Series(
        key="day_ahead_cost",
        name="day-ahead cost",
        unit=currency,
        unit_class=None,
        cumulative=True,
    )


def statistic_id(entry: ConfigEntry, series: Series) -> str:
    """E.g. spot_heating_planner:01jabc..._day_ahead_energy."""
    return f"{DOMAIN}:{entry.entry_id.lower()}_{series.key}"


@dataclass(frozen=True, kw_only=True)
class Hour:
    """One hour's value of a series."""

    start: datetime
    value: float
    """The hour's own amount, or its mean."""

    total: float = 0.0
    """For cumulative series: the running total up to the end of the hour."""


def write_hour(
    hass: HomeAssistant, entry: ConfigEntry, series: Series, hour: Hour
) -> None:
    """Write one hour of a series."""
    if RECORDER not in hass.config.components:
        return
    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE
        if series.cumulative
        else StatisticMeanType.ARITHMETIC,
        has_sum=series.cumulative,
        name=f"{entry.title} {series.name}",
        source=DOMAIN,
        statistic_id=statistic_id(entry, series),
        unit_class=series.unit_class,
        unit_of_measurement=series.unit,
    )
    if series.cumulative:
        row = StatisticData(start=hour.start, state=hour.value, sum=hour.total)
    else:
        value = hour.value
        row = StatisticData(start=hour.start, mean=value, min=value, max=value)
    async_add_external_statistics(hass, metadata, [row])

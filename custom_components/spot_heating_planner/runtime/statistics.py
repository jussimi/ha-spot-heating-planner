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


def thermostat_energy(temperature: float) -> Series:
    """A comparison thermostat's energy series."""
    return Series(
        key=f"thermostat_{_temperature_key(temperature)}_energy",
        name=f"thermostat {temperature:g} °C energy",
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        unit_class="energy",
        cumulative=True,
    )


def thermostat_cost(temperature: float, currency: str) -> Series:
    """A comparison thermostat's cost series."""
    return Series(
        key=f"thermostat_{_temperature_key(temperature)}_cost",
        name=f"thermostat {temperature:g} °C cost",
        unit=currency,
        unit_class=None,
        cumulative=True,
    )


def metered_cost(currency: str) -> Series:
    """What the heaters' meters measured, priced: the real curve, retroactively."""
    return Series(
        key="metered_cost",
        name="metered cost",
        unit=currency,
        unit_class=None,
        cumulative=True,
    )


def _temperature_key(temperature: float) -> str:
    """4.5 -> "4_5", -2 -> "minus_2": statistic ids allow no dots or signs."""
    return f"{temperature:g}".replace("-", "minus_").replace(".", "_")


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
    write_hours(hass, entry, series, [hour])


def write_hours(
    hass: HomeAssistant, entry: ConfigEntry, series: Series, hours: list[Hour]
) -> None:
    """Write hours of a series; hours already there are overwritten."""
    if RECORDER not in hass.config.components or not hours:
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
    async_add_external_statistics(
        hass, metadata, [_row(hour, cumulative=series.cumulative) for hour in hours]
    )


def _row(hour: Hour, *, cumulative: bool) -> StatisticData:
    if cumulative:
        return StatisticData(start=hour.start, state=hour.value, sum=hour.total)
    value = hour.value
    return StatisticData(start=hour.start, mean=value, min=value, max=value)


def running_totals(hours: list[tuple[datetime, float]]) -> list[Hour]:
    """Hours with their running total, for a cumulative series."""
    total = 0.0
    rows = []
    for start, value in hours:
        total += value
        rows.append(Hour(start=start, value=value, total=total))
    return rows

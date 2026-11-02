"""What a plain thermostat would have cost, hour by hour, for the same room.

A thermostat holding a constant temperature T_set stores no heat, so it only
replaces what leaks out (docs/physics.md#comparison-thermostat):

    E = min(P, UA * max(0, T_set - T_outdoor)) * 1 h

Every input is taken as it was in that hour: the room learned at the time
(UA and the heaters' power P), the outdoor temperature, and the energy price
(spot plus the fixed costs then in force). A later change, to the building
or to the tariff, shows up from then on instead of rewriting the past.

The series for different temperatures aren't multiples of one another: the
max() leaves mild hours out of the cooler thermostats only, and the cap
P bites on the warmer ones first.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

CENTS_PER_UNIT = 100.0


@dataclass(frozen=True, kw_only=True)
class HourHistory:
    """What Home Assistant's statistics hold for one past hour."""

    start: datetime

    outdoor_temperature: float | None
    """Hourly mean, deg C."""

    energy_price: float | None
    """What a kWh cost: spot plus fixed costs, c/kWh incl. VAT."""

    heat_loss_kw: float | None
    """UA as learned at the time, kW per deg C."""

    heater_power_kw: float | None
    """The heaters' power as known at the time."""

    energy_kwh: float | None
    """What the heaters' meters measured in the hour."""

    indoor_temperature: float | None = None
    """Hourly mean, deg C."""


@dataclass(frozen=True, kw_only=True)
class HourResult:
    """Energy and cost of one hour."""

    start: datetime
    energy_kwh: float
    cost: float
    """In currency units."""


def thermostat_hour(hour: HourHistory, set_temperature: float) -> HourResult | None:
    """The comparison thermostat's hour; None without every input."""
    if (
        hour.outdoor_temperature is None
        or hour.energy_price is None
        or hour.heat_loss_kw is None
        or hour.heater_power_kw is None
    ):
        return None
    shortfall = max(0.0, set_temperature - hour.outdoor_temperature)
    power = min(hour.heater_power_kw, hour.heat_loss_kw * shortfall)
    return _priced(hour.start, power, hour.energy_price)


def metered_hour(hour: HourHistory) -> HourResult | None:
    """What the measured energy cost; None without a reading or a price."""
    if hour.energy_kwh is None or hour.energy_price is None:
        return None
    return _priced(hour.start, hour.energy_kwh, hour.energy_price)


def _priced(start: datetime, energy_kwh: float, price: float) -> HourResult:
    return HourResult(
        start=start, energy_kwh=energy_kwh, cost=energy_kwh * price / CENTS_PER_UNIT
    )


@dataclass(frozen=True, kw_only=True)
class Totals:
    """Energy and cost summed over a period."""

    energy_kwh: float
    cost: float
    hours: int
    """Hours that had the data to count."""


def totals(results: list[HourResult | None]) -> Totals:
    """Sum the hours that could be counted."""
    counted = [r for r in results if r is not None]
    return Totals(
        energy_kwh=sum(r.energy_kwh for r in counted),
        cost=sum(r.cost for r in counted),
        hours=len(counted),
    )


def mean_indoor_temperature(history: list[HourHistory]) -> float | None:
    """The average indoor temperature actually kept; None without readings."""
    readings = [
        h.indoor_temperature for h in history if h.indoor_temperature is not None
    ]
    return sum(readings) / len(readings) if readings else None

"""What a plain thermostat would have cost, hour by hour, for the same room.

A thermostat holding a constant temperature T_set stores no heat, so it only
replaces what leaks out (docs/physics.md#comparison-thermostat):

    P = UA * (T_set - T_outdoor),   capped at the heaters' power

Priced at each hour's spot price plus the fixed costs, that is the
comparison. The room (UA) is the latest learned one; a building's heat loss
hardly changes, and every past hour gains as learning improves.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from .thermal import HeatedRoom

CENTS_PER_UNIT = 100.0


@dataclass(frozen=True, kw_only=True)
class HourHistory:
    """What Home Assistant's statistics hold for one past hour."""

    start: datetime
    outdoor_temperature: float | None
    """Hourly mean, deg C."""

    price: float | None
    """Hourly mean spot price, c/kWh incl. VAT."""

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
    """In currency units, incl. fixed costs."""


def thermostat_hour(
    hour: HourHistory, heated_room: HeatedRoom, set_temperature: float, fixed: float
) -> HourResult | None:
    """The comparison thermostat's hour; None without outdoor or price data."""
    if hour.outdoor_temperature is None or hour.price is None:
        return None
    shortfall = max(0.0, set_temperature - hour.outdoor_temperature)
    power = min(heated_room.heater_power_kw, heated_room.room.heat_loss_kw * shortfall)
    return _priced(hour, power, fixed)


def metered_hour(hour: HourHistory, fixed: float) -> HourResult | None:
    """What the measured energy cost; None without a meter reading or price."""
    if hour.energy_kwh is None or hour.price is None:
        return None
    return _priced(hour, hour.energy_kwh, fixed)


def _priced(hour: HourHistory, energy_kwh: float, fixed: float) -> HourResult:
    price = hour.price or 0.0
    return HourResult(
        start=hour.start,
        energy_kwh=energy_kwh,
        cost=energy_kwh * (price + fixed) / CENTS_PER_UNIT,
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

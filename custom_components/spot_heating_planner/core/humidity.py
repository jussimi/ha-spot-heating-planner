"""Humidity: dew point, relative humidity and the sliding limits.

All temperatures are deg C, humidities %. The formulas are derived in
docs/physics.md#humidity.
"""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import Humidity

PERCENT = 100.0

# Magnus coefficients over water (Sonntag 1990), good from -45 to +60 deg C
MAGNUS_A = 17.62
MAGNUS_B = 243.12  # deg C

# Bisection in `warm_enough`: search this far above the dew point, in enough
# halvings to get well under 0.001 deg C
BISECT_RANGE = 40.0
BISECT_STEPS = 40


def dew_point(temperature: float, relative_humidity: float) -> float:
    """Dew point of air at this temperature and relative humidity.

    gamma = ln(RH/100) + a*T/(b+T);  Td = b*gamma / (a - gamma)
    """
    gamma = math.log(relative_humidity / PERCENT) + _magnus(temperature)
    return MAGNUS_B * gamma / (MAGNUS_A - gamma)


def relative_humidity(temperature: float, dew_point: float) -> float:
    """Relative humidity of air with this dew point, at this temperature.

    RH(T) = 100 * exp(a*Td/(b+Td) - a*T/(b+T))
    """
    return PERCENT * math.exp(_magnus(dew_point) - _magnus(temperature))


def _magnus(temperature: float) -> float:
    """The exponent a*T/(b+T) shared by both directions of the Magnus formula."""
    return MAGNUS_A * temperature / (MAGNUS_B + temperature)


def limits(temperature: float, settings: Humidity) -> tuple[float, float]:
    """(target, critical) relative humidity at this indoor temperature.

    The target slides up as the space gets colder, because mould and rust
    slow down in the cold. docs/physics.md#sliding-humidity-limit
    """
    warm_shortfall = settings.warm_temperature - temperature
    target = settings.target_warm + settings.slope * warm_shortfall
    target = min(max(target, settings.target_warm), settings.target_max)
    return target, target + settings.critical_gap


@dataclass(frozen=True)
class WarmEnough:
    """Lowest indoor temperatures that keep the air dry enough."""

    target: float
    """At or below the target humidity from here up."""

    critical: float
    """Below the critical humidity from here up."""


def warm_enough(dew_point: float, settings: Humidity) -> WarmEnough:
    """How warm the space must be to keep air with this dew point dry enough.

    Assumes the water in the air stays the same, so warming only lowers the
    relative humidity.
    """
    return WarmEnough(
        target=_lowest_dry(
            dew_point, lambda temperature: limits(temperature, settings)[0]
        ),
        critical=_lowest_dry(
            dew_point, lambda temperature: limits(temperature, settings)[1]
        ),
    )


def _lowest_dry(dew_point: float, limit_at: Callable[[float], float]) -> float:
    """Lowest temperature where the relative humidity is within `limit_at`.

    Both the humidity and the sliding limit fall as the temperature rises,
    so there's no closed form: find the crossing by bisection.
    """
    low, high = dew_point, dew_point + BISECT_RANGE
    for _ in range(BISECT_STEPS):
        middle = (low + high) / 2
        if relative_humidity(middle, dew_point) > limit_at(middle):
            low = middle
        else:
            high = middle
    return high

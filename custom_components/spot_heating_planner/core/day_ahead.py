"""The day-ahead forecast: tomorrow's plan, as it looked the day before.

When tomorrow's prices arrive (early afternoon), the plan already covers
all of tomorrow. Its hours are kept as they are then, 10 to 34 hours before
they happen, so they can later be set against what actually happened. The
gaps show where the weather forecast, the learned room or real life (an open
door) differed from what was expected.

Comparing against the plan in force when an hour starts would show nothing:
the heaters follow that plan exactly.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from .planner import HourCost, Plan


@dataclass(frozen=True, kw_only=True)
class ForecastHour:
    """One hour as forecast the day before."""

    start: datetime
    energy_kwh: float
    cost: float
    """In currency units, incl. fixed costs."""

    temperature: float
    """Predicted indoor temperature at the end of the hour, deg C."""


def snapshot(
    plan: Plan, costs: list[HourCost], *, start: datetime, end: datetime
) -> list[ForecastHour]:
    """The plan's hours from `start` up to `end` (tomorrow, local time)."""
    cost_by_start = {c.start: c for c in costs}
    hours = []
    for hour in plan.hours:
        cost = cost_by_start.get(hour.start)
        if cost is None or not start <= hour.start < end:
            continue
        hours.append(
            ForecastHour(
                start=hour.start,
                energy_kwh=cost.energy_kwh,
                cost=cost.cost,
                temperature=hour.temperature,
            )
        )
    return hours

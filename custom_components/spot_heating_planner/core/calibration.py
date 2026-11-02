"""The calibration run: one heat-then-coast cycle so learning starts quickly.

Learning the room needs both steps with heating (they show how much a kWh
warms it) and steps without (they show how fast it loses heat). Instead of
waiting for them to happen by chance, the run heats for
calibration_heat_minutes and then lets the space coast for
calibration_coast_minutes, starting in the cheapest hour within the
lookahead. The safety rules stay in charge throughout; during the coast,
frost and critical humidity still heat (see `during_coast_heat_anyway`).
"""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Calibration


class Phase(StrEnum):
    """Where a calibration run is."""

    WAITING = "waiting"
    HEAT = "heat"
    COAST = "coast"
    DONE = "done"


def best_start(
    prices: list[tuple[datetime, float]], now: datetime, calibration: Calibration
) -> datetime:
    """Start of the cheapest hour within the lookahead; now if no prices."""
    current = now.replace(minute=0, second=0, microsecond=0)
    horizon = current + timedelta(hours=calibration.lookahead_hours)
    candidates = [
        (price, start) for start, price in prices if current <= start < horizon
    ]
    if not candidates:
        return now
    _, start = min(candidates)
    return max(start, now)


def phase(now: datetime, start: datetime, calibration: Calibration) -> Phase:
    """Which part of the run `now` falls in."""
    heat_end = start + timedelta(minutes=calibration.heat_minutes)
    coast_end = heat_end + timedelta(minutes=calibration.coast_minutes)
    if now < start:
        return Phase.WAITING
    if now < heat_end:
        return Phase.HEAT
    if now < coast_end:
        return Phase.COAST
    return Phase.DONE


def during_coast_heat_anyway(mode: str) -> bool:
    """Whether the thermostat's reason to heat overrides the coast.

    Hard wishes (frost, critical humidity, an override) protect the space
    and win; soft ones wait until the run is over.
    """
    return mode in {"frost", "humidity_critical", "override"}

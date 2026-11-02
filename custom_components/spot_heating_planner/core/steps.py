"""Collecting one learning step, minute by minute.

The runtime opens a step at a step boundary, feeds it every minute, and
closes it at the next boundary. A step missing any of the readings learning
needs (indoor at both ends, the real outdoor temperature) yields nothing;
learning would rather skip a step than learn from a guess.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .learning import StepSample

if TYPE_CHECKING:
    from datetime import datetime

SECONDS_PER_MINUTE = 60


@dataclass
class OpenStep:
    """A learning step under way."""

    start: datetime
    indoor_temperature_start: float
    energy_start_kwh: float | None
    minutes: int = 0
    heating_minutes: int = 0
    outdoor_temperatures: list[float] = field(default_factory=list)

    def add_minute(self, *, heating: bool, outdoor_temperature: float | None) -> None:
        """Count one minute: whether the heaters were on, and the outdoor reading."""
        self.minutes += 1
        self.heating_minutes += 1 if heating else 0
        if outdoor_temperature is not None:
            self.outdoor_temperatures.append(outdoor_temperature)

    def close(
        self,
        now: datetime,
        *,
        indoor_temperature_end: float | None,
        energy_end_kwh: float | None,
    ) -> StepSample | None:
        """The finished step; None if a reading learning needs is missing."""
        if (
            indoor_temperature_end is None
            or not self.outdoor_temperatures
            or self.minutes == 0
        ):
            return None
        return StepSample(
            start=self.start,
            minutes=(now - self.start).total_seconds() / SECONDS_PER_MINUTE,
            indoor_temperature_start=self.indoor_temperature_start,
            indoor_temperature_end=indoor_temperature_end,
            outdoor_temperature=sum(self.outdoor_temperatures)
            / len(self.outdoor_temperatures),
            heat_share=self.heating_minutes / self.minutes,
            energy_kwh=self._energy_used(energy_end_kwh),
        )

    def _energy_used(self, energy_end_kwh: float | None) -> float | None:
        """KWh used in the step; None without a meter or if it was reset."""
        if self.energy_start_kwh is None or energy_end_kwh is None:
            return None
        used = energy_end_kwh - self.energy_start_kwh
        return used if used >= 0 else None


def is_boundary(now: datetime, step_minutes: int) -> bool:
    """Whether a step starts at this minute (0, 15, 30, 45 for 15 minutes)."""
    return now.minute % step_minutes == 0

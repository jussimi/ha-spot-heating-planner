"""Reading sensor states: units converted, nonsense dropped, noise smoothed."""

import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
    UnitOfTemperature,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.unit_conversion import EnergyConverter, TemperatureConverter

from .const import MEDIAN_WINDOW

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant, State

NOT_A_READING = {STATE_UNAVAILABLE, STATE_UNKNOWN, ""}


def number(state: State | None) -> float | None:
    """The state as a number, or None if it isn't one."""
    if state is None or state.state in NOT_A_READING:
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


def temperature(state: State | None) -> float | None:
    """A temperature reading in deg C, whatever unit the sensor reports."""
    value = number(state)
    if value is None or state is None:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature.CELSIUS)
    return _convert(TemperatureConverter, value, unit, UnitOfTemperature.CELSIUS)


def energy(state: State | None) -> float | None:
    """An energy counter in kWh, whatever unit the sensor reports."""
    value = number(state)
    if value is None or state is None:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, UnitOfEnergy.KILO_WATT_HOUR)
    return _convert(EnergyConverter, value, unit, UnitOfEnergy.KILO_WATT_HOUR)


def _convert(
    converter: type[TemperatureConverter | EnergyConverter],
    value: float,
    unit: str,
    to_unit: str,
) -> float | None:
    """The value in `to_unit`; None if the sensor's unit makes no sense here."""
    try:
        return converter.convert(value, unit, to_unit)
    except HomeAssistantError:
        return None


def total_energy(hass: HomeAssistant, entity_ids: list[str]) -> float | None:
    """Sum of the energy counters in kWh; None if any of them has no reading.

    A partial sum would look like a counter reset and spoil a learning step.
    """
    readings = [energy(hass.states.get(entity_id)) for entity_id in entity_ids]
    if not readings or any(r is None for r in readings):
        return None
    return sum(r for r in readings if r is not None)


@dataclass
class Smoothed:
    """Recent readings of one sensor, smoothed with a median.

    A single odd reading, or a door opened for a moment, doesn't swing the
    median the way it would swing the latest value.
    """

    samples: deque[tuple[datetime, float]] = field(default_factory=deque)

    def add(self, now: datetime, value: float | None) -> None:
        """Remember a reading; a missing one is simply skipped."""
        if value is not None:
            self.samples.append((now, value))
        self._forget_before(now - MEDIAN_WINDOW)

    def value(self, now: datetime) -> float | None:
        """Median of the readings in the window; None without any."""
        self._forget_before(now - MEDIAN_WINDOW)
        if not self.samples:
            return None
        return statistics.median(v for _, v in self.samples)

    def _forget_before(self, cutoff: datetime) -> None:
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

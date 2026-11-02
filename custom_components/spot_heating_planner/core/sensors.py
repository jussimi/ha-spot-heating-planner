"""Sanity checks on sensor readings.

A reading that fails these is treated as missing: the safety rules then
handle a missing indoor temperature, and learning skips the affected steps.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Sensors
    from .learning import StepSample

PERCENT = 100.0


def plausible_temperature(reading: float | None, sensors: Sensors) -> float | None:
    """The reading, or None if it is missing or physically impossible here."""
    low, high = sensors.temperature_range
    return reading if reading is not None and low <= reading <= high else None


def plausible_humidity(reading: float | None) -> float | None:
    """The reading, or None if it is missing or not a relative humidity."""
    return reading if reading is not None and 0 < reading <= PERCENT else None


def stuck_while_heating(recent: list[StepSample], sensors: Sensors) -> bool:
    """Whether the indoor temperature hasn't moved through a stretch of heating.

    Heating for sensor_stuck_heating_minutes warms any real space by far more
    than a sensor step, so an unchanged reading means the sensor has stopped
    reporting or is somewhere the heat doesn't reach. Looks at the most
    recent steps, newest last.
    """
    heating = 0.0
    readings: set[float] = set()
    for sample in reversed(recent):
        readings |= {sample.indoor_temperature_start, sample.indoor_temperature_end}
        if len(readings) > 1:
            return False
        heating += sample.heat_share * sample.minutes
        if heating >= sensors.stuck_heating_minutes:
            return True
    return False

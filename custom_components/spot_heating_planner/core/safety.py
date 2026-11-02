"""The three safety rules, checked every minute before the plan.

    sensor_fault  no indoor temperature  -> heat; the heaters' own thermostats
                                            cap the temperature
    emergency     below the emergency temperature -> heat at any price
    max_temp      at the upper limit     -> never heat

These are the only rules with hysteresis (thermostat-style on/off bands).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Limits


@dataclass
class SafetyState:
    """What the safety rules remember between minutes, for hysteresis."""

    emergency: bool = False
    max_blocked: bool = False


@dataclass(frozen=True)
class SafetyResult:
    """A safety rule in control: its mode and whether to heat."""

    mode: str
    heat: bool


def upper_limit(limits: Limits, *, override_active: bool) -> float:
    """Never heat above this. An override may aim higher than the maximum."""
    if override_active:
        return max(limits.max_temperature, limits.override_temperature)
    return limits.max_temperature


def check(
    t_in: float | None, state: SafetyState, limits: Limits, *, override_active: bool
) -> SafetyResult | None:
    """The safety rule in control, or None to follow the plan.

    Updates `state`, which carries the hysteresis from minute to minute.
    """
    if t_in is None:
        return SafetyResult("sensor_fault", heat=True)

    upper = upper_limit(limits, override_active=override_active)
    state.emergency = _emergency(t_in, limits, active=state.emergency)
    state.max_blocked = _max_blocked(t_in, upper, limits, active=state.max_blocked)
    if state.emergency:
        return SafetyResult("emergency", heat=True)
    if state.max_blocked:
        return SafetyResult("max_temp", heat=False)
    return None


def _emergency(t_in: float, limits: Limits, *, active: bool) -> bool:
    """On below the emergency temperature, off once emergency_band above it."""
    if active:
        return t_in < limits.emergency_temperature + limits.emergency_band
    return t_in < limits.emergency_temperature


def _max_blocked(t_in: float, upper: float, limits: Limits, *, active: bool) -> bool:
    """On at the upper limit, off once max_temp_band below it."""
    if active:
        return t_in > upper - limits.max_temp_band
    return t_in >= upper

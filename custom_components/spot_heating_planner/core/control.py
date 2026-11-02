"""What to do this minute: the layers of control in their order.

1. a safety rule, if one is in control
2. a calibration run, while one is under way
3. the hourly plan, once the room is known
4. the plain thermostat, until then
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .calibration import Phase, during_coast_heat_anyway

if TYPE_CHECKING:
    from datetime import datetime

    from .planner import Plan, ThermostatDecision
    from .safety import SafetyResult

CALIBRATING = "calibrating"


@dataclass(frozen=True)
class Decision:
    """Whether to heat this minute, and why."""

    mode: str
    heat: bool


def decide(
    now: datetime,
    *,
    safety: SafetyResult | None,
    calibration: Phase | None,
    plan: Plan | None,
    thermostat: ThermostatDecision,
) -> Decision:
    """Combine the layers: the first one with something to say wins."""
    if safety is not None:
        return Decision(safety.mode, heat=safety.heat)
    if calibration is Phase.HEAT:
        return Decision(CALIBRATING, heat=True)
    if calibration is Phase.COAST:
        # Hard wishes still protect the space while it coasts
        if thermostat.heat and during_coast_heat_anyway(thermostat.mode):
            return Decision(thermostat.mode, heat=True)
        return Decision(CALIBRATING, heat=False)
    if plan is not None:
        return Decision(plan.mode, heat=now < plan.heat_until)
    return Decision(thermostat.mode, heat=thermostat.heat)

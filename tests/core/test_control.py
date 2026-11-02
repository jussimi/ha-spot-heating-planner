"""The layers of control, in order."""

from datetime import timedelta

from custom_components.spot_heating_planner.core.calibration import Phase
from custom_components.spot_heating_planner.core.control import (
    CALIBRATING,
    Decision,
    decide,
)
from custom_components.spot_heating_planner.core.planner import (
    Plan,
    ThermostatDecision,
)
from custom_components.spot_heating_planner.core.safety import SafetyResult

from .example import NOW

IDLE = ThermostatDecision("idle", heat=False)
MINIMUM = ThermostatDecision("minimum", heat=True)
HUMID = ThermostatDecision("humidity", heat=True)


def plan_heating_for(minutes: int) -> Plan:
    return Plan(
        mode="preheat",
        minutes=minutes,
        heat_until=NOW + timedelta(minutes=minutes),
        humidity_target=None,
        humidity_critical=None,
        coasting_hours=None,
        target_unreachable=False,
        hours=[],
    )


def test_safety_wins_over_everything() -> None:
    emergency = SafetyResult("emergency", heat=True)
    decision = decide(
        NOW, safety=emergency, calibration=Phase.COAST, plan=None, thermostat=IDLE
    )
    assert decision == Decision("emergency", heat=True)


def test_calibration_heats_then_coasts() -> None:
    heat = decide(NOW, safety=None, calibration=Phase.HEAT, plan=None, thermostat=IDLE)
    coast = decide(
        NOW, safety=None, calibration=Phase.COAST, plan=None, thermostat=HUMID
    )
    assert heat == Decision(CALIBRATING, heat=True)
    assert coast == Decision(CALIBRATING, heat=False)


def test_the_minimum_interrupts_the_coast() -> None:
    decision = decide(
        NOW, safety=None, calibration=Phase.COAST, plan=None, thermostat=MINIMUM
    )
    assert decision == Decision("minimum", heat=True)


def test_plan_heats_until_its_minute() -> None:
    plan = plan_heating_for(30)
    early = decide(NOW, safety=None, calibration=None, plan=plan, thermostat=IDLE)
    later = NOW + timedelta(minutes=45)
    late = decide(later, safety=None, calibration=None, plan=plan, thermostat=IDLE)
    assert early == Decision("preheat", heat=True)
    assert late == Decision("preheat", heat=False)


def test_thermostat_without_a_plan() -> None:
    decision = decide(NOW, safety=None, calibration=None, plan=None, thermostat=MINIMUM)
    assert decision == Decision("minimum", heat=True)


def test_finished_calibration_hands_over() -> None:
    plan = plan_heating_for(0)
    decision = decide(
        NOW, safety=None, calibration=Phase.DONE, plan=plan, thermostat=MINIMUM
    )
    assert decision == Decision("preheat", heat=False)

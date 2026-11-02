"""The three safety rules."""

from dataclasses import replace

from custom_components.spot_heating_planner.core.safety import (
    SafetyResult,
    SafetyState,
    check,
)

from .example import CFG

EMERGENCY = SafetyResult("emergency", heat=True)
MAX_TEMP = SafetyResult("max_temp", heat=False)


def test_missing_temperature_heats() -> None:
    result = check(None, SafetyState(), CFG.limits, override_active=False)
    assert result == SafetyResult("sensor_fault", heat=True)


def test_emergency_has_hysteresis() -> None:
    state = SafetyState()
    assert check(0.5, state, CFG.limits, override_active=False) == EMERGENCY
    assert check(1.5, state, CFG.limits, override_active=False) == EMERGENCY  # below 2
    assert check(2.0, state, CFG.limits, override_active=False) is None
    assert check(1.5, state, CFG.limits, override_active=False) is None  # not below 1


def test_max_temperature_blocks_until_one_degree_below() -> None:
    state = SafetyState()
    assert check(15.0, state, CFG.limits, override_active=False) == MAX_TEMP
    assert check(14.5, state, CFG.limits, override_active=False) == MAX_TEMP
    assert check(14.0, state, CFG.limits, override_active=False) is None


def test_override_raises_the_maximum() -> None:
    limits = replace(CFG.limits, override_temperature=18)
    assert check(16, SafetyState(), limits, override_active=True) is None


def test_emergency_temperature_may_be_below_freezing() -> None:
    limits = replace(CFG.limits, min_temperature=-10, emergency_temperature=-15)
    assert check(-12, SafetyState(), limits, override_active=False) is None
    emergency = check(-16, SafetyState(), limits, override_active=False)
    assert emergency == EMERGENCY

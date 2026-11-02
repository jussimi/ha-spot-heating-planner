"""The calibration run."""

from datetime import timedelta

from custom_components.spot_heating_planner.core.calibration import (
    Phase,
    best_start,
    during_coast_heat_anyway,
    phase,
)

from .example import CFG, NOW, prices


def test_starts_in_the_cheapest_hour_ahead() -> None:
    start = best_start(prices((9.0, 7.0, 2.0, 5.0) + (8.0,) * 20), NOW, CFG.calibration)
    assert start == NOW + timedelta(hours=2)


def test_ignores_cheap_hours_beyond_the_lookahead() -> None:
    lookahead = CFG.calibration.lookahead_hours
    pattern = (5.0, 4.0) + (8.0,) * (lookahead - 2) + (1.0,) * 10
    assert best_start(prices(pattern), NOW, CFG.calibration) == NOW + timedelta(hours=1)


def test_starts_now_without_prices() -> None:
    assert best_start([], NOW, CFG.calibration) == NOW


def test_never_starts_in_the_past() -> None:
    later = NOW + timedelta(minutes=20)
    assert best_start(prices((1.0, 5.0)), later, CFG.calibration) == later


def test_phases_follow_the_clock() -> None:
    start = NOW
    assert phase(start - timedelta(minutes=1), start, CFG.calibration) == Phase.WAITING
    assert phase(start, start, CFG.calibration) == Phase.HEAT
    heat_end = start + timedelta(minutes=CFG.calibration.heat_minutes)
    assert phase(heat_end, start, CFG.calibration) == Phase.COAST
    coast_end = heat_end + timedelta(minutes=CFG.calibration.coast_minutes)
    assert phase(coast_end, start, CFG.calibration) == Phase.DONE


def test_only_hard_wishes_interrupt_the_coast() -> None:
    assert during_coast_heat_anyway("minimum")
    assert during_coast_heat_anyway("humidity_critical")
    assert not during_coast_heat_anyway("humidity")
    assert not during_coast_heat_anyway("dew_point")

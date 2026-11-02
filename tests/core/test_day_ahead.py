"""The day-ahead forecast snapshot."""

from datetime import timedelta

from custom_components.spot_heating_planner.core.day_ahead import snapshot
from custom_components.spot_heating_planner.core.planner import hour_costs, plan_hour

from .example import CFG, HEATED_ROOM, NOW, inputs

TOMORROW = NOW.replace(hour=0) + timedelta(days=1)


def test_keeps_only_tomorrows_hours() -> None:
    plan = plan_hour(
        inputs(indoor_temperature=4, price_pattern=(8.0,) * 34), CFG, HEATED_ROOM
    )
    costs = hour_costs(plan, HEATED_ROOM, CFG)
    hours = snapshot(plan, costs, start=TOMORROW, end=TOMORROW + timedelta(days=1))
    assert hours
    assert all(TOMORROW <= h.start < TOMORROW + timedelta(days=1) for h in hours)


def test_carries_energy_cost_and_temperature() -> None:
    plan = plan_hour(
        inputs(indoor_temperature=4, price_pattern=(8.0,) * 34), CFG, HEATED_ROOM
    )
    costs = {c.start: c for c in hour_costs(plan, HEATED_ROOM, CFG)}
    planned = {h.start: h for h in plan.hours}
    for hour in snapshot(
        plan, list(costs.values()), start=TOMORROW, end=TOMORROW + timedelta(days=1)
    ):
        assert hour.energy_kwh == costs[hour.start].energy_kwh
        assert hour.cost == costs[hour.start].cost
        assert hour.temperature == planned[hour.start].temperature

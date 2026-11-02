"""The hourly plan."""

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.spot_heating_planner.core.planner import (
    NO_OUTSIDE_DATA_T,
    outside_conditions,
    plan_hour,
    summarize,
    thermostat,
)

from .example import CFG, CHEAP, HEATED_ROOM, NORMAL, NOW, PEAK, forecast, inputs

WEAK = replace(
    HEATED_ROOM, heater_power_kw=HEATED_ROOM.room.heat_loss_kw * 5
)  # can hold +5 deg C


def test_warm_dry_space_stays_idle() -> None:
    plan = plan_hour(
        inputs(indoor_temperature=10, outdoor_temperature=5), CFG, HEATED_ROOM
    )
    assert plan.minutes == 0
    assert plan.mode == "idle"


def test_cold_space_heats_for_frost() -> None:
    plan = plan_hour(
        inputs(indoor_temperature=3.5, outdoor_temperature=-10), CFG, HEATED_ROOM
    )
    assert plan.minutes > 0
    assert plan.mode == "frost"


def test_preheats_in_cheap_hours_before_a_long_peak() -> None:
    # Cheap now, then a 6 h peak the space can't coast through unheated
    pattern = (CHEAP,) * 3 + (PEAK,) * 6 + (NORMAL,) * 15
    plan = plan_hour(
        inputs(indoor_temperature=7, outdoor_temperature=-10, price_pattern=pattern),
        CFG,
        HEATED_ROOM,
    )
    assert plan.minutes > 0
    assert plan.mode == "preheat"
    assert sum(h.minutes for h in plan.hours[3:9]) == 0  # coasts through the peak


def test_never_drops_below_the_lower_limit_in_the_plan() -> None:
    pattern = (CHEAP, PEAK, PEAK, NORMAL, PEAK, CHEAP) * 4
    plan = plan_hour(
        inputs(indoor_temperature=6, outdoor_temperature=-25, price_pattern=pattern),
        CFG,
        HEATED_ROOM,
    )
    lower_limit = CFG.limits.min_temperature + CFG.limits.margin
    assert min(h.temperature for h in plan.hours) >= lower_limit - 0.1
    assert not plan.target_unreachable


def test_flat_prices_heat_no_earlier_than_needed() -> None:
    plan = plan_hour(
        inputs(indoor_temperature=8, outdoor_temperature=-10), CFG, HEATED_ROOM
    )
    assert plan.minutes == 0  # plenty of runway, nothing cheaper to wait for


def test_humid_space_heats_at_a_normal_price() -> None:
    # At 8 deg C the target is 72 % and critical 82 %
    plan = plan_hour(
        inputs(indoor_temperature=8, indoor_humidity=78, outdoor_temperature=0),
        CFG,
        HEATED_ROOM,
    )
    assert plan.minutes > 0
    assert plan.mode == "humidity"


def test_humidity_waits_out_an_expensive_hour() -> None:
    pattern = (PEAK,) + (NORMAL,) * 23
    plan = plan_hour(
        inputs(
            indoor_temperature=8,
            indoor_humidity=74,
            outdoor_temperature=0,
            price_pattern=pattern,
        ),
        CFG,
        HEATED_ROOM,
    )
    assert plan.minutes == 0
    assert plan.mode == "price_ceiling"


def test_critical_humidity_heats_even_when_expensive() -> None:
    plan = plan_hour(
        inputs(
            indoor_temperature=8,
            indoor_humidity=92,
            outdoor_temperature=0,
            price_pattern=(PEAK,) * 24,
        ),
        CFG,
        HEATED_ROOM,
    )
    assert plan.minutes > 0
    assert plan.mode == "humidity_critical"


def test_dew_point_wish_heats_when_outside_air_is_moist() -> None:
    plan = plan_hour(
        inputs(indoor_temperature=12, outdoor_temperature=16, outdoor_dew_point=13),
        CFG,
        HEATED_ROOM,
    )
    assert plan.minutes > 0
    assert plan.mode == "dew_point"


def test_override_heats_to_its_target() -> None:
    until = NOW + timedelta(hours=3)
    plan = plan_hour(
        inputs(indoor_temperature=8, outdoor_temperature=0, override_until=until),
        CFG,
        HEATED_ROOM,
    )
    assert plan.minutes == 60
    assert plan.mode == "override"


def test_short_burst_when_little_heat_is_needed_in_a_peak() -> None:
    plan = plan_hour(
        inputs(
            indoor_temperature=4.3, outdoor_temperature=-5, price_pattern=(PEAK,) * 24
        ),
        CFG,
        HEATED_ROOM,
    )
    assert 0 < plan.minutes < 60


def test_unreachable_target_is_flagged() -> None:
    plan = plan_hour(inputs(indoor_temperature=4, outdoor_temperature=-25), CFG, WEAK)
    assert plan.target_unreachable
    assert plan.minutes == 60


def test_mid_hour_plan_heats_only_the_rest_of_the_hour() -> None:
    now = NOW + timedelta(minutes=40)
    plan = plan_hour(
        inputs(indoor_temperature=3.5, outdoor_temperature=-10, now=now),
        CFG,
        HEATED_ROOM,
    )
    assert plan.minutes <= 20
    assert plan.heat_until <= NOW + timedelta(hours=1)


def test_every_setting_is_configurable() -> None:
    cfg = CFG.with_groups(replace(CFG.limits, min_temperature=8, margin=0))
    plan = plan_hour(
        inputs(indoor_temperature=7, outdoor_temperature=0), cfg, HEATED_ROOM
    )
    assert plan.minutes > 0
    assert plan.mode == "frost"


# --- Outside data: the sensor now, the forecast later -------------------------


def test_current_hour_uses_the_sensor_and_later_hours_the_forecast() -> None:
    inp = inputs(outdoor_temperature=-3, outdoor_dew_point=-5)
    inp.forecast = forecast(-10, dew=-12)
    assert outside_conditions(NOW, inp) == (-3, -5)
    assert outside_conditions(NOW + timedelta(hours=1), inp) == (-10, -12)


def test_forecast_stands_in_for_a_missing_sensor() -> None:
    inp = inputs(outdoor_temperature=None)
    inp.forecast = forecast(-10, dew=-12)
    assert outside_conditions(NOW, inp) == (-10, -12)


def test_sensor_stands_in_for_a_missing_forecast() -> None:
    inp = inputs(outdoor_temperature=-3, outdoor_dew_point=-5)
    inp.forecast = []
    assert outside_conditions(NOW + timedelta(hours=5), inp) == (-3, -5)


def test_no_outside_data_at_all() -> None:
    inp = inputs(outdoor_temperature=None)
    inp.forecast = []
    assert outside_conditions(NOW, inp) == (NO_OUTSIDE_DATA_T, None)


def test_dew_point_wish_starts_before_moist_air_arrives() -> None:
    inp = inputs(indoor_temperature=12, outdoor_temperature=14, outdoor_dew_point=5)
    inp.forecast = forecast(14, hours=3, dew=5) + forecast(
        18, hours=21, start=NOW + timedelta(hours=3), dew=14
    )
    plan = plan_hour(inp, CFG, HEATED_ROOM)
    assert plan.hours[0].soft_lower_limit == pytest.approx(7)  # 5 + 2 margin
    assert plan.hours[4].soft_lower_limit == pytest.approx(15)  # 14 + 2 margin
    assert sum(h.minutes for h in plan.hours[:4]) > 0


# --- Thermostat, before the model is known ------------------------------------


def test_thermostat_heats_below_the_minimum() -> None:
    decision = thermostat(inputs(indoor_temperature=3.5), CFG, heating=False)
    assert decision.heat
    assert decision.mode == "frost"


def test_thermostat_keeps_heating_through_its_band() -> None:
    # Lower limit 4 deg C: off at 4.5 when idle, still on at 4.5 once heating
    assert not thermostat(inputs(indoor_temperature=4.5), CFG, heating=False).heat
    assert thermostat(inputs(indoor_temperature=4.5), CFG, heating=True).heat
    assert not thermostat(inputs(indoor_temperature=5.1), CFG, heating=True).heat


def test_thermostat_lets_humidity_wait_out_an_expensive_hour() -> None:
    pattern = (PEAK,) + (NORMAL,) * 23
    decision = thermostat(
        inputs(
            indoor_temperature=8,
            indoor_humidity=78,
            outdoor_temperature=0,
            price_pattern=pattern,
        ),
        CFG,
        heating=False,
    )
    assert not decision.heat
    assert decision.mode == "price_ceiling"


def test_thermostat_heats_for_critical_humidity_at_any_price() -> None:
    inp = inputs(
        indoor_temperature=8,
        indoor_humidity=92,
        outdoor_temperature=0,
        price_pattern=(PEAK,) * 24,
    )
    decision = thermostat(inp, CFG, heating=False)
    assert decision.heat
    assert decision.mode == "humidity_critical"


# --- Summary for the dashboard -------------------------------------------------------


def test_summary_counts_hours_cost_and_next_heating() -> None:
    pattern = (CHEAP,) * 3 + (PEAK,) * 6 + (NORMAL,) * 15
    plan = plan_hour(
        inputs(indoor_temperature=7, outdoor_temperature=-10, price_pattern=pattern),
        CFG,
        HEATED_ROOM,
    )
    summary = summarize(plan, HEATED_ROOM, CFG, until=NOW + timedelta(hours=24))
    heating = [h for h in plan.hours if h.minutes > 0]
    assert summary.next_heating == heating[0].start
    assert summary.heating_hours == pytest.approx(sum(h.minutes for h in heating) / 60)
    expected = sum(
        h.minutes / 60 * (h.price + CFG.prices.fixed_energy_cost) / 100 for h in heating
    )
    assert summary.cost == pytest.approx(expected)


def test_summary_of_an_idle_plan() -> None:
    plan = plan_hour(
        inputs(indoor_temperature=10, outdoor_temperature=5), CFG, HEATED_ROOM
    )
    summary = summarize(plan, HEATED_ROOM, CFG, until=NOW + timedelta(hours=24))
    assert summary.next_heating is None
    assert summary.heating_hours == 0
    assert summary.cost == 0

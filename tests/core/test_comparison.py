"""The comparison thermostat."""

import pytest

from custom_components.spot_heating_planner.core.comparison import (
    HourHistory,
    mean_indoor_temperature,
    metered_hour,
    thermostat_hour,
    totals,
)

from .example import HEATED_ROOM, NOW

FIXED = 8.5


def hour(
    *,
    outdoor: float | None = -10.0,
    price: float | None = 10.0,
    energy: float | None = None,
    indoor: float | None = None,
) -> HourHistory:
    return HourHistory(
        start=NOW,
        outdoor_temperature=outdoor,
        price=price,
        energy_kwh=energy,
        indoor_temperature=indoor,
    )


def test_thermostat_replaces_the_heat_loss() -> None:
    # 25 W/deg C * (5 - -10) = 375 W for an hour
    result = thermostat_hour(hour(), HEATED_ROOM, 5.0, FIXED)
    assert result is not None
    assert result.energy_kwh == pytest.approx(0.375)
    assert result.cost == pytest.approx(0.375 * (10.0 + FIXED) / 100)


def test_thermostat_is_capped_at_the_heaters_power() -> None:
    result = thermostat_hour(hour(outdoor=-60.0), HEATED_ROOM, 5.0, FIXED)
    assert result is not None
    assert result.energy_kwh == HEATED_ROOM.heater_power_kw


def test_no_heat_when_warm_outside() -> None:
    result = thermostat_hour(hour(outdoor=10.0), HEATED_ROOM, 5.0, FIXED)
    assert result is not None
    assert result.energy_kwh == 0


def test_missing_data_isnt_counted() -> None:
    assert thermostat_hour(hour(outdoor=None), HEATED_ROOM, 5.0, FIXED) is None
    assert thermostat_hour(hour(price=None), HEATED_ROOM, 5.0, FIXED) is None
    assert metered_hour(hour(energy=None), FIXED) is None


def test_metered_cost() -> None:
    result = metered_hour(hour(energy=0.8, price=20.0), FIXED)
    assert result is not None
    assert result.cost == pytest.approx(0.8 * (20.0 + FIXED) / 100)


def test_totals_skip_missing_hours() -> None:
    a = metered_hour(hour(energy=1.0), FIXED)
    b = metered_hour(hour(energy=None), FIXED)
    result = totals([a, b])
    assert result.hours == 1
    assert result.energy_kwh == 1.0


def test_mean_indoor_temperature() -> None:
    history = [hour(indoor=4.0), hour(indoor=6.0), hour(indoor=None)]
    assert mean_indoor_temperature(history) == 5.0
    assert mean_indoor_temperature([hour()]) is None

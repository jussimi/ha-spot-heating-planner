"""The comparison thermostat."""

import pytest

from custom_components.spot_heating_planner.core.comparison import (
    HourHistory,
    mean_indoor_temperature,
    metered_hour,
    thermostat_hour,
    totals,
)

from .example import NOW, ROOM

PRICE = 18.5  # 10 c spot + 8.5 c fixed


def hour(  # noqa: PLR0913 - one argument per input
    *,
    outdoor: float | None = -10.0,
    price: float | None = PRICE,
    heat_loss: float | None = ROOM.heat_loss_kw,
    power: float | None = 1.0,
    energy: float | None = None,
    indoor: float | None = None,
) -> HourHistory:
    return HourHistory(
        start=NOW,
        outdoor_temperature=outdoor,
        energy_price=price,
        heat_loss_kw=heat_loss,
        heater_power_kw=power,
        energy_kwh=energy,
        indoor_temperature=indoor,
    )


def test_thermostat_replaces_the_heat_loss() -> None:
    # 25 W/deg C * (5 - -10) = 375 W for an hour
    result = thermostat_hour(hour(), 5.0)
    assert result is not None
    assert result.energy_kwh == pytest.approx(0.375)
    assert result.cost == pytest.approx(0.375 * PRICE / 100)


def test_each_hour_uses_its_own_room() -> None:
    # The same hour with a leakier room learned at the time
    leaky = thermostat_hour(hour(heat_loss=0.05), 5.0)
    assert leaky is not None
    assert leaky.energy_kwh == pytest.approx(0.75)


def test_each_hour_uses_its_own_price() -> None:
    cheaper = thermostat_hour(hour(price=9.0), 5.0)
    assert cheaper is not None
    assert cheaper.cost == pytest.approx(0.375 * 9.0 / 100)


def test_thermostat_is_capped_at_the_heaters_power() -> None:
    result = thermostat_hour(hour(outdoor=-60.0), 5.0)
    assert result is not None
    assert result.energy_kwh == 1.0


def test_no_heat_when_warm_outside() -> None:
    result = thermostat_hour(hour(outdoor=10.0), 5.0)
    assert result is not None
    assert result.energy_kwh == 0


def test_temperatures_are_not_multiples_of_each_other() -> None:
    # At 6 deg C outside a 5 deg C thermostat rests while a 10 deg C one heats
    mild = hour(outdoor=6.0)
    at_5, at_10 = thermostat_hour(mild, 5.0), thermostat_hour(mild, 10.0)
    assert at_5 is not None
    assert at_10 is not None
    assert at_5.energy_kwh == 0
    assert at_10.energy_kwh > 0


def test_missing_data_isnt_counted() -> None:
    assert thermostat_hour(hour(outdoor=None), 5.0) is None
    assert thermostat_hour(hour(price=None), 5.0) is None
    assert thermostat_hour(hour(heat_loss=None), 5.0) is None  # room not learned
    assert thermostat_hour(hour(power=None), 5.0) is None
    assert metered_hour(hour(energy=None)) is None


def test_metered_cost() -> None:
    result = metered_hour(hour(energy=0.8, price=28.5))
    assert result is not None
    assert result.cost == pytest.approx(0.8 * 28.5 / 100)


def test_totals_skip_missing_hours() -> None:
    result = totals([metered_hour(hour(energy=1.0)), metered_hour(hour(energy=None))])
    assert result.hours == 1
    assert result.energy_kwh == 1.0


def test_mean_indoor_temperature() -> None:
    history = [hour(indoor=4.0), hour(indoor=6.0), hour(indoor=None)]
    assert mean_indoor_temperature(history) == 5.0
    assert mean_indoor_temperature([hour()]) is None

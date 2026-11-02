"""Sanity checks on the settings."""

from dataclasses import fields, replace
from typing import TYPE_CHECKING

import pytest

from custom_components.spot_heating_planner.core.config import (
    MAX_WINDOW_DAYS,
    Calibration,
    Config,
    ConfigError,
    Heaters,
    Humidity,
    Learning,
    Limits,
    ManualRoom,
    Prices,
    Sensors,
    Solver,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def test_defaults_are_valid() -> None:
    Config()


@pytest.mark.parametrize(
    "make",
    [
        lambda: Limits(frost_limit=5.0),  # above min_temperature 3
        lambda: Limits(min_temperature=14.5),  # 14.5 + margin 1 >= max 15
        lambda: Limits(override_temperature=0.5),  # below the frost limit
        lambda: Limits(thermostat_band=-1.0),
        lambda: Humidity(target_warm=90.0),  # above target_max 80
        lambda: Humidity(slope=-1.0),
        lambda: Prices(fixed_energy_cost=-1.0),
        lambda: Heaters(power_kw=0.0),
        lambda: ManualRoom(heat_loss_w=25.0),  # without the capacity
        lambda: ManualRoom(heat_loss_w=-25.0, heat_capacity_kwh=0.5),
        lambda: Learning(step_minutes=0),
        lambda: Learning(min_heating_steps=0),
        lambda: Learning(max_relative_error=0.0),
        lambda: Learning(heat_loss_range_w=(100.0, 10.0)),
        lambda: Calibration(heat_minutes=0),
        lambda: Sensors(temperature_range=(10.0, -10.0)),
        lambda: Solver(heat_steps=(0.25, 1.0)),  # no way to not heat
        lambda: Solver(heat_steps=(0.0, 1.5)),
        lambda: Solver(temperature_step=0.0),
        lambda: Solver(soft_penalty=2000.0),  # above the hard penalty
    ],
)
def test_nonsense_is_refused(make: Callable[[], object]) -> None:
    with pytest.raises(ConfigError):
        make()


def test_every_problem_in_a_group_is_reported_at_once() -> None:
    with pytest.raises(ConfigError) as error:
        Solver(temperature_step=0.0, max_overshoot=-1.0)
    assert len(error.value.problems) == 2


def test_a_complete_manual_room_is_fine() -> None:
    assert ManualRoom(heat_loss_w=25.0, heat_capacity_kwh=0.5).is_set
    assert not ManualRoom().is_set


def test_with_groups_swaps_only_the_given_groups() -> None:
    base = Config()
    cfg = base.with_groups(replace(base.humidity, slope=2.0), Heaters(power_kw=0.8))
    assert cfg.humidity.slope == 2.0
    assert cfg.humidity.target_warm == base.humidity.target_warm
    assert cfg.heaters.power_kw == 0.8
    assert cfg.limits == base.limits


def test_with_groups_knows_every_group() -> None:
    base = Config()
    for f in fields(Config):
        group = getattr(base, f.name)
        assert getattr(base.with_groups(group), f.name) is group


def test_learning_window_has_an_upper_limit() -> None:
    Learning(window_days=MAX_WINDOW_DAYS)
    with pytest.raises(ConfigError):
        Learning(window_days=MAX_WINDOW_DAYS + 1)

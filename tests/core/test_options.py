"""Settings a user changes from Home Assistant."""

import pytest

from custom_components.spot_heating_planner.core.config import Config, ConfigError
from custom_components.spot_heating_planner.core.options import (
    SETTINGS,
    config_from_options,
    value,
)


def test_no_options_means_the_defaults() -> None:
    assert config_from_options({}) == Config()


def test_options_land_in_their_groups() -> None:
    cfg = config_from_options({"min_temperature": 5.0, "price_ceiling": 40})
    assert cfg.limits.min_temperature == 5.0
    assert cfg.prices.ceiling == 40.0
    assert cfg.humidity == Config().humidity


def test_contradicting_options_are_refused() -> None:
    with pytest.raises(ConfigError):
        config_from_options({"emergency_temperature": 6.0})  # above the 3 deg C minimum


def test_every_setting_points_at_a_real_field() -> None:
    cfg = Config()
    for setting in SETTINGS:
        assert setting.minimum <= value(cfg, setting) <= setting.maximum, setting.key


def test_keys_are_unique() -> None:
    keys = [s.key for s in SETTINGS]
    assert len(keys) == len(set(keys))

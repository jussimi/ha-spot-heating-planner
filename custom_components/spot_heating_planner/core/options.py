"""The settings a user can change from Home Assistant, and where they go.

Each Setting names one field of one Config group, with the range and step a
number entity offers. A space keeps the user's values in its config entry's
options, by key; everything not set there keeps its default.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from .config import Config

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, kw_only=True)
class Setting:
    """One user-adjustable number."""

    key: str
    """Key in the config entry's options, and the entity's translation key."""

    group: str
    """The Config field holding the group, e.g. "limits"."""

    field: str
    """The field within the group."""

    minimum: float
    maximum: float
    step: float
    unit: str | None


CELSIUS = "°C"
PERCENT = "%"
CENTS_PER_KWH = "c/kWh"

SETTINGS: tuple[Setting, ...] = (
    Setting(key="min_temperature", group="limits", field="min_temperature",
            minimum=-5, maximum=20, step=0.5, unit=CELSIUS),
    Setting(key="max_temperature", group="limits", field="max_temperature",
            minimum=5, maximum=30, step=0.5, unit=CELSIUS),
    Setting(key="frost_limit", group="limits", field="frost_limit",
            minimum=-10, maximum=10, step=0.5, unit=CELSIUS),
    Setting(key="override_temperature", group="limits", field="override_temperature",
            minimum=5, maximum=30, step=0.5, unit=CELSIUS),
    Setting(key="override_hours", group="limits", field="override_hours",
            minimum=1, maximum=24, step=1, unit="h"),
    Setting(key="humidity_target", group="humidity", field="target_warm",
            minimum=40, maximum=90, step=1, unit=PERCENT),
    Setting(key="humidity_target_max", group="humidity", field="target_max",
            minimum=50, maximum=95, step=1, unit=PERCENT),
    Setting(key="dew_point_margin", group="humidity", field="dew_point_margin",
            minimum=0, maximum=10, step=0.5, unit=CELSIUS),
    Setting(key="price_ceiling", group="prices", field="ceiling",
            minimum=0, maximum=200, step=1, unit=CENTS_PER_KWH),
    Setting(key="fixed_energy_cost", group="prices", field="fixed_energy_cost",
            minimum=0, maximum=50, step=0.1, unit=CENTS_PER_KWH),
    Setting(key="heater_power", group="heaters", field="power_kw",
            minimum=0.1, maximum=20, step=0.1, unit="kW"),
)  # fmt: skip
"""Everything a number entity can change, in display order."""


def value(cfg: Config, setting: Setting) -> float:
    """The setting's current value in `cfg`."""
    group = getattr(cfg, setting.group)
    return float(getattr(group, setting.field))


def config_from_options(
    options: Mapping[str, Any], base: Config | None = None
) -> Config:
    """`base` (the defaults if not given) with the user's values applied.

    Raises ConfigError if the values contradict each other.
    """
    base = base or Config()
    changes: dict[str, dict[str, float]] = defaultdict(dict)
    for setting in SETTINGS:
        if setting.key in options:
            changes[setting.group][setting.field] = float(options[setting.key])
    groups = [
        replace(getattr(base, group), **fields) for group, fields in changes.items()
    ]
    return base.with_groups(*groups)

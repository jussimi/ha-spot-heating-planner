"""Every tunable number of the planner, grouped, with its default.

Each group checks its own rules when created. Anything that contradicts
itself raises `ConfigError`, listing every problem at once.
"""

from dataclasses import dataclass, field, replace
from typing import Any

MAX_WINDOW_DAYS = 60
"""Longest learning window: 60 days of 15-minute steps is under 6000 steps."""


class ConfigError(ValueError):
    """Settings that contradict each other or make no physical sense."""

    def __init__(self, problems: list[str]) -> None:
        """List every problem at once, so they can all be fixed together."""
        super().__init__("Invalid settings: " + "; ".join(problems))
        self.problems = problems


def _validate(checks: list[tuple[bool, str]]) -> None:
    """Raise ConfigError with every check that doesn't hold."""
    problems = [message for ok, message in checks if not ok]
    if problems:
        raise ConfigError(problems)


@dataclass(frozen=True, kw_only=True)
class Limits:
    """Temperatures the space is kept between, deg C."""

    min_temperature: float = 3.0
    """The planner keeps the space above this, plus margin."""

    margin: float = 1.0
    """Kept on top of min_temperature: the one explicit safety margin."""

    max_temperature: float = 15.0
    """Never heat above this (an override may aim higher)."""

    override_temperature: float = 15.0
    """Target while a manual override runs."""

    frost_limit: float = 1.0
    """Emergency: below this, heat at any price, until emergency_band above."""

    emergency_band: float = 1.0
    """Emergency heating stops this far above frost_limit."""

    max_temp_band: float = 1.0
    """After reaching the maximum, heat again once this far below it."""

    thermostat_band: float = 1.0
    """While still learning: once heating, continue this far past the lower limit."""

    def __post_init__(self) -> None:
        """Refuse limits in the wrong order."""
        _validate(
            [
                (
                    self.frost_limit < self.min_temperature,
                    "frost_limit must be below min_temperature",
                ),
                (
                    self.min_temperature + self.margin < self.max_temperature,
                    "min_temperature + margin must be below max_temperature",
                ),
                (
                    self.override_temperature > self.frost_limit,
                    "override_temperature must be above frost_limit",
                ),
                (
                    min(
                        self.margin,
                        self.emergency_band,
                        self.max_temp_band,
                        self.thermostat_band,
                    )
                    >= 0,
                    "margin and bands can't be negative",
                ),
            ]
        )


@dataclass(frozen=True, kw_only=True)
class Humidity:
    """Relative humidity limits.

    The target slides up as the space gets colder:
    target(T) = target_warm + slope * (warm_temperature - T),
    clamped between target_warm and target_max.
    docs/physics.md#sliding-humidity-limit
    """

    target_warm: float = 65.0
    """Target (%) at and above warm_temperature."""

    warm_temperature: float = 15.0
    """Deg C."""

    slope: float = 1.0
    """The target rises this many % per deg C colder."""

    target_max: float = 80.0
    """The target never rises above this, %."""

    critical_gap: float = 10.0
    """Critical humidity = target + gap, %."""

    dew_point_margin: float = 2.0
    """Stay this far above the outside dew point, deg C."""

    def __post_init__(self) -> None:
        """Refuse humidity limits that make no sense."""
        _validate(
            [
                (
                    0 < self.target_warm <= self.target_max,
                    "humidity target_warm must be positive and at most target_max",
                ),
                (
                    self.slope >= 0 and self.critical_gap >= 0,
                    "humidity slope and critical_gap can't be negative",
                ),
                (
                    self.dew_point_margin >= 0,
                    "dew_point_margin can't be negative",
                ),
            ]
        )


@dataclass(frozen=True, kw_only=True)
class Prices:
    """Electricity prices, c/kWh incl. VAT."""

    ceiling: float = 30.0
    """Above this spot price, soft wishes wait for a cheaper hour."""

    fixed_energy_cost: float = 8.5
    """Paid per kWh on top of spot: transfer fee, electricity tax, margin."""

    def __post_init__(self) -> None:
        """Refuse a negative fixed cost."""
        _validate(
            [(self.fixed_energy_cost >= 0, "fixed_energy_cost can't be negative")]
        )


@dataclass(frozen=True, kw_only=True)
class Heaters:
    """What heats the space."""

    power_kw: float = 1.0
    """Total draw while on. Used until an energy meter has measured it, and
    always without one."""

    def __post_init__(self) -> None:
        """Refuse a heater that gives no heat."""
        _validate([(self.power_kw > 0, "heater power_kw must be positive")])


@dataclass(frozen=True, kw_only=True)
class ManualRoom:
    """A room set by hand instead of learned. Both values, or neither.

    docs/physics.md#learning
    """

    heat_loss_w: float | None = None
    """UA, W per deg C."""

    heat_capacity_kwh: float | None = None
    """C, kWh per deg C."""

    @property
    def is_set(self) -> bool:
        """Whether the room is set by hand."""
        return self.heat_loss_w is not None and self.heat_capacity_kwh is not None

    def __post_init__(self) -> None:
        """Refuse half a room or negative values."""
        values = (self.heat_loss_w, self.heat_capacity_kwh)
        _validate(
            [
                (
                    values.count(None) in {0, 2},
                    "set both manual heat_loss_w and heat_capacity_kwh, or neither",
                ),
                (
                    all(v is None or v > 0 for v in values),
                    "manual room values must be positive",
                ),
            ]
        )


@dataclass(frozen=True, kw_only=True)
class Learning:
    """Learning the room from logged steps (docs/physics.md#learning)."""

    step_minutes: int = 15
    """Length of one logged step."""

    window_days: float = 14.0
    """Learn from the most recent steps only, to follow the seasons. At most
    MAX_WINDOW_DAYS, which also bounds how many steps are kept."""

    min_heating_steps: int = 4
    """Learning needs at least this many steps with heating."""

    min_coasting_steps: int = 8
    """Learning needs at least this many steps without heating."""

    max_relative_error: float = 0.25
    """Use the learned room once UA and C are known to within this share."""

    outlier_sigma: float = 3.0
    """Drop steps this many robust standard deviations off the fit (a door
    left open, a warm car parked inside)."""

    min_outlier_limit: float = 0.05
    """Never treat a miss smaller than this as an anomaly, deg C."""

    after_anomaly_minutes: int = 30
    """Also drop the steps this long after an anomaly: the air recovers from
    the walls and floor faster than the model expects."""

    max_rounds: int = 5
    """Refit at most this many times while dropping anomalies."""

    heat_loss_range_w: tuple[float, float] = (1.0, 2000.0)
    """Physically plausible UA, W per deg C."""

    heat_capacity_range_kwh: tuple[float, float] = (0.02, 50.0)
    """Physically plausible C, kWh per deg C."""

    def __post_init__(self) -> None:
        """Refuse learning settings that can't work."""
        loss_low, loss_high = self.heat_loss_range_w
        capacity_low, capacity_high = self.heat_capacity_range_kwh
        _validate(
            [
                (
                    self.step_minutes > 0 and 0 < self.window_days <= MAX_WINDOW_DAYS,
                    f"step_minutes must be > 0, window_days 0-{MAX_WINDOW_DAYS}",
                ),
                (
                    self.min_heating_steps > 0 and self.min_coasting_steps > 0,
                    "learning needs at least one heating and one coasting step",
                ),
                (
                    self.max_relative_error > 0 and self.outlier_sigma > 0,
                    "max_relative_error and outlier_sigma must be positive",
                ),
                (
                    self.min_outlier_limit >= 0
                    and self.after_anomaly_minutes >= 0
                    and self.max_rounds > 0,
                    "anomaly settings can't be negative, and max_rounds must be > 0",
                ),
                (
                    0 < loss_low < loss_high and 0 < capacity_low < capacity_high,
                    "learning ranges must be positive and low < high",
                ),
            ]
        )


@dataclass(frozen=True, kw_only=True)
class Calibration:
    """One heat-then-coast run, so learning starts quickly."""

    heat_minutes: int = 60
    """Heat this long at the start of the run."""

    coast_minutes: int = 150
    """Then coast this long without heating."""

    lookahead_hours: int = 12
    """Start the run in the cheapest hour this far ahead."""

    def __post_init__(self) -> None:
        """Refuse a run of no length."""
        _validate(
            [
                (
                    self.heat_minutes > 0
                    and self.coast_minutes > 0
                    and self.lookahead_hours > 0,
                    "calibration times must be positive",
                ),
            ]
        )


@dataclass(frozen=True, kw_only=True)
class Sensors:
    """Sanity limits for sensor readings."""

    temperature_range: tuple[float, float] = (-50.0, 70.0)
    """Readings outside this range are faults, deg C."""

    stuck_heating_minutes: int = 60
    """A temperature that doesn't move through this much heating is stuck."""

    def __post_init__(self) -> None:
        """Refuse an empty range or a zero stuck time."""
        low, high = self.temperature_range
        _validate(
            [
                (
                    low < high and self.stuck_heating_minutes > 0,
                    "sensor range must be low < high, stuck minutes positive",
                ),
            ]
        )


@dataclass(frozen=True, kw_only=True)
class Solver:
    """The planner's internals (docs/physics.md#the-planner)."""

    heat_steps: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
    """Allowed heating per hour, as a share of the hour, from its start."""

    temperature_step: float = 0.1
    """Resolution of the planner's temperature grid, deg C."""

    hard_penalty: float = 1000.0
    """Cents per deg C hour spent below a hard wish."""

    soft_penalty: float = 5.0
    """Cents per deg C hour spent below a soft wish."""

    max_overshoot: float = 0.5
    """Heating may end an hour this far above the upper limit, deg C."""

    def __post_init__(self) -> None:
        """Refuse settings the solver can't work with."""
        _validate(
            [
                (
                    0.0 in self.heat_steps
                    and all(0 <= s <= 1 for s in self.heat_steps),
                    "heat_steps must include 0 and lie between 0 and 1",
                ),
                (self.temperature_step > 0, "temperature_step must be positive"),
                (
                    self.hard_penalty >= self.soft_penalty >= 0,
                    "penalties can't be negative, hard_penalty must be >= soft",
                ),
                (self.max_overshoot >= 0, "max_overshoot can't be negative"),
            ]
        )


@dataclass(frozen=True, kw_only=True)
class Config:
    """Settings for one heated space. Home Assistant may override any of them."""

    limits: Limits = field(default_factory=Limits)
    humidity: Humidity = field(default_factory=Humidity)
    prices: Prices = field(default_factory=Prices)
    heaters: Heaters = field(default_factory=Heaters)
    manual_room: ManualRoom = field(default_factory=ManualRoom)
    learning: Learning = field(default_factory=Learning)
    calibration: Calibration = field(default_factory=Calibration)
    sensors: Sensors = field(default_factory=Sensors)
    solver: Solver = field(default_factory=Solver)

    def with_groups(self, *groups: Group) -> Config:
        """A copy of the config with whole groups swapped in, each by its type.

        Change single settings with dataclasses.replace on the group, which
        type checkers verify field by field:

            cfg.with_groups(replace(cfg.humidity, slope=2.0))
        """
        changes: dict[str, Any] = {_FIELD_FOR_GROUP[type(g)]: g for g in groups}
        return replace(self, **changes)


type Group = (
    Limits
    | Humidity
    | Prices
    | Heaters
    | ManualRoom
    | Learning
    | Calibration
    | Sensors
    | Solver
)

# Which Config field holds each group type (a test checks it covers them all)
_FIELD_FOR_GROUP: dict[type, str] = {
    Limits: "limits",
    Humidity: "humidity",
    Prices: "prices",
    Heaters: "heaters",
    ManualRoom: "manual_room",
    Learning: "learning",
    Calibration: "calibration",
    Sensors: "sensors",
    Solver: "solver",
}

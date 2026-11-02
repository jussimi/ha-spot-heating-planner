"""The hourly plan: the cheapest heating that keeps each hour above its limit.

Every hour of the known price list gets a lower limit, the highest of these
wishes:

    hard  frost               min_temperature + planner_margin
    hard  humidity_critical   warm enough that RH stays below critical
    hard  override            the override target, while it runs
    soft  humidity            warm enough that RH stays below the target
    soft  dew_point           outside dew point + margin

Soft wishes are dropped in hours whose spot price is above the ceiling. For
each hour the planner picks 0-60 minutes of heating, as one block from the
start of the hour, minimising

    electricity cost + penalty per deg C hour spent below a lower limit

Wishes are penalties rather than walls, so there is always a plan.
The optimisation is explained in docs/physics.md#the-planner.

Until the room has been learned, `thermostat` keeps the same wishes with a
plain on/off band instead.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from . import humidity, thermal
from .safety import upper_limit

if TYPE_CHECKING:
    from .config import Config
    from .thermal import HeatedRoom

MINUTES_PER_HOUR = 60
SECONDS_PER_HOUR = 3600
HALF_HOUR = timedelta(minutes=30)
# Ties between choices go to less heating; costs closer than this are a tie
COST_TIE = 1e-9
# Used when there is no outside temperature from any source
NO_OUTSIDE_DATA_T = 0.0


# --- Data ---------------------------------------------------------------------


@dataclass(frozen=True)
class ForecastPoint:
    """One hour of the weather forecast."""

    time: datetime
    temperature: float | None
    dew_point: float | None = None


@dataclass(kw_only=True)
class Inputs:
    """One snapshot of the space and its surroundings."""

    now: datetime

    indoor_temperature: float
    """Indoor temperature, deg C. Without it the safety rules are in charge."""

    indoor_humidity: float | None = None
    """Indoor relative humidity, %."""

    outdoor_temperature: float | None = None
    """Outdoor sensor now, deg C."""

    outdoor_dew_point: float | None = None
    """Outdoor dew point now, deg C."""

    prices: list[tuple[datetime, float]] = field(default_factory=list)
    """(hour start, spot price c/kWh incl. VAT), hourly."""

    forecast: list[ForecastPoint] = field(default_factory=list)
    """Hourly weather forecast."""

    override_until: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class Slot:
    """One hour of the planning window, with everything the planner needs."""

    start: datetime

    length_hours: float
    """1, or what's left of the hour already under way."""

    price: float
    outdoor_temperature: float
    outdoor_dew_point: float | None

    hard: dict[str, float]
    """Hard wishes: name -> lower limit, deg C."""

    soft: dict[str, float]
    """Soft wishes; empty above the price ceiling."""

    hard_lower_limit: float
    """Highest hard wish, capped at the upper limit."""

    soft_lower_limit: float | None
    """Highest soft wish, capped; None without soft wishes."""


@dataclass(frozen=True, kw_only=True)
class HourPlan:
    """What the plan does in one hour."""

    start: datetime

    minutes: int
    """Heating from the start of the hour."""

    price: float
    hard_lower_limit: float
    soft_lower_limit: float | None

    temperature: float
    """Predicted at the end of the hour, deg C."""


@dataclass(frozen=True, kw_only=True)
class Plan:
    """The result: what to do now, why, and the rest of the window."""

    mode: str
    minutes: int
    heat_until: datetime
    humidity_target: float | None
    humidity_critical: float | None

    coasting_hours: float | None
    """Hours the space can go unheated before it cools to min_temperature."""

    target_unreachable: bool
    hours: list[HourPlan]


# --- Wishes and lower limits --------------------------------------------------------


def warm_enough_for_humidity(inp: Inputs, cfg: Config) -> humidity.WarmEnough | None:
    """How warm the space must be for the water its air holds now.

    None without an indoor humidity reading.
    """
    if inp.indoor_humidity is None or inp.indoor_humidity <= 0:
        return None
    dew_point = humidity.dew_point(inp.indoor_temperature, inp.indoor_humidity)
    return humidity.warm_enough(dew_point, cfg.humidity)


def hard_wishes(
    start: datetime, inp: Inputs, dry: humidity.WarmEnough | None, cfg: Config
) -> dict[str, float]:
    """Wishes that hold at any price."""
    wishes = {"frost": cfg.limits.min_temperature + cfg.limits.margin}
    if dry is not None:
        wishes["humidity_critical"] = dry.critical
    if inp.override_until is not None and start < inp.override_until:
        wishes["override"] = cfg.limits.override_temperature
    return wishes


def soft_wishes(
    price: float,
    outdoor_dew_point: float | None,
    dry: humidity.WarmEnough | None,
    cfg: Config,
) -> dict[str, float]:
    """Wishes that wait while the spot price is above the ceiling."""
    if price > cfg.prices.ceiling:
        return {}
    wishes = {}
    if dry is not None:
        wishes["humidity"] = dry.target
    if outdoor_dew_point is not None:
        # Outside air at this dew point would condense on anything colder
        wishes["dew_point"] = outdoor_dew_point + cfg.humidity.dew_point_margin
    return wishes


def highest(wishes: dict[str, float], cap: float) -> float | None:
    """The binding lower limit, capped: aim for the cap when a wish asks for more."""
    if not wishes:
        return None
    return min(max(wishes.values()), cap)


# --- Building the planning window ---------------------------------------------


def hour_start(now: datetime) -> datetime:
    """The start of the hour `now` is in."""
    return now.replace(minute=0, second=0, microsecond=0)


def override_active(inp: Inputs) -> bool:
    """Whether the override runs now."""
    return inp.override_until is not None and inp.now < inp.override_until


def known_prices(inp: Inputs) -> list[tuple[datetime, float]]:
    """(start, price) from the current hour on.

    If the current hour has no price, it gets the average of the rest.
    """
    current = hour_start(inp.now)
    prices = [(s, p) for s, p in sorted(inp.prices) if s >= current]
    if prices and prices[0][0] == current:
        return prices
    average = sum(p for _, p in prices) / len(prices) if prices else 0.0
    return [(current, average), *prices]


def hour_length(start: datetime, now: datetime) -> float:
    """1 hour, or what's left of it if it has already begun."""
    end = start + timedelta(hours=1)
    return min(1.0, (end - max(start, now)).total_seconds() / SECONDS_PER_HOUR)


def forecast_point(start: datetime, inp: Inputs) -> ForecastPoint | None:
    """The forecast for the hour at `start`: the last point up to its middle."""
    earlier = [p for p in inp.forecast if p.time <= start + HALF_HOUR]
    if earlier:
        return earlier[-1]
    return inp.forecast[0] if inp.forecast else None


def outside_conditions(start: datetime, inp: Inputs) -> tuple[float, float | None]:
    """(outside temperature, outside dew point) for the hour at `start`.

    The current hour uses the outdoor sensor, later hours the forecast; each
    stands in for the other when missing.
    """
    point = forecast_point(start, inp)
    forecast_t = point.temperature if point else None
    forecast_dew = point.dew_point if point else None
    if start <= inp.now:
        outdoor_temperature = _first_known(inp.outdoor_temperature, forecast_t)
        dew_point = _first_known(inp.outdoor_dew_point, forecast_dew)
    else:
        outdoor_temperature = _first_known(forecast_t, inp.outdoor_temperature)
        dew_point = _first_known(forecast_dew, inp.outdoor_dew_point)
    temperature = (
        NO_OUTSIDE_DATA_T if outdoor_temperature is None else outdoor_temperature
    )
    return temperature, dew_point


def _first_known(*values: float | None) -> float | None:
    return next((v for v in values if v is not None), None)


def build_slots(inp: Inputs, cfg: Config) -> list[Slot]:
    """One Slot per hour of the known price list."""
    upper = upper_limit(cfg.limits, override_active=override_active(inp))
    dry = warm_enough_for_humidity(inp, cfg)
    slots = []
    for start, price in known_prices(inp):
        outdoor_temperature, outdoor_dew_point = outside_conditions(start, inp)
        hard = hard_wishes(start, inp, dry, cfg)
        soft = soft_wishes(price, outdoor_dew_point, dry, cfg)
        slots.append(
            Slot(
                start=start,
                length_hours=hour_length(start, inp.now),
                price=price,
                outdoor_temperature=outdoor_temperature,
                outdoor_dew_point=outdoor_dew_point,
                hard=hard,
                soft=soft,
                hard_lower_limit=min(max(hard.values()), upper),
                soft_lower_limit=highest(soft, upper),
            )
        )
    return slots


# --- The optimisation: docs/physics.md#the-planner ----------------------------


@dataclass(frozen=True)
class Grid:
    """Temperatures the planner considers, `step` apart."""

    lowest: float
    step: float
    size: int

    def temperature(self, i: int) -> float:
        """The temperature at index i."""
        return self.lowest + i * self.step

    def index(self, temperature: float) -> int:
        """The nearest index to this temperature."""
        offset = round((temperature - self.lowest) / self.step)
        return min(self.size - 1, max(0, offset))


@dataclass(frozen=True)
class Problem:
    """Everything fixed while solving one plan."""

    slots: list[Slot]
    grid: Grid
    upper: float
    cfg: Config
    heated_room: HeatedRoom


def make_problem(inp: Inputs, cfg: Config, heated_room: HeatedRoom) -> Problem:
    """The planning window and a temperature grid wide enough for it.

    The space can't get colder than the coldest outside temperature, nor
    (by the max_overshoot rule) much warmer than the upper limit.
    """
    slots = build_slots(inp, cfg)
    upper = upper_limit(cfg.limits, override_active=override_active(inp))
    lowest = min([inp.indoor_temperature, *(s.outdoor_temperature for s in slots)]) - 1
    highest_t = max(inp.indoor_temperature, upper) + cfg.solver.max_overshoot + 1
    size = int((highest_t - lowest) / cfg.solver.temperature_step) + 1
    grid = Grid(lowest, cfg.solver.temperature_step, size)
    return Problem(slots, grid, upper, cfg, heated_room)


def heating_options(slot: Slot, cfg: Config) -> list[float]:
    """Minutes of heating allowed in this hour, never more than is left of it."""
    minutes_left = slot.length_hours * MINUTES_PER_HOUR
    return sorted(
        {
            min(round(share * MINUTES_PER_HOUR), minutes_left)
            for share in cfg.solver.heat_steps
        }
    )


def hour_cost(slot: Slot, minutes: float, end: float, problem: Problem) -> float:
    """Electricity for the hour plus penalties for ending it below a lower limit, c."""
    cfg = problem.cfg
    kwh = problem.heated_room.heater_power_kw * minutes / MINUTES_PER_HOUR
    cost = (slot.price + cfg.prices.fixed_energy_cost) * kwh
    cost += (
        cfg.solver.hard_penalty
        * max(0.0, slot.hard_lower_limit - end)
        * slot.length_hours
    )
    if slot.soft_lower_limit is not None:
        shortfall = max(0.0, slot.soft_lower_limit - end)
        cost += cfg.solver.soft_penalty * shortfall * slot.length_hours
    return cost


def best_choice(
    start: float, slot: Slot, cost_after: list[float], problem: Problem
) -> tuple[float, float]:
    """(cost, minutes) of the cheapest heating for this hour from temperature `start`.

    `cost_after` is the cost of finishing the window from each grid
    temperature at the end of this hour. Ties go to less heating.
    """
    cfg = problem.cfg
    best_cost, best_minutes = math.inf, 0.0
    for minutes in heating_options(slot, cfg):
        end = thermal.temperature_after(
            start,
            slot.outdoor_temperature,
            slot.length_hours,
            problem.heated_room,
            heating_minutes=minutes,
        )
        if minutes > 0 and end > problem.upper + cfg.solver.max_overshoot:
            continue
        cost = hour_cost(slot, minutes, end, problem)
        cost += cost_after[problem.grid.index(end)]
        if cost < best_cost - COST_TIE:
            best_cost, best_minutes = cost, minutes
    return best_cost, best_minutes


def solve(problem: Problem) -> list[list[float]]:
    """Backwards pass: for each hour, the best minutes from each temperature."""
    grid = problem.grid
    cost_after = [0.0] * grid.size  # nothing to pay after the window
    policy = []
    for slot in reversed(problem.slots):
        choices = [
            best_choice(grid.temperature(i), slot, cost_after, problem)
            for i in range(grid.size)
        ]
        cost_after = [cost for cost, _ in choices]
        policy.append([minutes for _, minutes in choices])
    policy.reverse()
    return policy


def follow(
    indoor_temperature: float, problem: Problem, policy: list[list[float]]
) -> list[HourPlan]:
    """Forwards pass: the plan from the current temperature, hour by hour."""
    planned = []
    for slot, minutes_by_t in zip(problem.slots, policy, strict=True):
        minutes = minutes_by_t[problem.grid.index(indoor_temperature)]
        indoor_temperature = thermal.temperature_after(
            indoor_temperature,
            slot.outdoor_temperature,
            slot.length_hours,
            problem.heated_room,
            heating_minutes=minutes,
        )
        planned.append(
            HourPlan(
                start=slot.start,
                minutes=round(minutes),
                price=slot.price,
                hard_lower_limit=slot.hard_lower_limit,
                soft_lower_limit=slot.soft_lower_limit,
                temperature=round(indoor_temperature, 2),
            )
        )
    return planned


def unreachable(planned: list[HourPlan], inp: Inputs, problem: Problem) -> bool:
    """Whether the plan still leaves a hard wish unmet.

    Also true when critical humidity would need more warmth than allowed.
    """
    step = problem.cfg.solver.temperature_step
    if any(h.temperature < h.hard_lower_limit - step for h in planned):
        return True
    dry = warm_enough_for_humidity(inp, problem.cfg)
    return dry is not None and dry.critical > problem.upper


def humidity_now(inp: Inputs, cfg: Config) -> tuple[float | None, float | None]:
    """(target, critical) humidity at the current indoor temperature."""
    if inp.indoor_humidity is None:
        return None, None
    return humidity.limits(inp.indoor_temperature, cfg.humidity)


def plan_hour(inp: Inputs, cfg: Config, heated_room: HeatedRoom) -> Plan:
    """The cheapest heating plan over the known prices, and what to do now."""
    problem = make_problem(inp, cfg, heated_room)
    planned = follow(inp.indoor_temperature, problem, solve(problem))
    minutes_now = planned[0].minutes
    humidity_target, humidity_critical = humidity_now(inp, cfg)
    outdoor_temperatures = [s.outdoor_temperature for s in problem.slots]
    lower_limit = cfg.limits.min_temperature
    return Plan(
        mode=explain(minutes_now, problem.slots[0], inp, problem),
        minutes=minutes_now,
        heat_until=inp.now + timedelta(minutes=minutes_now),
        humidity_target=humidity_target,
        humidity_critical=humidity_critical,
        coasting_hours=thermal.coasting_hours(
            inp.indoor_temperature, outdoor_temperatures, lower_limit, heated_room
        ),
        target_unreachable=unreachable(planned, inp, problem),
        hours=planned,
    )


# --- Why: the mode shown in Home Assistant ------------------------------------


def explain(minutes: int, slot: Slot, inp: Inputs, problem: Problem) -> str:
    """Why the space is or isn't heating this hour."""
    cfg = problem.cfg
    coasting_end = thermal.temperature_after(
        inp.indoor_temperature,
        slot.outdoor_temperature,
        slot.length_hours,
        problem.heated_room,
    )
    if minutes > 0:
        return _reason_to_heat(slot, coasting_end)
    if slot.price > cfg.prices.ceiling and _soft_wish_waiting(
        slot, inp, coasting_end, cfg
    ):
        return "price_ceiling"
    return "idle"


def _reason_to_heat(slot: Slot, coasting_end: float) -> str:
    """The highest wish coasting would miss, hard wishes first; else preheat."""
    for wishes in (slot.hard, slot.soft):
        missed = {name: limit for name, limit in wishes.items() if coasting_end < limit}
        if missed:
            return max(missed, key=lambda name: missed[name])
    return "preheat"


def _soft_wish_waiting(
    slot: Slot, inp: Inputs, indoor_temperature: float, cfg: Config
) -> bool:
    """Whether a soft wish would have asked for heat at an ordinary price."""
    dry = warm_enough_for_humidity(inp, cfg)
    wishes = soft_wishes(cfg.prices.ceiling, slot.outdoor_dew_point, dry, cfg)
    return any(indoor_temperature < limit for limit in wishes.values())


# --- Before the room is learned: a plain thermostat ----------------------------


@dataclass(frozen=True)
class ThermostatDecision:
    """What the thermostat does this minute, and why."""

    mode: str
    heat: bool


def thermostat(inp: Inputs, cfg: Config, *, heating: bool) -> ThermostatDecision:
    """Heat while below this hour's lower limit; once heating, continue a band past it.

    Used until the room has been learned. It honours the same wishes as the
    planner (soft ones only below the price ceiling) but can't plan ahead.
    """
    slot = build_slots(inp, cfg)[0]
    band = cfg.limits.thermostat_band if heating else 0.0
    for wishes in (slot.hard, slot.soft):
        missed = {n: f for n, f in wishes.items() if inp.indoor_temperature < f + band}
        if missed:
            return ThermostatDecision(max(missed, key=lambda n: missed[n]), heat=True)
    if slot.price > cfg.prices.ceiling and _soft_wish_waiting(
        slot, inp, inp.indoor_temperature, cfg
    ):
        return ThermostatDecision("price_ceiling", heat=False)
    return ThermostatDecision("idle", heat=False)


# --- A summary for the dashboard ------------------------------------------------


CENTS_PER_UNIT = 100.0


@dataclass(frozen=True, kw_only=True)
class HourCost:
    """What one planned hour uses and costs."""

    start: datetime
    energy_kwh: float
    cost: float
    """In currency units (euros, not cents), incl. fixed costs."""


def hour_costs(plan: Plan, heated_room: HeatedRoom, cfg: Config) -> list[HourCost]:
    """Energy and cost of every planned hour, at the heaters' power."""
    costs = []
    for hour in plan.hours:
        energy = heated_room.heater_power_kw * hour.minutes / MINUTES_PER_HOUR
        cents = energy * (hour.price + cfg.prices.fixed_energy_cost)
        costs.append(
            HourCost(start=hour.start, energy_kwh=energy, cost=cents / CENTS_PER_UNIT)
        )
    return costs


@dataclass(frozen=True, kw_only=True)
class PlanSummary:
    """What the plan will do over the coming hours."""

    next_heating: datetime | None
    """Start of the first hour that heats; None if none does."""

    heating_hours: float
    """Hours of heating planned."""

    cost: float
    """Planned cost in currency units (euros, not cents), incl. fixed costs."""


def summarize(
    plan: Plan, heated_room: HeatedRoom, cfg: Config, *, until: datetime
) -> PlanSummary:
    """Totals over the planned hours that start before `until`."""
    heating = [h for h in plan.hours if h.start < until and h.minutes > 0]
    costs = [c for c in hour_costs(plan, heated_room, cfg) if c.start < until]
    return PlanSummary(
        next_heating=heating[0].start if heating else None,
        heating_hours=sum(h.minutes for h in heating) / MINUTES_PER_HOUR,
        cost=sum(c.cost for c in costs),
    )

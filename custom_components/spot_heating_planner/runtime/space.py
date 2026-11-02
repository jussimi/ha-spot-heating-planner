"""One heated space at run time: reads, decides, switches, learns.

Everything runs from a single tick at the start of every minute, in order:

    1. read the sensors into their medians
    2. at a step boundary: close the learning step, learn, open the next one
    3. at the top of the hour (and while waiting for tomorrow's prices):
       fetch prices and the forecast, and plan the hour
    4. decide: safety, calibration, plan or thermostat (core.control)
    5. switch the heaters if the decision changed, and publish the state
    6. count the minute into the learning step

Commands from the entities (override, calibration, new settings) act at
once, outside the tick, without counting a minute.

The decisions themselves live in the core; this module only connects them
to Home Assistant.
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_ON
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_CURRENCY,
    CONF_ENERGY_SENSORS,
    CONF_HEATERS,
    CONF_INDOOR_HUMIDITY,
    CONF_INDOOR_TEMPERATURE,
    CONF_NORDPOOL_AREA,
    CONF_NORDPOOL_ENTRY,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_PRICE_ENTITY,
    CONF_PRICE_FORMAT,
    CONF_PRICE_SOURCE,
    CONF_VAT_PERCENT,
    CONF_WEATHER,
    DOMAIN,
    PRICE_SOURCE_ENTITY,
    PRICE_SOURCE_NORDPOOL_ACTION,
    TOMORROW_PRICES_FROM_HOUR,
)
from ..core import calibration, day_ahead, humidity, learning, safety, sensors
from ..core.control import Decision, decide
from ..core.options import config_from_options
from ..core.planner import (
    HourCost,
    Inputs,
    Plan,
    PlanSummary,
    hour_costs,
    plan_hour,
    summarize,
    thermostat,
)
from ..core.steps import OpenStep, is_boundary
from ..core.thermal import MINUTES_PER_HOUR
from ..sources.forecast import fetch_forecast
from ..sources.prices import (
    FORMATS,
    AttributePrices,
    NordPoolAction,
    PriceSource,
    tomorrow_known,
)
from . import comparisons, readings, statistics
from .storage import Memory, SpaceStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ..core.config import Config
    from ..core.learning import RoomChoice, RoomEstimate
    from ..core.planner import ForecastPoint

LOGGER = logging.getLogger(__name__)
SUMMARY_HOURS = 24
"""The dashboard's planned heating and cost cover this many hours."""
CENTS_PER_UNIT = 100.0
DEFAULT_CURRENCY = "EUR"
COMPARISON_UPDATE_TIME = (0, 30)
"""Update the comparison series every night at 00:30, local time, once Home
Assistant has compiled the last hour's statistics."""
STUCK_CHECK_STEPS = 8
"""How many recent steps the stuck-sensor check looks at (2 hours)."""


# --- What the space is made of ---------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SpaceEntities:
    """The Home Assistant entities one space uses, from its config entry."""

    heaters: list[str]
    energy_sensors: list[str]
    indoor_temperature: str
    indoor_humidity: str | None
    outdoor_temperature: str | None
    outdoor_humidity: str | None
    weather: str | None

    @classmethod
    def from_entry(cls, data: dict[str, Any]) -> SpaceEntities:
        """Read the entities from a config entry's data."""
        return cls(
            heaters=list(data[CONF_HEATERS]),
            energy_sensors=list(data.get(CONF_ENERGY_SENSORS, [])),
            indoor_temperature=data[CONF_INDOOR_TEMPERATURE],
            indoor_humidity=data.get(CONF_INDOOR_HUMIDITY),
            outdoor_temperature=data.get(CONF_OUTDOOR_TEMPERATURE),
            outdoor_humidity=data.get(CONF_OUTDOOR_HUMIDITY),
            weather=data.get(CONF_WEATHER),
        )


def price_source(data: dict[str, Any]) -> PriceSource | None:
    """Where to fetch prices from; None if no price source is set up."""
    vat_percent = float(data.get(CONF_VAT_PERCENT, 0.0))
    kind = data.get(CONF_PRICE_SOURCE)
    if kind == PRICE_SOURCE_NORDPOOL_ACTION:
        return NordPoolAction(
            config_entry_id=data[CONF_NORDPOOL_ENTRY],
            area=data[CONF_NORDPOOL_AREA],
            currency=data[CONF_CURRENCY],
            vat_percent=vat_percent,
        )
    if kind == PRICE_SOURCE_ENTITY:
        return AttributePrices(
            entity_id=data[CONF_PRICE_ENTITY],
            price_format=FORMATS[data[CONF_PRICE_FORMAT]],
            vat_percent=vat_percent,
        )
    return None


@dataclass(frozen=True, kw_only=True)
class SpaceState:
    """A snapshot of the space for its entities."""

    decision: Decision
    room: RoomChoice
    estimate: RoomEstimate | None
    plan: Plan | None
    calibration: calibration.Phase | None
    override_until: datetime | None
    indoor_temperature: float | None
    indoor_humidity: float | None
    sensor_stuck: bool
    enabled: bool
    cost_total: float
    energy_total: float
    price_now: float | None
    """This hour's spot price, c/kWh incl. VAT."""
    energy_price_now: float | None
    """This hour's spot price plus the fixed costs: what a kWh costs now."""
    prices: list[tuple[datetime, float]]
    """The known hourly prices from this hour on."""
    hour_costs: list[HourCost]
    """Planned energy and cost of each hour in the plan."""
    summary: PlanSummary | None
    """The plan over the next SUMMARY_HOURS, once the room is known."""


@dataclass
class _Smoothing:
    """The medians of every sensor the space reads."""

    indoor_temperature: readings.Smoothed = field(default_factory=readings.Smoothed)
    indoor_humidity: readings.Smoothed = field(default_factory=readings.Smoothed)
    outdoor_temperature: readings.Smoothed = field(default_factory=readings.Smoothed)
    outdoor_humidity: readings.Smoothed = field(default_factory=readings.Smoothed)


# --- The runtime ------------------------------------------------------------


class Space(DataUpdateCoordinator[SpaceState]):
    """Runs one space; its entities follow it as a coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[Any],
        *,
        cfg: Config | None = None,
    ) -> None:
        """Set up from a config entry; nothing runs until `async_start`."""
        super().__init__(
            hass, LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}"
        )
        self.entities = SpaceEntities.from_entry(dict(entry.data))
        self.prices_from = price_source(dict(entry.data))
        self.entry = entry
        self.cfg = cfg or config_from_options(entry.options)
        self._store = SpaceStore(hass, entry.entry_id)
        self._memory = Memory()
        self._smoothing = _Smoothing()
        self._safety = safety.SafetyState()
        self._estimate: RoomEstimate | None = None
        self._prices: list[tuple[datetime, float]] = []
        self._forecast: list[ForecastPoint] = []
        self._plan: Plan | None = None
        self._step: OpenStep | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._last_energy: float | None = None
        self._comparison_task: asyncio.Task[None] | None = None
        self._heating = False

    # --- Lifecycle --------------------------------------------------------------------

    async def async_start(self) -> None:
        """Load what was learned, then run the first tick and every minute after."""
        now = dt_util.utcnow()
        self._memory = await self._store.load()
        self._memory.samples = learning.recent(self._memory.samples, now, self.cfg)
        self._learn()
        await self._refresh_outside_data(now)
        if not self._memory.samples and self._room().heated_room is None:
            self._schedule_calibration(now)
        await self.async_tick(now)
        self._unsubscribe = async_track_time_change(
            self.hass, self._on_minute, second=0
        )
        self._schedule_comparison_update()

    async def async_stop(self) -> None:
        """Stop ticking and updating, and save straight away."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._comparison_task is not None and not self._comparison_task.done():
            self._comparison_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._comparison_task
        await self._store.save_now(self._memory)

    @callback
    def _on_minute(self, now: datetime) -> None:
        self.hass.async_create_task(self.async_tick(now), eager_start=True)

    # --- Commands from the entities ---------------------------------------------------

    async def async_start_override(self, hours: float | None = None) -> None:
        """Hold the override temperature for `hours` (the setting if not given)."""
        now = dt_util.utcnow()
        length = self.cfg.limits.override_hours if hours is None else hours
        self._memory.override_until = now + timedelta(hours=length)
        self._store.save_soon(self._memory)
        await self._replan(now)
        await self._act(now)

    async def async_cancel_override(self) -> None:
        """End a running override."""
        now = dt_util.utcnow()
        self._memory.override_until = None
        self._store.save_soon(self._memory)
        await self._replan(now)
        await self._act(now)

    async def async_start_calibration(self) -> None:
        """Run a calibration in the cheapest hour ahead."""
        now = dt_util.utcnow()
        self._schedule_calibration(now)
        await self._act(now)

    async def async_set_option(self, key: str, value: float) -> None:
        """Change one setting and keep it in the config entry's options.

        Raises ConfigError, leaving everything as it was, if the new value
        contradicts the other settings.
        """
        options = {**self.entry.options, key: value}
        cfg = config_from_options(options)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        await self.async_set_config(cfg)

    async def async_set_enabled(self, *, enabled: bool) -> None:
        """Pause or resume switching the heaters; planning goes on either way."""
        self._memory.enabled = enabled
        self._store.save_soon(self._memory)
        await self._act(dt_util.utcnow())

    async def async_set_config(self, cfg: Config) -> None:
        """New settings: relearn with them and plan again."""
        now = dt_util.utcnow()
        comparisons_changed = cfg.comparison != self.cfg.comparison
        self.cfg = cfg
        self._learn()
        await self._replan(now)
        await self._act(now)
        if comparisons_changed:
            self._schedule_comparison_update()

    # --- The tick ---------------------------------------------------------------------

    async def async_tick(self, now: datetime) -> None:
        """Everything that happens at the start of a minute, in order."""
        self._read_sensors(now)
        if is_boundary(now, self.cfg.learning.step_minutes):
            self._close_step(now)
        if now.minute == 0:
            self._record_day_ahead(now)
        if _is_comparison_update_time(now):
            self._schedule_comparison_update()
        if self._is_planning_time(now):
            await self._refresh_outside_data(now)
            await self._replan(now)
        elif self._plan is None and self._room().heated_room is not None:
            await self._replan(now)
        self._take_day_ahead(now)

        self._count_energy(now)
        decision = await self._act(now)
        self._count_minute(now, heating=decision.heat)

    async def _act(self, now: datetime) -> Decision:
        """Decide, switch the heaters to match, and publish the new state.

        While paused, nothing is switched; the decision is still shown.
        """
        decision = self._decide(now)
        if self._memory.enabled:
            await self._switch_heaters(heat=decision.heat)
        self._heating = self._heaters_on()
        self.async_set_updated_data(self._snapshot(decision, now))
        return decision

    def _is_planning_time(self, now: datetime) -> bool:
        """At the top of each hour, and every step while tomorrow is missing."""
        if now.minute == 0:
            return True
        waiting_for_tomorrow = dt_util.as_local(
            now
        ).hour >= TOMORROW_PRICES_FROM_HOUR and not tomorrow_known(self._prices, now)
        return waiting_for_tomorrow and is_boundary(now, self.cfg.learning.step_minutes)

    # --- Reading ----------------------------------------------------------------------

    def _read_sensors(self, now: datetime) -> None:
        """Add this minute's readings to the medians.

        Read every minute rather than on change, so a steady sensor keeps its
        median filled.
        """
        states = self.hass.states
        e, s = self.entities, self._smoothing
        s.indoor_temperature.add(
            now, readings.temperature(states.get(e.indoor_temperature))
        )
        if e.indoor_humidity is not None:
            s.indoor_humidity.add(now, readings.number(states.get(e.indoor_humidity)))
        if e.outdoor_temperature is not None:
            outdoor = readings.temperature(states.get(e.outdoor_temperature))
            s.outdoor_temperature.add(now, outdoor)
        if e.outdoor_humidity is not None:
            s.outdoor_humidity.add(now, readings.number(states.get(e.outdoor_humidity)))

    def _indoor_temperature(self, now: datetime) -> float | None:
        """Smoothed and plausible; None if missing, impossible or stuck."""
        value = self._smoothing.indoor_temperature.value(now)
        value = sensors.plausible_temperature(value, self.cfg.sensors)
        return None if self._sensor_stuck() else value

    def _sensor_stuck(self) -> bool:
        recent = self._memory.samples[-STUCK_CHECK_STEPS:]
        return sensors.stuck_while_heating(recent, self.cfg.sensors)

    def _outdoor_temperature(self, now: datetime) -> float | None:
        value = self._smoothing.outdoor_temperature.value(now)
        return sensors.plausible_temperature(value, self.cfg.sensors)

    def _outdoor_dew_point(self, now: datetime) -> float | None:
        outdoor = self._outdoor_temperature(now)
        relative = sensors.plausible_humidity(
            self._smoothing.outdoor_humidity.value(now)
        )
        if outdoor is None or relative is None:
            return None
        return humidity.dew_point(outdoor, relative)

    def _inputs(self, now: datetime, indoor_temperature: float) -> Inputs:
        indoor_humidity = self._smoothing.indoor_humidity.value(now)
        return Inputs(
            now=now,
            indoor_temperature=indoor_temperature,
            indoor_humidity=sensors.plausible_humidity(indoor_humidity),
            outdoor_temperature=self._outdoor_temperature(now),
            outdoor_dew_point=self._outdoor_dew_point(now),
            prices=self._prices,
            forecast=self._forecast,
            override_until=self._override_until(now),
        )

    def _override_until(self, now: datetime) -> datetime | None:
        """When a running override ends; None if none runs (expired ones too)."""
        until = self._memory.override_until
        return until if until is not None and now < until else None

    # --- Learning ---------------------------------------------------------------------

    def _close_step(self, now: datetime) -> None:
        """Finish the step under way, learn from it, and open the next one."""
        if self._step is not None:
            sample = self._step.close(
                now,
                indoor_temperature_end=self._indoor_temperature(now),
                energy_end_kwh=self._energy(),
            )
            if sample is not None:
                kept = learning.recent([*self._memory.samples, sample], now, self.cfg)
                self._memory.samples = kept
                self._store.save_soon(self._memory)
                self._learn()
        self._step = self._open_step(now)

    def _open_step(self, now: datetime) -> OpenStep | None:
        indoor = self._indoor_temperature(now)
        if indoor is None:
            return None
        return OpenStep(
            start=now, indoor_temperature_start=indoor, energy_start_kwh=self._energy()
        )

    def _count_minute(self, now: datetime, *, heating: bool) -> None:
        if self._step is not None:
            outdoor = self._outdoor_temperature(now)
            self._step.add_minute(heating=heating, outdoor_temperature=outdoor)

    def _energy(self) -> float | None:
        if not self.entities.energy_sensors:
            return None
        return readings.total_energy(self.hass, self.entities.energy_sensors)

    def _learn(self) -> None:
        self._estimate = learning.estimate(self._memory.samples, self.cfg)

    def _room(self) -> RoomChoice:
        return learning.choose(self.cfg, self._estimate)

    # --- Prices, forecast and the plan ------------------------------------------------

    async def _refresh_outside_data(self, now: datetime) -> None:
        if self.prices_from is not None:
            self._prices = await self.prices_from.fetch(self.hass, now)
        if self.entities.weather is not None:
            self._forecast = await fetch_forecast(self.hass, self.entities.weather)

    async def _replan(self, now: datetime) -> None:
        """Plan the rest of this hour again, if the room is known."""
        heated_room = self._room().heated_room
        indoor = self._indoor_temperature(now)
        if heated_room is None or indoor is None:
            self._plan = None
            return
        inputs = self._inputs(now, indoor)
        self._plan = await self.hass.async_add_executor_job(
            plan_hour, inputs, self.cfg, heated_room
        )

    # --- Calibration ------------------------------------------------------------------

    def _schedule_calibration(self, now: datetime) -> None:
        start = calibration.best_start(self._prices, now, self.cfg.calibration)
        self._memory.calibration_start = start
        self._store.save_soon(self._memory)

    def _calibration_phase(self, now: datetime) -> calibration.Phase | None:
        """The run's phase; a finished run is forgotten."""
        start = self._memory.calibration_start
        if start is None:
            return None
        phase = calibration.phase(now, start, self.cfg.calibration)
        if phase is calibration.Phase.DONE:
            self._memory.calibration_start = None
            self._store.save_soon(self._memory)
            return None
        return phase

    # --- Deciding and switching -------------------------------------------------------

    def _decide(self, now: datetime) -> Decision:
        indoor = self._indoor_temperature(now)
        override_active = self._override_until(now) is not None
        rule = safety.check(
            indoor, self._safety, self.cfg.limits, override_active=override_active
        )
        if indoor is None:
            # Without the indoor temperature the safety rules always decide
            assert rule is not None  # noqa: S101 - safety.check guarantees it
            return Decision(rule.mode, heat=rule.heat)
        fallback = thermostat(
            self._inputs(now, indoor), self.cfg, heating=self._heaters_on()
        )
        return decide(
            now,
            safety=rule,
            calibration=self._calibration_phase(now),
            plan=self._plan,
            thermostat=fallback,
        )

    def _heaters_on(self) -> bool:
        return any(
            self.hass.states.is_state(heater, STATE_ON)
            for heater in self.entities.heaters
        )

    async def _switch_heaters(self, *, heat: bool) -> None:
        """Turn every heater on or off, only those not already there."""
        action = "turn_on" if heat else "turn_off"
        for heater in self.entities.heaters:
            if self.hass.states.is_state(heater, STATE_ON) == heat:
                continue
            domain = heater.split(".", 1)[0]
            await self.hass.services.async_call(
                domain, action, target={"entity_id": heater}, blocking=True
            )

    # --- The comparison series -------------------------------------------------------

    async def async_update_comparisons(self) -> None:
        """Bring the comparison and metered-cost series up to date."""
        await comparisons.update(self)

    @property
    def memory(self) -> Memory:
        """What the space keeps across restarts."""
        return self._memory

    def save_soon(self) -> None:
        """Save the memory within a minute."""
        self._store.save_soon(self._memory)

    def _schedule_comparison_update(self) -> None:
        """Update in the background; reading history takes a moment."""
        if self._comparison_task is not None and not self._comparison_task.done():
            return
        self._comparison_task = self.hass.async_create_background_task(
            self.async_update_comparisons(), name=f"{DOMAIN} comparisons"
        )

    # --- The day-ahead forecast -------------------------------------------------------

    def _take_day_ahead(self, now: datetime) -> None:
        """Once tomorrow's prices are known, keep tomorrow's plan as forecast."""
        heated_room = self._room().heated_room
        if self._plan is None or heated_room is None:
            return
        if not tomorrow_known(self._prices, now):
            return
        tomorrow_start = dt_util.start_of_local_day(now) + timedelta(days=1)
        tomorrow = dt_util.as_local(tomorrow_start).date().isoformat()
        if self._memory.day_ahead_date == tomorrow:
            return
        costs = hour_costs(self._plan, heated_room, self.cfg)
        hours = day_ahead.snapshot(
            self._plan,
            costs,
            start=tomorrow_start,
            end=tomorrow_start + timedelta(days=1),
        )
        self._memory.day_ahead = [
            h for h in self._memory.day_ahead if h.start < tomorrow_start
        ] + hours
        self._memory.day_ahead_date = tomorrow
        self._store.save_soon(self._memory)

    def _record_day_ahead(self, now: datetime) -> None:
        """Write the forecast of the hour that just ended into the statistics."""
        ended = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        memory = self._memory
        forecast = next((h for h in memory.day_ahead if h.start == ended), None)
        memory.day_ahead = [h for h in memory.day_ahead if h.start > ended]
        if forecast is None:
            return
        memory.day_ahead_energy_total += forecast.energy_kwh
        memory.day_ahead_cost_total += forecast.cost
        self._store.save_soon(memory)
        start = forecast.start
        for series, hour in (
            (
                statistics.DAY_AHEAD_ENERGY,
                statistics.Hour(
                    start=start,
                    value=forecast.energy_kwh,
                    total=memory.day_ahead_energy_total,
                ),
            ),
            (
                statistics.day_ahead_cost(self.currency),
                statistics.Hour(
                    start=start, value=forecast.cost, total=memory.day_ahead_cost_total
                ),
            ),
            (
                statistics.DAY_AHEAD_TEMPERATURE,
                statistics.Hour(start=start, value=forecast.temperature),
            ),
        ):
            statistics.write_hour(self.hass, self.entry, series, hour)

    @property
    def currency(self) -> str:
        """The currency the space's costs are in."""
        return str(self.entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY))

    # --- Cost -------------------------------------------------------------------------

    def _count_energy(self, now: datetime) -> None:
        """Add the minute that just ended to the heating energy and cost.

        Measured energy if there are meters, else the heaters' power while they
        were on; priced at this hour's spot price plus the fixed costs.
        """
        energy_now = self._energy()
        if energy_now is not None:
            # A meter: its change since the last minute (none on the first
            # reading, and none across a counter reset)
            last = self._last_energy
            kwh = 0.0 if last is None else max(0.0, energy_now - last)
        elif self._heating:
            kwh = self._heater_power() / MINUTES_PER_HOUR
        else:
            kwh = 0.0
        self._last_energy = energy_now
        if kwh <= 0:
            return
        self._memory.energy_total += kwh
        self._store.save_soon(self._memory)
        price = self._price_at(now)
        if price is not None:
            cents = kwh * (price + self.cfg.prices.fixed_energy_cost)
            self._memory.cost_total += cents / CENTS_PER_UNIT

    def _heater_power(self) -> float:
        estimate = self._estimate
        if estimate is not None:
            return estimate.heated_room.heater_power_kw
        return self.cfg.heaters.power_kw

    def _energy_price_at(self, now: datetime) -> float | None:
        price = self._price_at(now)
        return None if price is None else price + self.cfg.prices.fixed_energy_cost

    def _price_at(self, now: datetime) -> float | None:
        hour = now.replace(minute=0, second=0, microsecond=0)
        return next((p for start, p in self._prices if start == hour), None)

    def _hour_costs(self) -> list[HourCost]:
        heated_room = self._room().heated_room
        if self._plan is None or heated_room is None:
            return []
        return hour_costs(self._plan, heated_room, self.cfg)

    def _summary(self, now: datetime) -> PlanSummary | None:
        heated_room = self._room().heated_room
        if self._plan is None or heated_room is None:
            return None
        until = now + timedelta(hours=SUMMARY_HOURS)
        return summarize(self._plan, heated_room, self.cfg, until=until)

    def _snapshot(self, decision: Decision, now: datetime) -> SpaceState:
        return SpaceState(
            decision=decision,
            room=self._room(),
            estimate=self._estimate,
            plan=self._plan,
            calibration=self._calibration_phase(now),
            override_until=self._override_until(now),
            indoor_temperature=self._indoor_temperature(now),
            indoor_humidity=self._smoothing.indoor_humidity.value(now),
            sensor_stuck=self._sensor_stuck(),
            enabled=self._memory.enabled,
            cost_total=self._memory.cost_total,
            energy_total=self._memory.energy_total,
            price_now=self._price_at(now),
            energy_price_now=self._energy_price_at(now),
            prices=self._prices,
            hour_costs=self._hour_costs(),
            summary=self._summary(now),
        )


def _is_comparison_update_time(now: datetime) -> bool:
    local = dt_util.as_local(now)
    return (local.hour, local.minute) == COMPARISON_UPDATE_TIME

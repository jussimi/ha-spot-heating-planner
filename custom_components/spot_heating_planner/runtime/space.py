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
from ..core import calibration, humidity, learning, safety, sensors
from ..core.config import Config
from ..core.control import Decision, decide
from ..core.planner import Inputs, Plan, plan_hour, thermostat
from ..core.steps import OpenStep, is_boundary
from ..sources.forecast import fetch_forecast
from ..sources.prices import (
    FORMATS,
    AttributePrices,
    NordPoolAction,
    PriceSource,
    tomorrow_known,
)
from . import readings
from .storage import Memory, SpaceStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ..core.learning import RoomChoice, RoomEstimate
    from ..core.planner import ForecastPoint

LOGGER = logging.getLogger(__name__)
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
        self.cfg = cfg or Config()
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

    # --- Lifecycle ----------------------------------------------------------

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

    async def async_stop(self) -> None:
        """Stop ticking and save straight away."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        await self._store.save_now(self._memory)

    @callback
    def _on_minute(self, now: datetime) -> None:
        self.hass.async_create_task(self.async_tick(now), eager_start=True)

    # --- Commands from the entities ------------------------------------------

    async def async_start_override(self, hours: float) -> None:
        """Hold the override temperature for `hours` from now."""
        now = dt_util.utcnow()
        self._memory.override_until = now + timedelta(hours=hours)
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

    async def async_set_config(self, cfg: Config) -> None:
        """New settings: relearn with them and plan again."""
        now = dt_util.utcnow()
        self.cfg = cfg
        self._learn()
        await self._replan(now)
        await self._act(now)

    # --- The tick -------------------------------------------------------------

    async def async_tick(self, now: datetime) -> None:
        """Everything that happens at the start of a minute, in order."""
        self._read_sensors(now)
        if is_boundary(now, self.cfg.learning.step_minutes):
            self._close_step(now)
        if self._is_planning_time(now):
            await self._refresh_outside_data(now)
            await self._replan(now)
        elif self._plan is None and self._room().heated_room is not None:
            await self._replan(now)

        decision = await self._act(now)
        self._count_minute(now, heating=decision.heat)

    async def _act(self, now: datetime) -> Decision:
        """Decide, switch the heaters to match, and publish the new state."""
        decision = self._decide(now)
        await self._switch_heaters(heat=decision.heat)
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

    # --- Reading ----------------------------------------------------------------

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

    # --- Learning ------------------------------------------------------------

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

    # --- Prices, forecast and the plan -----------------------------------------

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

    # --- Calibration -------------------------------------------------------------

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

    # --- Deciding and switching ----------------------------------------------------

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
        )

"""One heated space at run time, against a fake Home Assistant setup."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spot_heating_planner.const import (
    CONF_CURRENCY,
    CONF_ENERGY_SENSORS,
    CONF_HEATERS,
    CONF_INDOOR_HUMIDITY,
    CONF_INDOOR_TEMPERATURE,
    CONF_NORDPOOL_AREA,
    CONF_NORDPOOL_ENTRY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_PRICE_ENTITY,
    CONF_PRICE_FORMAT,
    CONF_PRICE_SOURCE,
    CONF_VAT_PERCENT,
    DOMAIN,
    PRICE_SOURCE_ENTITY,
    PRICE_SOURCE_NORDPOOL_ACTION,
)
from custom_components.spot_heating_planner.core.config import Config, ManualRoom
from custom_components.spot_heating_planner.runtime.space import Space, price_source
from custom_components.spot_heating_planner.sources.prices import (
    FORMATS,
    AttributePrices,
    NordPoolAction,
)

HEATER = "switch.heater"
ENERGY = "sensor.heater_energy"
INDOOR = "sensor.indoor_temperature"
INDOOR_HUMIDITY = "sensor.indoor_humidity"
OUTDOOR = "sensor.outdoor_temperature"
# A known room, so tests that need the planner don't wait for learning
KNOWN_ROOM = ManualRoom(heat_loss_w=25.0, heat_capacity_kwh=0.56)


def set_temperatures(hass: HomeAssistant, *, indoor: str, outdoor: str = "-10") -> None:
    hass.states.async_set(INDOOR, indoor, {"unit_of_measurement": "°C"})
    hass.states.async_set(OUTDOOR, outdoor, {"unit_of_measurement": "°C"})


def fake_switch(hass: HomeAssistant) -> list[str]:
    """A switch whose turn_on/turn_off just change its state; logs the calls."""
    calls: list[str] = []

    async def turn(call: ServiceCall) -> None:
        calls.append(call.service)
        state = STATE_ON if call.service == "turn_on" else STATE_OFF
        entity_ids = call.data["entity_id"]
        for entity_id in [entity_ids] if isinstance(entity_ids, str) else entity_ids:
            hass.states.async_set(entity_id, state)

    hass.states.async_set(HEATER, STATE_OFF)
    hass.services.async_register("switch", "turn_on", turn)
    hass.services.async_register("switch", "turn_off", turn)
    return calls


def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garage",
        data={
            CONF_HEATERS: [HEATER],
            CONF_ENERGY_SENSORS: [ENERGY],
            CONF_INDOOR_TEMPERATURE: INDOOR,
            CONF_INDOOR_HUMIDITY: INDOOR_HUMIDITY,
            CONF_OUTDOOR_TEMPERATURE: OUTDOOR,
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def switch_calls(hass: HomeAssistant) -> list[str]:
    set_temperatures(hass, indoor="8")
    hass.states.async_set(ENERGY, "100.0", {"unit_of_measurement": "kWh"})
    return fake_switch(hass)


async def started(hass: HomeAssistant, cfg: Config | None = None) -> Space:
    space = Space(hass, config_entry(hass), cfg=cfg)
    await space.async_start()
    return space


@pytest.fixture
async def space(hass: HomeAssistant, switch_calls: list[str]) -> AsyncIterator[Space]:
    """A fresh space: nothing learned yet."""
    del switch_calls
    running = await started(hass)
    yield running
    await running.async_stop()


@pytest.fixture
async def known_space(
    hass: HomeAssistant, switch_calls: list[str]
) -> AsyncIterator[Space]:
    """A space whose room is set by hand, so it plans from the start."""
    del switch_calls
    running = await started(hass, Config(manual_room=KNOWN_ROOM))
    yield running
    await running.async_stop()


def state_of(entry: MockConfigEntry) -> ConfigEntryState:
    """The entry's state, read fresh (keeps mypy from assuming it can't change)."""
    state: ConfigEntryState = entry.state
    return state


def heater_is_on(hass: HomeAssistant) -> bool:
    return hass.states.is_state(HEATER, STATE_ON)


def minutes_later(minutes: int) -> datetime:
    return dt_util.utcnow() + timedelta(minutes=minutes)


# --- A fresh install -----------------------------------------------------------


async def test_a_fresh_space_starts_by_calibrating(
    hass: HomeAssistant, space: Space
) -> None:
    assert space.data.decision.mode == "calibrating"
    assert heater_is_on(hass)


async def test_calibration_coasts_after_its_hour(
    hass: HomeAssistant, space: Space
) -> None:
    await space.async_tick(minutes_later(90))
    assert space.data.decision.mode == "calibrating"
    assert not heater_is_on(hass)


async def test_thermostat_takes_over_after_calibration(
    hass: HomeAssistant, space: Space
) -> None:
    set_temperatures(hass, indoor="3.5")
    later = minutes_later(4 * 60)
    for minute in range(30):  # let the median follow the new reading
        await space.async_tick(later + timedelta(minutes=minute))
    assert space.data.room.status == "learning"
    assert space.data.decision.mode == "frost"
    assert heater_is_on(hass)


# --- Safety ----------------------------------------------------------------------


async def test_lost_indoor_sensor_heats(hass: HomeAssistant, space: Space) -> None:
    hass.states.async_set(INDOOR, "unavailable")
    await space.async_tick(minutes_later(40))  # past the median window
    assert space.data.decision.mode == "sensor_fault"
    assert heater_is_on(hass)


async def test_frost_emergency_heats(hass: HomeAssistant, known_space: Space) -> None:
    set_temperatures(hass, indoor="0.5")
    later = minutes_later(31)
    for minute in range(31):
        await known_space.async_tick(later + timedelta(minutes=minute))
    assert known_space.data.decision.mode == "emergency"
    assert heater_is_on(hass)


# --- Planning ---------------------------------------------------------------------


async def test_known_room_plans_from_the_start(known_space: Space) -> None:
    assert known_space.data.room.status == "manual"
    assert known_space.data.plan is not None
    assert known_space.data.calibration is None  # nothing to calibrate


async def test_override_heats_to_its_target(
    hass: HomeAssistant, known_space: Space
) -> None:
    await known_space.async_start_override(3)
    assert known_space.data.decision.mode == "override"
    assert heater_is_on(hass)
    await known_space.async_cancel_override()
    assert known_space.data.override_until is None
    assert known_space.data.decision.mode != "override"


async def test_new_settings_replan(known_space: Space) -> None:
    warmer = replace(known_space.cfg.limits, min_temperature=12.0)
    await known_space.async_set_config(known_space.cfg.with_groups(warmer))
    assert known_space.data.decision.mode == "frost"


# --- Learning ---------------------------------------------------------------------


async def test_a_full_step_is_logged(hass: HomeAssistant, space: Space) -> None:
    start = dt_util.utcnow().replace(second=0, microsecond=0)
    boundary = start + timedelta(minutes=15 - start.minute % 15)
    for minute in range(16):
        await space.async_tick(boundary + timedelta(minutes=minute))
    assert len(space._memory.samples) == 1  # noqa: SLF001 - checking what was logged
    sample = space._memory.samples[0]  # noqa: SLF001
    assert sample.minutes == 15
    assert sample.outdoor_temperature == -10.0
    del hass


# --- Setting up through Home Assistant -------------------------------------------


async def test_sets_up_and_unloads(
    hass: HomeAssistant, switch_calls: list[str]
) -> None:
    entry = config_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert state_of(entry) is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, Space)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert state_of(entry) is ConfigEntryState.NOT_LOADED
    assert "turn_on" in switch_calls  # it calibrated while it ran


# --- Choosing the price source ------------------------------------------------------


def test_price_source_from_the_setup() -> None:
    nordpool = price_source(
        {
            CONF_PRICE_SOURCE: PRICE_SOURCE_NORDPOOL_ACTION,
            CONF_NORDPOOL_ENTRY: "nordpool-entry",
            CONF_NORDPOOL_AREA: "FI",
            CONF_CURRENCY: "EUR",
            CONF_VAT_PERCENT: 25.5,
        }
    )
    entity = price_source(
        {
            CONF_PRICE_SOURCE: PRICE_SOURCE_ENTITY,
            CONF_PRICE_ENTITY: "sensor.spot_price_forecast",
            CONF_PRICE_FORMAT: "spot_heating_planner",
        }
    )
    assert isinstance(nordpool, NordPoolAction)
    assert nordpool.vat_percent == 25.5
    assert isinstance(entity, AttributePrices)
    assert entity.price_format is FORMATS["spot_heating_planner"]
    assert price_source({}) is None

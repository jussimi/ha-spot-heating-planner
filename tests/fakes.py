"""A fake Home Assistant setup for one space: heater, sensors, prices."""

from datetime import timedelta
from typing import Any

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
    CONF_OUTDOOR_TEMPERATURE,
    CONF_PRICE_ENTITY,
    CONF_PRICE_FORMAT,
    CONF_PRICE_SOURCE,
    DOMAIN,
    PRICE_SOURCE_ENTITY,
)
from custom_components.spot_heating_planner.core.config import ManualRoom

HEATER = "input_boolean.heater"
"""An input_boolean: the switch domain is taken by the space's own switch."""
ENERGY = "sensor.heater_energy"
INDOOR = "sensor.indoor_temperature"
INDOOR_HUMIDITY = "sensor.indoor_humidity"
OUTDOOR = "sensor.outdoor_temperature"
# A known room, so tests that need the planner don't wait for learning
KNOWN_ROOM = ManualRoom(heat_loss_w=25.0, heat_capacity_kwh=0.56)


def set_temperatures(hass: HomeAssistant, *, indoor: str, outdoor: str = "-10") -> None:
    hass.states.async_set(INDOOR, indoor, {"unit_of_measurement": "°C"})
    hass.states.async_set(OUTDOOR, outdoor, {"unit_of_measurement": "°C"})


def fake_heater(hass: HomeAssistant) -> list[str]:
    """A heater whose turn_on/turn_off just change its state; logs the calls."""
    calls: list[str] = []

    async def turn(call: ServiceCall) -> None:
        calls.append(call.service)
        state = STATE_ON if call.service == "turn_on" else STATE_OFF
        entity_ids = call.data["entity_id"]
        for entity_id in [entity_ids] if isinstance(entity_ids, str) else entity_ids:
            hass.states.async_set(entity_id, state)

    hass.states.async_set(HEATER, STATE_OFF)
    hass.services.async_register("input_boolean", "turn_on", turn)
    hass.services.async_register("input_boolean", "turn_off", turn)
    return calls


PRICES = "sensor.spot_price_forecast"


def config_entry(
    hass: HomeAssistant, *, options: dict[str, Any] | None = None
) -> MockConfigEntry:
    """A space using the fake entities, with prices from PRICES."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garage",
        data={
            CONF_HEATERS: [HEATER],
            CONF_ENERGY_SENSORS: [ENERGY],
            CONF_INDOOR_TEMPERATURE: INDOOR,
            CONF_INDOOR_HUMIDITY: INDOOR_HUMIDITY,
            CONF_OUTDOOR_TEMPERATURE: OUTDOOR,
            CONF_PRICE_SOURCE: PRICE_SOURCE_ENTITY,
            CONF_PRICE_ENTITY: PRICES,
            CONF_PRICE_FORMAT: "spot_heating_planner",
            CONF_CURRENCY: "EUR",
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


def set_prices(hass: HomeAssistant, cents: list[float]) -> None:
    """Hourly prices from the current hour, in this integration's own format."""
    hour = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    forecast = [
        {"start": (hour + timedelta(hours=h)).isoformat(), "price": p}
        for h, p in enumerate(cents)
    ]
    hass.states.async_set(PRICES, str(cents[0]), {"forecast": forecast})


def set_energy(hass: HomeAssistant, kwh: float) -> None:
    hass.states.async_set(ENERGY, str(kwh), {"unit_of_measurement": "kWh"})


def fake_space(hass: HomeAssistant) -> list[str]:
    """Readings, prices and a heater for one space; returns the switch calls."""
    set_temperatures(hass, indoor="8")
    set_energy(hass, 100.0)
    set_prices(hass, [10.0] * 48)
    return fake_heater(hass)


def recent_step() -> dict[str, Any]:
    """One stored learning step, so a space doesn't start by calibrating."""
    return {
        "start": (dt_util.utcnow() - timedelta(hours=1)).isoformat(),
        "minutes": 15,
        "indoor_temperature_start": 8.0,
        "indoor_temperature_end": 8.0,
        "outdoor_temperature": -10.0,
        "heat_share": 0.0,
        "energy_kwh": 0.0,
    }

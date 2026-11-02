"""The entities of a space, set up through Home Assistant."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spot_heating_planner.const import DOMAIN
from tests.fakes import HEATER, config_entry, fake_space, recent_step


@pytest.fixture
async def garage(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> AsyncIterator[MockConfigEntry]:
    """A space that has logged a step already, so it doesn't calibrate."""
    fake_space(hass)
    entry = config_entry(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "data": {"samples": [recent_step()]},
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    assert await hass.config_entries.async_unload(entry.entry_id)


def state(hass: HomeAssistant, entity_id: str) -> str:
    current = hass.states.get(entity_id)
    assert current is not None, entity_id
    return current.state


async def press(hass: HomeAssistant, button: str) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": button}, blocking=True
    )


async def test_entities_are_created(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    del garage
    assert state(hass, "sensor.garage_mode") == "idle"  # 8 deg C, dry
    assert state(hass, "sensor.garage_room_model") == "learning"
    assert state(hass, "binary_sensor.garage_heating") == STATE_OFF
    assert state(hass, "switch.garage_control_heaters") == STATE_ON
    assert state(hass, "number.garage_minimum_temperature") == "3.0"
    assert state(hass, "sensor.garage_heating_cost") == "0.0"


async def test_mode_carries_the_humidity_limits(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    del garage
    mode = hass.states.get("sensor.garage_mode")
    assert mode is not None
    assert "plan" in mode.attributes


async def test_a_setting_is_kept_and_used(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.garage_minimum_temperature", "value": 9.0},
        blocking=True,
    )
    assert garage.options["min_temperature"] == 9.0
    assert state(hass, "sensor.garage_mode") == "frost"  # 8 deg C is now too cold
    assert state(hass, HEATER) == STATE_ON


async def test_a_contradicting_setting_is_refused(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.garage_frost_limit", "value": 8.0},
            blocking=True,
        )
    assert "frost_limit" not in garage.options


async def test_override_button_heats(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    del garage
    await press(hass, "button.garage_start_override")
    assert state(hass, "sensor.garage_mode") == "override"
    assert state(hass, HEATER) == STATE_ON
    await press(hass, "button.garage_cancel_override")
    assert state(hass, "sensor.garage_mode") == "idle"
    assert state(hass, HEATER) == STATE_OFF


async def test_control_switch_pauses(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    del garage
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.garage_control_heaters"},
        blocking=True,
    )
    await press(hass, "button.garage_start_override")
    assert state(hass, "sensor.garage_mode") == "override"
    assert state(hass, HEATER) == STATE_OFF  # paused: left alone


async def test_spot_price_shows_the_hour_and_the_known_prices(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    del garage
    price = hass.states.get("sensor.garage_spot_price")
    assert price is not None
    assert float(price.state) == 10.0  # the fake price list
    forecast = price.attributes["forecast"]
    assert forecast[0]["price"] == 10.0
    assert {"start", "price"} <= set(forecast[0])


async def test_heating_energy_starts_at_zero(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    del garage
    assert state(hass, "sensor.garage_heating_energy") == "0.0"

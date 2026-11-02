"""Setting up a space from the UI."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spot_heating_planner.const import (
    CONF_CURRENCY,
    CONF_HEATERS,
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

SPACE = {
    "name": "Garage",
    CONF_HEATERS: ["switch.heater"],
    CONF_INDOOR_TEMPERATURE: "sensor.indoor_temperature",
    CONF_OUTDOOR_TEMPERATURE: "sensor.outdoor_temperature",
}


async def start(hass: HomeAssistant) -> str:
    """Fill in the first step; returns the flow id at the prices step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], SPACE)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "prices"
    return str(result["flow_id"])


async def test_space_with_nord_pool_prices(hass: HomeAssistant) -> None:
    nordpool = MockConfigEntry(domain="nordpool", title="Nord Pool")
    nordpool.add_to_hass(hass)
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PRICE_SOURCE: PRICE_SOURCE_NORDPOOL_ACTION}
    )
    assert result["step_id"] == "nordpool"
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_NORDPOOL_ENTRY: nordpool.entry_id,
            CONF_NORDPOOL_AREA: "FI",
            CONF_CURRENCY: "EUR",
            CONF_VAT_PERCENT: 25.5,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Garage"
    data = result["data"]
    assert data[CONF_PRICE_SOURCE] == PRICE_SOURCE_NORDPOOL_ACTION
    assert data[CONF_NORDPOOL_AREA] == "FI"
    assert data[CONF_HEATERS] == ["switch.heater"]
    assert "name" not in data


async def test_space_with_a_price_entity(hass: HomeAssistant) -> None:
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PRICE_SOURCE: PRICE_SOURCE_ENTITY}
    )
    assert result["step_id"] == "price_entity"
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_PRICE_ENTITY: "sensor.spot_price_forecast",
            CONF_PRICE_FORMAT: "spot_heating_planner",
            CONF_VAT_PERCENT: 0,
            CONF_CURRENCY: "EUR",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PRICE_FORMAT] == "spot_heating_planner"


async def test_space_without_prices(hass: HomeAssistant) -> None:
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PRICE_SOURCE: "none"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_PRICE_SOURCE not in result["data"]

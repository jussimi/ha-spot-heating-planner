"""Setting up a space from the UI."""

from typing import Any

import probatio
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType
from homeassistant.helpers import config_validation as cv
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
from tests.fakes import config_entry

SPACE = {
    "name": "Garage",
    CONF_HEATERS: ["switch.heater"],
    CONF_INDOOR_TEMPERATURE: "sensor.indoor_temperature",
    CONF_OUTDOOR_TEMPERATURE: "sensor.outdoor_temperature",
}


def form_fields(result: FlowResult[Any, Any]) -> list[dict[str, Any]]:
    """A form's fields as the frontend gets them."""
    fields = probatio.to_field_list(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )
    return [field for field in fields if isinstance(field, dict)]


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


async def test_the_nord_pool_entry_is_chosen_for_you(hass: HomeAssistant) -> None:
    nordpool = MockConfigEntry(domain="nordpool", title="Nord Pool")
    nordpool.add_to_hass(hass)
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PRICE_SOURCE: PRICE_SOURCE_NORDPOOL_ACTION}
    )
    defaults = {field["name"]: field.get("default") for field in form_fields(result)}
    assert defaults[CONF_NORDPOOL_ENTRY] == nordpool.entry_id


async def test_nord_pool_without_the_integration_stops(hass: HomeAssistant) -> None:
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PRICE_SOURCE: PRICE_SOURCE_NORDPOOL_ACTION}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nordpool_missing"


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


# --- Reconfiguring -------------------------------------------------------------------


async def test_reconfigure_changes_the_setup_and_keeps_the_entry(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garage",
        data={
            CONF_HEATERS: ["switch.heater"],
            CONF_INDOOR_TEMPERATURE: "sensor.indoor_temperature",
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    changed = {**SPACE, "name": "Workshop", CONF_HEATERS: ["switch.new_heater"]}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], changed)
    assert result["step_id"] == "prices"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRICE_SOURCE: "none"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Workshop"
    assert entry.data[CONF_HEATERS] == ["switch.new_heater"]
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reconfigure_fills_in_the_current_answers(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garage",
        data={
            CONF_HEATERS: ["switch.heater"],
            CONF_INDOOR_TEMPERATURE: "sensor.indoor_temperature",
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    schema = result["data_schema"]
    suggested = {
        str(key): key.description.get("suggested_value")
        for key in schema.schema
        if key.description
    }
    assert suggested["name"] == "Garage"
    assert suggested[CONF_HEATERS] == ["switch.heater"]


# --- Forms the frontend can show ------------------------------------------------------

PREFILLED_SELECTORS = {"boolean", "entity", "number", "object", "select", "text"}
"""Selectors the frontend can give a starting value: a required field of any
other kind (a config entry, say) needs a default, or the form doesn't show.
From get-selector-initial-value.ts in home-assistant/frontend."""


def unshowable_fields(result: FlowResult[Any, Any]) -> list[str]:
    """A form's required fields that have no starting value in the frontend."""
    return [
        field["name"]
        for field in form_fields(result)
        if field.get("required")
        and "default" not in field
        and (field.get("description") or {}).get("suggested_value") is None
        and next(iter(field["selector"])) not in PREFILLED_SELECTORS
    ]


async def test_every_form_can_be_shown(hass: HomeAssistant) -> None:
    MockConfigEntry(domain="nordpool", title="Nord Pool").add_to_hass(hass)
    forms = []
    for source in (PRICE_SOURCE_NORDPOOL_ACTION, PRICE_SOURCE_ENTITY):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        forms.append(result)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], SPACE
        )
        forms.append(result)
        forms.append(
            await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_PRICE_SOURCE: source}
            )
        )
    entry = config_entry(hass)
    forms.append(await entry.start_reconfigure_flow(hass))
    forms.append(await hass.config_entries.options.async_init(entry.entry_id))

    assert {form["step_id"] for form in forms} == {
        "user",
        "prices",
        "nordpool",
        "price_entity",
        "reconfigure",
        "init",
    }
    for form in forms:
        assert unshowable_fields(form) == [], form["step_id"]

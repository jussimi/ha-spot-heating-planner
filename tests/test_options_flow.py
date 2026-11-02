"""Choosing the comparison thermostats."""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.spot_heating_planner.core.options import COMPARISON_TEMPERATURES
from tests.fakes import config_entry


async def test_temperatures_are_kept_sorted_and_unique(hass: HomeAssistant) -> None:
    entry = config_entry(hass, options={"min_temperature": 4.0})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {COMPARISON_TEMPERATURES: ["10", "4.5", "10"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[COMPARISON_TEMPERATURES] == [4.5, 10.0]
    assert entry.options["min_temperature"] == 4.0  # other settings are kept


async def test_nonsense_temperatures_are_refused(hass: HomeAssistant) -> None:
    entry = config_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {COMPARISON_TEMPERATURES: ["warm"]}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_temperatures"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {COMPARISON_TEMPERATURES: ["99"]}
    )
    assert result["errors"] == {"base": "invalid_temperatures"}

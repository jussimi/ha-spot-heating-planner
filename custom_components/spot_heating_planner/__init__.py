"""Spot Heating Planner: frost and moisture protection heating on spot prices.

Each config entry is one heated space. Its `Space` runs the planner every
minute and its entities (added in a later part) follow it.
"""

from typing import TYPE_CHECKING

from .runtime.space import Space

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant

type SpotHeatingConfigEntry = ConfigEntry[Space]

PLATFORMS: list[Platform] = []


async def async_setup_entry(hass: HomeAssistant, entry: SpotHeatingConfigEntry) -> bool:
    """Start the space and its entities."""
    space = Space(hass, entry)
    await space.async_start()
    entry.runtime_data = space
    entry.async_on_unload(space.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SpotHeatingConfigEntry
) -> bool:
    """Stop the space; `async_on_unload` saves its memory."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

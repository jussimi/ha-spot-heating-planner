"""Spot Heating Planner: frost and moisture protection heating on spot prices.

Each config entry is one heated space. Its `Space` runs the planner every
minute and its entities follow it.
"""

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

from . import services
from .const import DOMAIN
from .runtime.space import Space

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

type SpotHeatingConfigEntry = ConfigEntry[Space]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions, which every space shares."""
    del config
    services.async_register(hass)
    return True


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

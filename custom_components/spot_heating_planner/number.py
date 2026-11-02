"""Number entities: the settings a user can change, kept in the entry's options."""

from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .core.config import ConfigError
from .core.options import SETTINGS, Setting, value
from .entity import SpaceEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SpotHeatingConfigEntry
    from .runtime.space import Space


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpotHeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One number per setting in core.options.SETTINGS."""
    del hass
    space = entry.runtime_data
    async_add_entities(SettingNumber(space, setting) for setting in SETTINGS)


class SettingNumber(SpaceEntity, NumberEntity):
    """One setting; changing it replans at once."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, space: Space, setting: Setting) -> None:
        """Range, step and unit come from the setting."""
        super().__init__(space, setting.key)
        self.setting = setting
        self._attr_native_min_value = setting.minimum
        self._attr_native_max_value = setting.maximum
        self._attr_native_step = setting.step
        self._attr_native_unit_of_measurement = setting.unit

    @property
    def native_value(self) -> float:
        """The value the space is using now."""
        return value(self.coordinator.cfg, self.setting)

    async def async_set_native_value(self, value: float) -> None:
        """Keep the new value, unless it contradicts the other settings."""
        try:
            await self.coordinator.async_set_option(self.setting.key, value)
        except ConfigError as error:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_setting",
                translation_placeholders={"problems": "; ".join(error.problems)},
            ) from error

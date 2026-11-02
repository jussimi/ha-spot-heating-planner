"""Switch: whether the space controls its heaters, or only plans."""

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .entity import SpaceEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SpotHeatingConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpotHeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """The control switch."""
    del hass
    async_add_entities([ControlSwitch(entry.runtime_data, "control")])


class ControlSwitch(SpaceEntity, SwitchEntity):
    """On: the space switches its heaters. Off: it only plans and shows why."""

    @property
    def is_on(self) -> bool:
        """Whether the space is switching its heaters."""
        return self.coordinator.data.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ANN401 - HA's API
        """Resume control."""
        del kwargs
        await self.coordinator.async_set_enabled(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ANN401 - HA's API
        """Pause control; the heaters stay as they are."""
        del kwargs
        await self.coordinator.async_set_enabled(enabled=False)

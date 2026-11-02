"""Buttons: start or cancel an override, and run a calibration."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from .entity import SpaceEntity

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SpotHeatingConfigEntry
    from .runtime.space import Space


@dataclass(frozen=True, kw_only=True)
class SpaceButtonDescription(ButtonEntityDescription):
    """A button and what it asks the space to do."""

    press: Callable[[Space], Awaitable[None]]


BUTTONS: tuple[SpaceButtonDescription, ...] = (
    SpaceButtonDescription(
        key="start_override", press=lambda space: space.async_start_override()
    ),
    SpaceButtonDescription(
        key="cancel_override", press=lambda space: space.async_cancel_override()
    ),
    SpaceButtonDescription(
        key="calibrate", press=lambda space: space.async_start_calibration()
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpotHeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One of each button for the space."""
    del hass
    space = entry.runtime_data
    async_add_entities(SpaceButton(space, d) for d in BUTTONS)


class SpaceButton(SpaceEntity, ButtonEntity):
    """A button that asks the space to do something."""

    entity_description: SpaceButtonDescription

    def __init__(self, space: Space, description: SpaceButtonDescription) -> None:
        """Describe it."""
        super().__init__(space, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Ask the space."""
        await self.entity_description.press(self.coordinator)

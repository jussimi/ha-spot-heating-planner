"""Binary sensors: whether the space is heating, and whether it can't keep up."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass

from .entity import SpaceEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SpotHeatingConfigEntry
    from .runtime.space import Space, SpaceState


@dataclass(frozen=True, kw_only=True)
class SpaceBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor and how to read it from the space's state."""

    is_on: Callable[[SpaceState], bool]


BINARY_SENSORS: tuple[SpaceBinarySensorDescription, ...] = (
    SpaceBinarySensorDescription(
        key="heating",
        device_class=BinarySensorDeviceClass.HEAT,
        is_on=lambda s: s.decision.heat,
    ),
    SpaceBinarySensorDescription(
        key="target_unreachable",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on=lambda s: bool(s.plan and s.plan.target_unreachable),
    ),
    SpaceBinarySensorDescription(
        key="sensor_stuck",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on=lambda s: s.sensor_stuck,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpotHeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One of each binary sensor for the space."""
    del hass
    space = entry.runtime_data
    async_add_entities(SpaceBinarySensor(space, d) for d in BINARY_SENSORS)


class SpaceBinarySensor(SpaceEntity, BinarySensorEntity):
    """A binary sensor reading the space's state."""

    entity_description: SpaceBinarySensorDescription

    def __init__(self, space: Space, description: SpaceBinarySensorDescription) -> None:
        """Describe it."""
        super().__init__(space, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """From the latest state."""
        return self.entity_description.is_on(self.coordinator.data)

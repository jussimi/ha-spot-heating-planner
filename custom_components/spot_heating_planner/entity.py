"""What every entity of a space shares: its device and its coordinator."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .runtime.space import Space


class SpaceEntity(CoordinatorEntity[Space]):
    """An entity of one space, updated whenever the space ticks."""

    _attr_has_entity_name = True

    def __init__(self, space: Space, key: str) -> None:
        """Name it by `key` (its translation key) under the space's device."""
        super().__init__(space)
        entry = space.entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Spot Heating Planner",
        )

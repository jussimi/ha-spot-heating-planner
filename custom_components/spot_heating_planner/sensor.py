"""Sensors: why the space is heating, the plan, its cost, and the learned room."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)

from .const import CONF_CURRENCY
from .core.thermal import WATTS_PER_KW
from .entity import SpaceEntity

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SpotHeatingConfigEntry
    from .runtime.space import Space, SpaceState

DEFAULT_CURRENCY = "EUR"

MODES = [
    "sensor_fault",
    "emergency",
    "max_temp",
    "calibrating",
    "override",
    "minimum",
    "humidity_critical",
    "humidity",
    "dew_point",
    "preheat",
    "price_ceiling",
    "idle",
]
"""Every reason the mode sensor can show, for its enum device class."""

ROOM_STATUSES = ["learning", "learned", "manual"]


@dataclass(frozen=True, kw_only=True)
class SpaceSensorDescription(SensorEntityDescription):
    """A sensor and how to read its value from the space's state."""

    value: Callable[[SpaceState], float | str | datetime | None]


def _room_value(read: Callable[[Any], float]) -> Callable[[SpaceState], float | None]:
    """Read from the space's room, once there is one."""

    def value(state: SpaceState) -> float | None:
        heated_room = state.room.heated_room
        return None if heated_room is None else read(heated_room)

    return value


SENSORS: tuple[SpaceSensorDescription, ...] = (
    SpaceSensorDescription(
        key="mode",
        device_class=SensorDeviceClass.ENUM,
        options=MODES,
        value=lambda s: s.decision.mode,
    ),
    SpaceSensorDescription(
        key="next_heating",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda s: s.summary.next_heating if s.summary else None,
    ),
    SpaceSensorDescription(
        key="planned_heating",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        suggested_display_precision=1,
        value=lambda s: s.summary.heating_hours if s.summary else None,
    ),
    SpaceSensorDescription(
        key="planned_cost",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value=lambda s: s.summary.cost if s.summary else None,
    ),
    SpaceSensorDescription(
        key="spot_price",
        native_unit_of_measurement="c/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value=lambda s: s.price_now,
    ),
    SpaceSensorDescription(
        key="energy_price",
        native_unit_of_measurement="c/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value=lambda s: s.energy_price_now,
    ),
    SpaceSensorDescription(
        key="heating_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value=lambda s: s.energy_total,
    ),
    SpaceSensorDescription(
        key="heating_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value=lambda s: s.cost_total,
    ),
    SpaceSensorDescription(
        key="coasting_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        suggested_display_precision=1,
        value=lambda s: s.plan.coasting_hours if s.plan else None,
    ),
    SpaceSensorDescription(
        key="room_status",
        device_class=SensorDeviceClass.ENUM,
        options=ROOM_STATUSES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.room.status,
    ),
    SpaceSensorDescription(
        key="heat_loss",
        native_unit_of_measurement="W/°C",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_room_value(lambda r: r.room.heat_loss_kw * WATTS_PER_KW),
    ),
    SpaceSensorDescription(
        key="heat_capacity",
        native_unit_of_measurement="kWh/°C",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_room_value(lambda r: r.room.heat_capacity_kwh),
    ),
    SpaceSensorDescription(
        key="max_rise",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_room_value(lambda r: r.max_rise),
    ),
    SpaceSensorDescription(
        key="half_life",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_room_value(lambda r: r.half_life_hours),
    ),
    SpaceSensorDescription(
        key="heater_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_room_value(lambda r: r.heater_power_kw * WATTS_PER_KW),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpotHeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One of each sensor for the space."""
    del hass
    space = entry.runtime_data
    async_add_entities(SpaceSensor(space, description) for description in SENSORS)


class SpaceSensor(SpaceEntity, SensorEntity):
    """A sensor reading one value from the space's state."""

    entity_description: SpaceSensorDescription

    def __init__(self, space: Space, description: SpaceSensorDescription) -> None:
        """Describe it; money sensors take the space's currency."""
        super().__init__(space, description.key)
        self.entity_description = description
        if description.device_class is SensorDeviceClass.MONETARY:
            currency = space.entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            self._attr_native_unit_of_measurement = currency

    @property
    def native_value(self) -> float | str | datetime | None:
        """The value from the latest state."""
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The mode carries the plan, the spot price the known prices."""
        key = self.entity_description.key
        if key == "mode":
            return plan_attributes(self.coordinator.data)
        if key == "spot_price":
            return price_attributes(self.coordinator.data)
        return None


def plan_attributes(state: SpaceState) -> dict[str, Any]:
    """The plan hour by hour, and the humidity limits, in plain values.

    Each hour: heating minutes, spot price, predicted indoor temperature at
    its end, and the planned energy (kWh) and cost (incl. fixed costs).
    """
    plan = state.plan
    costs = {c.start: c for c in state.hour_costs}
    hours = []
    for hour in plan.hours if plan else []:
        cost = costs.get(hour.start)
        hours.append(
            {
                "start": hour.start.isoformat(),
                "minutes": hour.minutes,
                "price": hour.price,
                "temperature": hour.temperature,
                "energy_kwh": round(cost.energy_kwh, 3) if cost else None,
                "cost": round(cost.cost, 4) if cost else None,
            }
        )
    return {
        "humidity_target": plan.humidity_target if plan else None,
        "humidity_critical": plan.humidity_critical if plan else None,
        "override_until": state.override_until,
        "plan": hours,
    }


def price_attributes(state: SpaceState) -> dict[str, Any]:
    """The known hourly prices, in this integration's own price format."""
    return {
        "forecast": [
            {"start": start.isoformat(), "price": round(price, 3)}
            for start, price in state.prices
        ]
    }

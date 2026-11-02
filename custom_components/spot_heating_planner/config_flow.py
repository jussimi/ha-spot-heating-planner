"""Setting up a space from the UI.

Three short steps:

    user     the space: its name, heaters and sensors
    prices   where spot prices come from (or none)
    nordpool / price_entity   the details of that source

The settings (temperatures, humidity, prices) aren't asked here; they start
at their defaults and are changed afterwards from the space's number
entities.
"""

from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import (
    ConfigEntrySelector,
    ConfigEntrySelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    EntityWithDeviceFilterSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)

from .const import (
    CONF_CURRENCY,
    CONF_ENERGY_SENSORS,
    CONF_HEATERS,
    CONF_INDOOR_HUMIDITY,
    CONF_INDOOR_TEMPERATURE,
    CONF_NORDPOOL_AREA,
    CONF_NORDPOOL_ENTRY,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_PRICE_ENTITY,
    CONF_PRICE_FORMAT,
    CONF_PRICE_SOURCE,
    CONF_VAT_PERCENT,
    CONF_WEATHER,
    DOMAIN,
    PRICE_SOURCE_ENTITY,
    PRICE_SOURCE_NORDPOOL_ACTION,
)
from .sources.prices import FORMATS

if TYPE_CHECKING:
    from collections.abc import Mapping

PRICE_SOURCE_NONE = "none"
DEFAULT_CURRENCY = "EUR"
DEFAULT_VAT_PERCENT = 25.5
SWITCHABLE = ["switch", "input_boolean", "light", "fan"]
MAX_VAT_PERCENT = 50


def _entity(
    domain: str | list[str], device_class: str | None = None, *, multiple: bool = False
) -> EntitySelector:
    """An entity picker for one kind of entity."""
    entity_filter = EntityWithDeviceFilterSelectorConfig(domain=domain)
    if device_class is not None:
        entity_filter["device_class"] = device_class
    return EntitySelector(EntitySelectorConfig(filter=entity_filter, multiple=multiple))


def _vat() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=MAX_VAT_PERCENT,
            step=0.1,
            unit_of_measurement="%",
            mode=NumberSelectorMode.BOX,
        )
    )


SPACE_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_NAME): TextSelector(),
        probatio.Required(CONF_HEATERS): _entity(SWITCHABLE, multiple=True),
        probatio.Required(CONF_INDOOR_TEMPERATURE): _entity("sensor", "temperature"),
        probatio.Optional(CONF_INDOOR_HUMIDITY): _entity("sensor", "humidity"),
        probatio.Optional(CONF_OUTDOOR_TEMPERATURE): _entity("sensor", "temperature"),
        probatio.Optional(CONF_OUTDOOR_HUMIDITY): _entity("sensor", "humidity"),
        probatio.Optional(CONF_ENERGY_SENSORS): _entity(
            "sensor", "energy", multiple=True
        ),
        probatio.Optional(CONF_WEATHER): _entity("weather"),
    }
)

PRICES_SCHEMA = probatio.Schema(
    {
        probatio.Required(
            CONF_PRICE_SOURCE, default=PRICE_SOURCE_NORDPOOL_ACTION
        ): SelectSelector(
            SelectSelectorConfig(
                options=[
                    PRICE_SOURCE_NORDPOOL_ACTION,
                    PRICE_SOURCE_ENTITY,
                    PRICE_SOURCE_NONE,
                ],
                translation_key=CONF_PRICE_SOURCE,
            )
        ),
    }
)

NORDPOOL_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_NORDPOOL_ENTRY): ConfigEntrySelector(
            ConfigEntrySelectorConfig(integration="nordpool")
        ),
        probatio.Required(CONF_NORDPOOL_AREA): TextSelector(),
        probatio.Required(CONF_CURRENCY, default=DEFAULT_CURRENCY): TextSelector(),
        probatio.Required(CONF_VAT_PERCENT, default=DEFAULT_VAT_PERCENT): _vat(),
    }
)

PRICE_ENTITY_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_PRICE_ENTITY): _entity("sensor"),
        probatio.Required(CONF_PRICE_FORMAT): SelectSelector(
            SelectSelectorConfig(
                options=list(FORMATS), translation_key=CONF_PRICE_FORMAT
            )
        ),
        probatio.Required(CONF_VAT_PERCENT, default=0.0): _vat(),
        probatio.Required(CONF_CURRENCY, default=DEFAULT_CURRENCY): TextSelector(),
    }
)


class SpotHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one space."""

    VERSION = 1

    def __init__(self) -> None:
        """Collect the answers of every step before creating the entry."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The space: its name, heaters and sensors."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=SPACE_SCHEMA)
        self._data.update(user_input)
        return await self.async_step_prices()

    async def async_step_prices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Where spot prices come from."""
        if user_input is None:
            return self.async_show_form(step_id="prices", data_schema=PRICES_SCHEMA)
        source = user_input[CONF_PRICE_SOURCE]
        if source == PRICE_SOURCE_NORDPOOL_ACTION:
            return await self.async_step_nordpool()
        if source == PRICE_SOURCE_ENTITY:
            return await self.async_step_price_entity()
        return self._create()

    async def async_step_nordpool(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The official Nord Pool integration: which entry and area."""
        if user_input is None:
            return self.async_show_form(step_id="nordpool", data_schema=NORDPOOL_SCHEMA)
        return self._create(
            {CONF_PRICE_SOURCE: PRICE_SOURCE_NORDPOOL_ACTION, **user_input}
        )

    async def async_step_price_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """An entity with a price list, and its format."""
        if user_input is None:
            return self.async_show_form(
                step_id="price_entity", data_schema=PRICE_ENTITY_SCHEMA
            )
        return self._create({CONF_PRICE_SOURCE: PRICE_SOURCE_ENTITY, **user_input})

    def _create(self, prices: Mapping[str, Any] | None = None) -> ConfigFlowResult:
        data = {**self._data, **(prices or {})}
        title = data.pop(CONF_NAME)
        return self.async_create_entry(title=title, data=data)

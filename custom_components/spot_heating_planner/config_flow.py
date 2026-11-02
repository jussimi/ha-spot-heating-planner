"""Setting up a space from the UI.

Three short steps:

    user     the space: its name, heaters and sensors
             (reconfigure: the same, filled in, to change)
    prices   where spot prices come from (or none)
    nordpool / price_entity   the details of that source

The settings (temperatures, humidity, prices) aren't asked here; they start
at their defaults and are changed afterwards from the space's number
entities.
"""

from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
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
from .core.config import Comparison, ConfigError
from .core.options import COMPARISON_TEMPERATURES, config_from_options
from .sources.prices import FORMATS

if TYPE_CHECKING:
    from collections.abc import Mapping

PRICE_SOURCE_NONE = "none"
DEFAULT_CURRENCY = "EUR"
DEFAULT_VAT_PERCENT = 25.5
SWITCHABLE = ["switch", "input_boolean", "light", "fan"]
MAX_VAT_PERCENT = 50
NORDPOOL = "nordpool"
NORDPOOL_AREAS = "areas"


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


def _nordpool_schema(entries: list[ConfigEntry]) -> probatio.Schema:
    """The Nord Pool step, with the first entry, its first area and currency chosen.

    The entry picker needs a default: the frontend can't make up a starting
    value for a config entry, and shows no form at all. The areas are those
    the Nord Pool entries fetch.
    """
    first = entries[0]
    fields: dict[probatio.Marker, Any] = {
        probatio.Required(
            CONF_NORDPOOL_ENTRY, default=first.entry_id
        ): ConfigEntrySelector(ConfigEntrySelectorConfig(integration=NORDPOOL))
    }
    if areas := _nordpool_areas(entries):
        fields[probatio.Required(CONF_NORDPOOL_AREA, default=areas[0])] = (
            SelectSelector(SelectSelectorConfig(options=areas))
        )
    else:  # entries that don't list their areas: type one in
        fields[probatio.Required(CONF_NORDPOOL_AREA)] = TextSelector()
    currency = first.data.get(CONF_CURRENCY, DEFAULT_CURRENCY)
    fields[probatio.Required(CONF_CURRENCY, default=currency)] = TextSelector()
    fields[probatio.Required(CONF_VAT_PERCENT, default=DEFAULT_VAT_PERCENT)] = _vat()
    return probatio.Schema(fields)


def _nordpool_areas(entries: list[ConfigEntry]) -> list[str]:
    """The price areas the Nord Pool entries fetch, each once, in order."""
    areas = (area for entry in entries for area in entry.data.get(NORDPOOL_AREAS, []))
    return list(dict.fromkeys(areas))


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
    """Set up one space, or change one that exists (reconfigure).

    Reconfiguring walks the same steps with the current answers filled in,
    and keeps the entry: what the space has learned is stored under the
    entry's id, so nothing is lost.
    """

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """The options: which plain thermostats to compare with."""
        del config_entry
        return SpotHeatingOptionsFlow()

    def __init__(self) -> None:
        """Collect the answers of every step before creating the entry."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The space: its name, heaters and sensors."""
        if user_input is None:
            return self._form("user", SPACE_SCHEMA)
        self._data.update(user_input)
        return await self.async_step_prices()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The space's current setup, to change."""
        if user_input is None:
            return self._form("reconfigure", SPACE_SCHEMA)
        self._data.update(user_input)
        return await self.async_step_prices()

    async def async_step_prices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Where spot prices come from."""
        if user_input is None:
            return self._form("prices", PRICES_SCHEMA)
        source = user_input[CONF_PRICE_SOURCE]
        if source == PRICE_SOURCE_NORDPOOL_ACTION:
            return await self.async_step_nordpool()
        if source == PRICE_SOURCE_ENTITY:
            return await self.async_step_price_entity()
        return self._finish({})

    async def async_step_nordpool(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The official Nord Pool integration: which entry and area."""
        entries = self.hass.config_entries.async_entries(NORDPOOL)
        if not entries:
            return self.async_abort(reason="nordpool_missing")
        schema = _nordpool_schema(entries)
        if user_input is None:
            return self._form("nordpool", schema)
        chosen = self.hass.config_entries.async_get_entry(
            user_input[CONF_NORDPOOL_ENTRY]
        )
        fetched = _nordpool_areas([chosen]) if chosen else []
        if fetched and user_input[CONF_NORDPOOL_AREA] not in fetched:
            return self._form(
                "nordpool", schema, errors={CONF_NORDPOOL_AREA: "area_not_fetched"}
            )
        return self._finish(
            {CONF_PRICE_SOURCE: PRICE_SOURCE_NORDPOOL_ACTION, **user_input}
        )

    async def async_step_price_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """An entity with a price list, and its format."""
        if user_input is None:
            return self._form("price_entity", PRICE_ENTITY_SCHEMA)
        return self._finish({CONF_PRICE_SOURCE: PRICE_SOURCE_ENTITY, **user_input})

    def _form(
        self,
        step_id: str,
        schema: probatio.Schema,
        errors: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Show a step; when reconfiguring, with the current answers filled in."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, self._current()),
            errors=errors,
        )

    def _current(self) -> dict[str, Any]:
        """The existing entry's answers when reconfiguring, else none."""
        if self.source != SOURCE_RECONFIGURE:
            return {}
        entry = self._get_reconfigure_entry()
        return {
            CONF_NAME: entry.title,
            CONF_PRICE_SOURCE: PRICE_SOURCE_NONE,  # unless the entry has one
            **entry.data,
        }

    def _finish(self, prices: Mapping[str, Any]) -> ConfigFlowResult:
        """Create the entry, or update the reconfigured one and reload it."""
        data = {**self._data, **prices}
        title = data.pop(CONF_NAME)
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), title=title, data=data
            )
        return self.async_create_entry(title=title, data=data)


SUGGESTED_COMPARISONS = ["0", "4", "5", "8", "10", "12", "15", "18"]


class SpotHeatingOptionsFlow(OptionsFlow):
    """Which plain thermostats the comparison series and sensors use.

    The other settings are number entities; a list of temperatures isn't a
    number, so it lives here.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the temperatures, or type others."""
        current = config_from_options(self.config_entry.options).comparison
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                temperatures = tuple(
                    sorted({float(t) for t in user_input[COMPARISON_TEMPERATURES]})
                )
                Comparison(temperatures=temperatures)
            except ValueError, ConfigError:
                errors["base"] = "invalid_temperatures"
            else:
                return await self._save(temperatures)
        schema = probatio.Schema(
            {
                probatio.Required(
                    COMPARISON_TEMPERATURES,
                    default=[f"{t:g}" for t in current.temperatures],
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=SUGGESTED_COMPARISONS,
                        multiple=True,
                        custom_value=True,
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def _save(self, temperatures: tuple[float, ...]) -> ConfigFlowResult:
        """Keep them, and let a running space rebuild its series at once."""
        entry = self.config_entry
        options = {**entry.options, COMPARISON_TEMPERATURES: list(temperatures)}
        if entry.state is ConfigEntryState.LOADED:
            await entry.runtime_data.async_set_config(config_from_options(options))
        return self.async_create_entry(data=options)

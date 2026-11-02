"""Constants shared by the Home Assistant side of the integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "spot_heating_planner"

# --- Config entry keys: what the setup flow stores (part 4 builds the flow) ---
CONF_HEATERS: Final = "heaters"
"""Switch-like entities that turn the heaters on and off."""

CONF_ENERGY_SENSORS: Final = "energy_sensors"
"""Optional kWh counters of the heaters' plugs."""

CONF_INDOOR_TEMPERATURE: Final = "indoor_temperature"
CONF_INDOOR_HUMIDITY: Final = "indoor_humidity"
CONF_OUTDOOR_TEMPERATURE: Final = "outdoor_temperature"
CONF_OUTDOOR_HUMIDITY: Final = "outdoor_humidity"
CONF_WEATHER: Final = "weather"

CONF_PRICE_SOURCE: Final = "price_source"
"""Which kind of price source: one of the PRICE_SOURCE_* values."""

PRICE_SOURCE_NORDPOOL_ACTION: Final = "nordpool_action"
"""The official Nord Pool integration's action."""

PRICE_SOURCE_ENTITY: Final = "entity"
"""An entity with a price list in its attributes, in a known format."""

CONF_NORDPOOL_ENTRY: Final = "nordpool_entry"
"""Config entry id of the official Nord Pool integration."""

CONF_NORDPOOL_AREA: Final = "nordpool_area"
CONF_CURRENCY: Final = "currency"

CONF_PRICE_ENTITY: Final = "price_entity"
CONF_PRICE_FORMAT: Final = "price_format"
"""Name of a format in prices.FORMATS."""

CONF_VAT_PERCENT: Final = "vat_percent"
"""Added to prices that don't include VAT already."""

# --- Timing ---
MEDIAN_WINDOW: Final = timedelta(minutes=30)
"""Readings are smoothed with a median over this window."""

TOMORROW_PRICES_FROM_HOUR: Final = 13
"""Local hour after which tomorrow's prices are fetched every 15 minutes
until they appear (Nord Pool publishes them around 14:00 CET)."""

# --- Storage ---
STORAGE_VERSION: Final = 1

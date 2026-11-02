"""The integration's actions.

compare_thermostat: what plain thermostats at the given temperatures would
have cost over a period, next to what heating actually cost, from Home
Assistant's long-term statistics. It returns the answer as a response, for
Developer tools or for a script's `response_variable`.
"""

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .core import comparison
from .core.config import COMPARISON_RANGE, MAX_COMPARISONS
from .runtime import comparisons, history

if TYPE_CHECKING:
    from homeassistant.core import ServiceResponse

    from .core.comparison import HourHistory
    from .runtime.space import Space

COMPARE_THERMOSTAT = "compare_thermostat"
CONF_CONFIG_ENTRY_ID = "config_entry_id"
CONF_TEMPERATURES = "temperatures"
CONF_START = "start"
CONF_END = "end"
DECIMALS = 3

COMPARE_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_CONFIG_ENTRY_ID): cv.string,
        probatio.Required(CONF_TEMPERATURES): probatio.All(
            cv.ensure_list,
            [probatio.All(probatio.Coerce(float), probatio.Range(*COMPARISON_RANGE))],
            probatio.Length(min=1, max=MAX_COMPARISONS),
        ),
        probatio.Required(CONF_START): cv.date,
        probatio.Required(CONF_END): cv.date,
    }
)


def async_register(hass: HomeAssistant) -> None:
    """Register the actions; once, for every space."""

    async def compare(call: ServiceCall) -> ServiceResponse:
        return await compare_thermostat(hass, call)

    hass.services.async_register(
        DOMAIN,
        COMPARE_THERMOSTAT,
        compare,
        schema=COMPARE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


async def compare_thermostat(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """The comparison for one space, over whole local days from start to end."""
    space = _space(hass, call.data[CONF_CONFIG_ENTRY_ID])
    start, end = _period(call.data[CONF_START], call.data[CONF_END])
    sources = comparisons.sources(hass, space.entry, space.entities)
    hours = await history.read_in_chunks(
        hass, sources, start=start, end=end, chunk=comparisons.CHUNK
    )
    return comparison_response(
        hours, call.data[CONF_TEMPERATURES], currency=space.currency
    )


def comparison_response(
    hours: list[HourHistory], temperatures: list[float], *, currency: str
) -> dict[str, Any]:
    """Actual and thermostat totals over the hours that have every reading.

    Only hours with every input (outdoor temperature, energy price, the room
    as learned then, metered energy) count, so every figure covers the same
    hours and the savings compare like with like.
    """
    complete = [
        h
        for h in hours
        if comparison.metered_hour(h) is not None
        and comparison.thermostat_hour(h, 0.0) is not None
    ]
    actual = comparison.totals(comparisons.metered(complete))
    thermostats = []
    for temperature in temperatures:
        total = comparison.totals(comparisons.thermostat_results(complete, temperature))
        thermostats.append(
            {
                "temperature": temperature,
                "energy_kwh": round(total.energy_kwh, DECIMALS),
                "cost": round(total.cost, DECIMALS),
                "savings": round(total.cost - actual.cost, DECIMALS),
            }
        )
    indoor = comparison.mean_indoor_temperature(complete)
    return {
        "currency": currency,
        "hours": len(hours),
        "hours_counted": len(complete),
        "actual": {
            "energy_kwh": round(actual.energy_kwh, DECIMALS),
            "cost": round(actual.cost, DECIMALS),
            "mean_indoor_temperature": None if indoor is None else round(indoor, 1),
        },
        "thermostats": thermostats,
    }


def _space(hass: HomeAssistant, entry_id: str) -> Space:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_space"
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="space_not_loaded"
        )
    space: Space = entry.runtime_data
    return space


def _period(first: date, last: date) -> tuple[datetime, datetime]:
    """Local midnight of `first` to the midnight after `last`, in UTC."""
    if last < first:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="end_before_start"
        )
    start = dt_util.start_of_local_day(first)
    end = dt_util.start_of_local_day(last) + timedelta(days=1)
    return dt_util.as_utc(start), dt_util.as_utc(end)

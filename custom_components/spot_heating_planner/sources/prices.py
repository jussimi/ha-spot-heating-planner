"""Spot prices, from whichever integration provides them.

The planner needs one thing: hourly prices in cents/kWh including VAT, from
the current hour on. Every source delivers exactly that through
`PriceSource.fetch`:

    NordPoolAction    the official Nord Pool integration's action
    AttributePrices   any entity with a list of prices in its attributes,
                      read according to a PriceFormat

Formats are data, not code: a known integration is one entry in FORMATS.
Prices finer than an hour (quarter-hour markets) are averaged into hours,
because the planner decides by the hour.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

type HourlyPrices = list[tuple[datetime, float]]
"""(hour start, cents/kWh incl. VAT), sorted, from the current hour on."""

PERCENT = 100.0


# --- Units and conversion ---------------------------------------------------


class PriceUnit(StrEnum):
    """How a source states its prices."""

    CENTS_PER_KWH = "c/kWh"
    PER_KWH = "currency/kWh"
    PER_MWH = "currency/MWh"


CENTS_PER_KWH_FACTOR: dict[PriceUnit, float] = {
    PriceUnit.CENTS_PER_KWH: 1.0,
    PriceUnit.PER_KWH: 100.0,  # 1 EUR/kWh = 100 c/kWh
    PriceUnit.PER_MWH: 0.1,  # 1 EUR/MWh = 0.1 c/kWh
}


@dataclass(frozen=True, kw_only=True)
class Pricing:
    """How to turn a source's price into cents/kWh including VAT."""

    unit: PriceUnit
    vat_included: bool
    vat_percent: float = 0.0
    """Added when the source's prices don't include VAT."""

    def to_cents_per_kwh(self, price: float) -> float:
        """The source's price in cents/kWh with VAT."""
        cents = price * CENTS_PER_KWH_FACTOR[self.unit]
        if self.vat_included:
            return cents
        return cents * (1 + self.vat_percent / PERCENT)


class PriceSource(Protocol):
    """Anything that can deliver hourly prices for the planner."""

    async def fetch(self, hass: HomeAssistant, now: datetime) -> HourlyPrices:
        """Hourly (start, cents/kWh incl. VAT) from the current hour on."""
        ...


# --- Shared helpers -----------------------------------------------------------


def hourly(
    raw: list[tuple[datetime, float]], pricing: Pricing, now: datetime
) -> HourlyPrices:
    """Converted prices averaged into whole hours, from the current hour on."""
    current_hour = _hour_of(now)
    by_hour: dict[datetime, list[float]] = defaultdict(list)
    for start, price in raw:
        hour = _hour_of(start)
        if hour >= current_hour:
            by_hour[hour].append(pricing.to_cents_per_kwh(price))
    return sorted((hour, sum(p) / len(p)) for hour, p in by_hour.items())


def _hour_of(time: datetime) -> datetime:
    return dt_util.as_utc(time).replace(minute=0, second=0, microsecond=0)


def tomorrow_known(prices: HourlyPrices, now: datetime) -> bool:
    """Whether the prices reach the end of tomorrow, local time."""
    if not prices:
        return False
    end_of_tomorrow = dt_util.start_of_local_day(now) + timedelta(days=2)
    last_start = prices[-1][0]
    return last_start + timedelta(hours=1) >= end_of_tomorrow


def _entry(item: Any, start_key: str, price_key: str) -> tuple[datetime, float] | None:  # noqa: ANN401 - JSON
    """(start, price) from one list item; None if it's malformed."""
    if not isinstance(item, dict):
        return None
    raw_start = item.get(start_key)
    start = (
        raw_start
        if isinstance(raw_start, datetime)
        else dt_util.parse_datetime(str(raw_start or ""))
    )
    price = item.get(price_key)
    if start is None or not isinstance(price, int | float):
        return None
    return dt_util.as_utc(start), float(price)


# --- The official Nord Pool integration -----------------------------------------


NORDPOOL_DOMAIN = "nordpool"
NORDPOOL_PRICES_ACTION = "get_price_indices_for_date"
NORDPOOL_RESOLUTION_MINUTES = 60


@dataclass(frozen=True, kw_only=True)
class NordPoolAction:
    """Prices from the official Nord Pool integration's action.

    It returns one market day per call, in currency/MWh without VAT. A market
    day runs in Central European time, so a local day can span two of them:
    fetch yesterday, today and tomorrow. Days that fail to load are skipped;
    tomorrow's don't exist until early afternoon.
    """

    config_entry_id: str
    area: str
    currency: str
    vat_percent: float

    async def fetch(self, hass: HomeAssistant, now: datetime) -> HourlyPrices:
        """Hourly prices from the current hour on."""
        pricing = Pricing(
            unit=PriceUnit.PER_MWH, vat_included=False, vat_percent=self.vat_percent
        )
        today = dt_util.as_local(now).date()
        raw: list[tuple[datetime, float]] = []
        for offset in (-1, 0, 1):
            raw += await self._fetch_day(hass, today + timedelta(days=offset))
        return hourly(raw, pricing, now)

    async def _fetch_day(
        self, hass: HomeAssistant, day: date
    ) -> list[tuple[datetime, float]]:
        try:
            response = await hass.services.async_call(
                NORDPOOL_DOMAIN,
                NORDPOOL_PRICES_ACTION,
                {
                    "config_entry": self.config_entry_id,
                    "date": day.isoformat(),
                    "areas": [self.area],
                    "currency": self.currency,
                    "resolution": NORDPOOL_RESOLUTION_MINUTES,
                },
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError:
            return []
        items = response.get(self.area) if isinstance(response, dict) else None
        if not isinstance(items, list):
            return []
        entries = (_entry(item, "start", "price") for item in items)
        return [e for e in entries if e is not None]


# --- Any entity with a price list in its attributes --------------------------------


@dataclass(frozen=True, kw_only=True)
class PriceFormat:
    """Where an entity keeps its price list, and what the numbers mean."""

    attributes: tuple[str, ...]
    """Attributes holding lists of prices; read in order and combined."""

    start_key: str
    """Key of the start time in each list item."""

    price_key: str
    """Key of the price in each list item."""

    unit: PriceUnit
    vat_included: bool


FORMATS: dict[str, PriceFormat] = {
    # This integration's own format: one list, already in c/kWh incl. VAT.
    # A template sensor can bring any price source into it.
    "spot_heating_planner": PriceFormat(
        attributes=("forecast",),
        start_key="start",
        price_key="price",
        unit=PriceUnit.CENTS_PER_KWH,
        vat_included=True,
    ),
}
"""Known formats by name. Add an integration here once its attributes have
been checked against a real installation."""


@dataclass(frozen=True, kw_only=True)
class AttributePrices:
    """Prices from a list in an entity's attributes, read by a PriceFormat."""

    entity_id: str
    price_format: PriceFormat
    vat_percent: float = 0.0
    """Added when the format's prices don't include VAT."""

    async def fetch(self, hass: HomeAssistant, now: datetime) -> HourlyPrices:
        """Hourly prices from the current hour on; [] if the entity has none."""
        state = hass.states.get(self.entity_id)
        if state is None:
            return []
        fmt = self.price_format
        raw: list[tuple[datetime, float]] = []
        for attribute in fmt.attributes:
            items = state.attributes.get(attribute)
            if isinstance(items, list):
                entries = (_entry(i, fmt.start_key, fmt.price_key) for i in items)
                raw += [e for e in entries if e is not None]
        pricing = Pricing(
            unit=fmt.unit, vat_included=fmt.vat_included, vat_percent=self.vat_percent
        )
        return hourly(raw, pricing, now)

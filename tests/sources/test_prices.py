"""Spot prices from the Nord Pool action and from entity attributes."""

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.spot_heating_planner.sources.prices import (
    FORMATS,
    AttributePrices,
    NordPoolAction,
    PriceUnit,
    Pricing,
    hourly,
    tomorrow_known,
)

NORDPOOL = NordPoolAction(
    config_entry_id="nordpool-entry", area="FI", currency="EUR", vat_percent=25.5
)
PRICE_PER_MWH = 40.0
CENTS_PER_KWH = 40.0 * 1.255 / 10  # 5.02 c/kWh incl. VAT
PRICE_ENTITY = "sensor.spot_price_forecast"


def current_hour() -> datetime:
    return dt_util.utcnow().replace(minute=0, second=0, microsecond=0)


# --- Units ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pricing", "price", "cents"),
    [
        (Pricing(unit=PriceUnit.CENTS_PER_KWH, vat_included=True), 5.0, 5.0),
        (Pricing(unit=PriceUnit.PER_KWH, vat_included=True), 0.05, 5.0),
        (Pricing(unit=PriceUnit.PER_MWH, vat_included=True), 50.0, 5.0),
        (
            Pricing(unit=PriceUnit.PER_MWH, vat_included=False, vat_percent=25.5),
            40.0,
            5.02,
        ),
    ],
)
def test_units_become_cents_per_kwh_with_vat(
    pricing: Pricing, price: float, cents: float
) -> None:
    assert pricing.to_cents_per_kwh(price) == pytest.approx(cents)


def test_quarter_hours_are_averaged_into_hours() -> None:
    hour = current_hour()
    quarters = [(hour + timedelta(minutes=15 * q), float(q + 1)) for q in range(4)]
    cents = Pricing(unit=PriceUnit.CENTS_PER_KWH, vat_included=True)
    assert hourly(quarters, cents, hour) == [(hour, 2.5)]


def test_past_hours_are_dropped() -> None:
    hour = current_hour()
    raw = [(hour - timedelta(hours=1), 9.0), (hour, 3.0)]
    cents = Pricing(unit=PriceUnit.CENTS_PER_KWH, vat_included=True)
    assert hourly(raw, cents, hour + timedelta(minutes=20)) == [(hour, 3.0)]


def test_tomorrow_known_needs_the_last_hour_of_tomorrow() -> None:
    now = dt_util.utcnow()
    start = dt_util.start_of_local_day(now)
    two_days = [(start + timedelta(hours=h), 1.0) for h in range(48)]
    assert tomorrow_known(two_days, now)
    assert not tomorrow_known(two_days[:-1], now)
    assert not tomorrow_known([], now)


# --- The official Nord Pool action ------------------------------------------------


def market_day(day: date) -> list[dict[str, Any]]:
    """24 hourly prices for a market day, starting at midnight CET."""
    start = datetime(day.year, day.month, day.day, tzinfo=dt_util.UTC)
    start -= timedelta(hours=1)
    return [
        {
            "start": (start + timedelta(hours=h)).isoformat(),
            "end": (start + timedelta(hours=h + 1)).isoformat(),
            "price": PRICE_PER_MWH,
        }
        for h in range(24)
    ]


@pytest.fixture
async def nordpool(hass: HomeAssistant) -> list[ServiceCall]:
    """A fake Nord Pool action; tomorrow isn't published yet."""
    await hass.config.async_set_time_zone("Europe/Helsinki")
    calls: list[ServiceCall] = []
    tomorrow = dt_util.now().date() + timedelta(days=1)

    async def handle(call: ServiceCall) -> dict[str, Any]:
        calls.append(call)
        day = date.fromisoformat(str(call.data["date"]))
        if day == tomorrow:
            raise ServiceValidationError("not published yet")
        return {"FI": market_day(day)}

    hass.services.async_register(
        "nordpool",
        "get_price_indices_for_date",
        handle,
        supports_response=SupportsResponse.ONLY,
    )
    return calls


async def test_nordpool_prices_from_the_current_hour(
    hass: HomeAssistant, nordpool: list[ServiceCall]
) -> None:
    now = dt_util.utcnow()
    prices = await NORDPOOL.fetch(hass, now)
    assert prices[0][0] == current_hour()
    assert all(price == pytest.approx(CENTS_PER_KWH) for _, price in prices)
    assert len(nordpool) == 3  # yesterday, today and tomorrow


async def test_nordpool_asks_for_the_area_and_hourly_prices(
    hass: HomeAssistant, nordpool: list[ServiceCall]
) -> None:
    await NORDPOOL.fetch(hass, dt_util.utcnow())
    call = nordpool[0].data
    assert call["config_entry"] == "nordpool-entry"
    assert call["areas"] == ["FI"]
    assert call["resolution"] == 60


async def test_missing_tomorrow_is_not_an_error(
    hass: HomeAssistant, nordpool: list[ServiceCall]
) -> None:
    now = dt_util.utcnow()
    prices = await NORDPOOL.fetch(hass, now)
    assert prices
    assert not tomorrow_known(prices, now)
    del nordpool


async def test_no_nordpool_integration_means_no_prices(hass: HomeAssistant) -> None:
    assert await NORDPOOL.fetch(hass, dt_util.utcnow()) == []


# --- An entity with a price list ---------------------------------------------------


def our_format_entity(hass: HomeAssistant, prices: list[float]) -> None:
    hour = current_hour()
    forecast = [
        {"start": (hour + timedelta(hours=h)).isoformat(), "price": p}
        for h, p in enumerate(prices)
    ]
    hass.states.async_set(PRICE_ENTITY, str(prices[0]), {"forecast": forecast})


async def test_reads_our_own_format(hass: HomeAssistant) -> None:
    our_format_entity(hass, [3.0, 50.0, 8.0])
    source = AttributePrices(
        entity_id=PRICE_ENTITY, price_format=FORMATS["spot_heating_planner"]
    )
    prices = await source.fetch(hass, dt_util.utcnow())
    assert [p for _, p in prices] == [3.0, 50.0, 8.0]


async def test_missing_entity_means_no_prices(hass: HomeAssistant) -> None:
    source = AttributePrices(
        entity_id=PRICE_ENTITY, price_format=FORMATS["spot_heating_planner"]
    )
    assert await source.fetch(hass, dt_util.utcnow()) == []


async def test_malformed_items_are_skipped(hass: HomeAssistant) -> None:
    hour = current_hour().isoformat()
    hass.states.async_set(
        PRICE_ENTITY,
        "1",
        {"forecast": [{"start": hour, "price": 4.0}, {"start": hour}, "junk"]},
    )
    source = AttributePrices(
        entity_id=PRICE_ENTITY, price_format=FORMATS["spot_heating_planner"]
    )
    assert [p for _, p in await source.fetch(hass, dt_util.utcnow())] == [4.0]

"""The thermostat comparison, end to end: history in, series and answers out.

Uses a real recorder, filled with a day of made-up history: outdoor -10 deg C,
energy price 18.5 c/kWh, a learned room of 25 W/deg C with a 1 kW heater,
and the heater metering 0.5 kWh an hour.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    StatisticsRow,
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.spot_heating_planner.const import DOMAIN
from custom_components.spot_heating_planner.core.options import COMPARISON_TEMPERATURES
from custom_components.spot_heating_planner.runtime import comparisons, statistics
from custom_components.spot_heating_planner.runtime.space import Space
from tests.fakes import ENERGY, OUTDOOR, config_entry, fake_space

ENERGY_PRICE = "sensor.garage_energy_price"
HEAT_LOSS = "sensor.garage_heat_loss"
HEATER_POWER = "sensor.garage_heater_power"
HOURS = 24
PRICE = 18.5
THERMOSTAT_KWH = 0.375  # 25 W/deg C * (5 - -10) deg C for an hour
METERED_KWH = 0.5


@pytest.fixture
def mock_recorder_before_hass(async_setup_recorder_instance: object) -> None:
    """A real recorder, set up before Home Assistant as it needs."""
    del async_setup_recorder_instance


def day_start() -> datetime:
    hour = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    return hour - timedelta(days=2)


def import_means(
    hass: HomeAssistant, statistic_id: str, unit: str, value: float, start: datetime
) -> None:
    unit_class = {"°C": "temperature", "W": "power"}.get(unit)
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=False,
            name=None,
            source="recorder",
            statistic_id=statistic_id,
            unit_class=unit_class,
            unit_of_measurement=unit,
        ),
        [
            StatisticData(start=start + timedelta(hours=h), mean=value)
            for h in range(HOURS)
        ],
    )


def import_meter(hass: HomeAssistant, start: datetime, first_sum: float = 0.0) -> None:
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=None,
            source="recorder",
            statistic_id=ENERGY,
            unit_class="energy",
            unit_of_measurement="kWh",
        ),
        [
            StatisticData(
                start=start + timedelta(hours=h),
                state=100 + first_sum + METERED_KWH * (h + 1),
                sum=first_sum + METERED_KWH * (h + 1),
            )
            for h in range(HOURS)
        ],
    )


def add_history(hass: HomeAssistant, start: datetime, first_sum: float = 0.0) -> None:
    import_means(hass, OUTDOOR, "°C", -10.0, start)
    import_means(hass, ENERGY_PRICE, "c/kWh", PRICE, start)
    import_means(hass, HEAT_LOSS, "W/°C", 25.0, start)
    import_means(hass, HEATER_POWER, "W", 1000.0, start)
    import_meter(hass, start, first_sum)


@pytest.fixture
async def garage(
    recorder_mock: object, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[MockConfigEntry]:
    """A running space comparing with 5 and 10 deg C, and a day of history.

    The made-up history predates the space's sensors, so the series are told
    to start from it.
    """
    del recorder_mock
    monkeypatch.setattr(comparisons, "first_priced_hour", lambda *_: day_start())
    fake_space(hass)
    entry = config_entry(hass, options={COMPARISON_TEMPERATURES: [5.0, 10.0]})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    add_history(hass, day_start())
    await async_wait_recording_done(hass)
    yield entry
    assert await hass.config_entries.async_unload(entry.entry_id)


async def last_sum(hass: HomeAssistant, statistic_id: str) -> float | None:
    def query() -> dict[str, list[StatisticsRow]]:
        return statistics_during_period(
            hass, day_start(), None, {statistic_id}, "hour", None, {"sum"}
        )

    rows = await hass.async_add_executor_job(query)
    series = rows.get(statistic_id, [])
    return series[-1].get("sum") if series else None


async def update(hass: HomeAssistant, entry: MockConfigEntry) -> Space:
    space: Space = entry.runtime_data
    await space.async_update_comparisons()
    await async_wait_recording_done(hass)
    return space


# --- The series -----------------------------------------------------------------------


async def test_series_are_written_from_history(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    await update(hass, garage)
    thermostat = statistics.statistic_id(garage, statistics.thermostat_cost(5, "EUR"))
    metered = statistics.statistic_id(garage, statistics.metered_cost("EUR"))
    assert await last_sum(hass, thermostat) == pytest.approx(
        HOURS * THERMOSTAT_KWH * PRICE / 100
    )
    assert await last_sum(hass, metered) == pytest.approx(
        HOURS * METERED_KWH * PRICE / 100
    )


async def test_the_next_run_only_appends(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    space = await update(hass, garage)
    key = statistics.thermostat_cost(5, "EUR").key
    after_first = space.memory.comparison_totals[key]
    # A second day of history arrives
    add_history(hass, day_start() + timedelta(hours=HOURS), HOURS * METERED_KWH)
    await async_wait_recording_done(hass)
    await update(hass, garage)
    assert space.memory.comparison_totals[key] == pytest.approx(2 * after_first)


async def test_new_temperatures_start_over(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    space = await update(hass, garage)
    await hass.config_entries.options.async_init(garage.entry_id)
    flow = await hass.config_entries.options.async_init(garage.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"], {COMPARISON_TEMPERATURES: ["8"]}
    )
    await update(hass, garage)
    assert space.memory.comparison_temperatures == [8.0]
    eight = statistics.thermostat_cost(8, "EUR").key
    assert space.memory.comparison_totals[eight] > 0


# --- The action -----------------------------------------------------------------------


async def compare(hass: HomeAssistant, entry_id: str, **data: str) -> dict[str, Any]:
    start = day_start().date()
    response = await hass.services.async_call(
        DOMAIN,
        "compare_thermostat",
        {
            "config_entry_id": entry_id,
            "temperatures": [5, 10],
            "start": start.isoformat(),
            "end": (start + timedelta(days=1)).isoformat(),
            **data,
        },
        blocking=True,
        return_response=True,
    )
    assert isinstance(response, dict)
    return response


async def test_action_compares_thermostats_with_the_actual_cost(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    response = await compare(hass, garage.entry_id)
    assert response["hours_counted"] == HOURS
    actual = response["actual"]["cost"]
    assert actual == pytest.approx(HOURS * METERED_KWH * PRICE / 100, abs=1e-3)
    at_5, at_10 = response["thermostats"]
    assert at_5["energy_kwh"] == pytest.approx(HOURS * THERMOSTAT_KWH, abs=1e-3)
    assert at_10["energy_kwh"] > at_5["energy_kwh"]
    assert at_5["savings"] == pytest.approx(at_5["cost"] - actual, abs=1e-3)


async def test_action_refuses_an_unknown_space(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    del garage
    with pytest.raises(ServiceValidationError):
        await compare(hass, "no-such-entry")


async def test_action_refuses_a_period_ending_before_it_starts(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    start = day_start().date()
    with pytest.raises(ServiceValidationError):
        await compare(
            hass,
            garage.entry_id,
            start=start.isoformat(),
            end=(start - timedelta(days=1)).isoformat(),
        )


async def test_chunks_give_the_same_series_as_one_pass(
    hass: HomeAssistant, garage: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_history(hass, day_start() + timedelta(hours=HOURS), HOURS * METERED_KWH)
    await async_wait_recording_done(hass)
    space = await update(hass, garage)
    one_pass = dict(space.memory.comparison_totals)

    monkeypatch.setattr(comparisons, "CHUNK", timedelta(hours=5))
    space.memory.comparison_temperatures = None  # force a fresh start
    await update(hass, garage)
    assert space.memory.comparison_totals == pytest.approx(one_pass)


async def test_nothing_before_the_price_sensor_existed(
    hass: HomeAssistant, garage: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    space: Space = garage.runtime_data
    monkeypatch.setattr(comparisons, "first_priced_hour", lambda *_: dt_util.utcnow())
    space.memory.comparison_temperatures = None
    await update(hass, garage)
    assert space.memory.comparison_totals == {}

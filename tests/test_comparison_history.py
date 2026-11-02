"""The thermostat comparison, end to end: history in, series and answers out.

Uses a real recorder, filled with a day of made-up history: outdoor -10 deg C,
spot price 10 c/kWh, and the heater metering 0.5 kWh an hour.
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
from custom_components.spot_heating_planner.core.config import Config
from custom_components.spot_heating_planner.runtime import statistics
from custom_components.spot_heating_planner.runtime.space import Space
from tests.fakes import ENERGY, KNOWN_ROOM, OUTDOOR, config_entry, fake_space

PRICE = "sensor.garage_spot_price"
HOURS = 24
FIXED = Config().prices.fixed_energy_cost


@pytest.fixture
def mock_recorder_before_hass(async_setup_recorder_instance: object) -> None:
    """A real recorder, set up before Home Assistant as it needs."""
    del async_setup_recorder_instance


def history_start() -> datetime:
    hour = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    return hour - timedelta(days=2)


def import_series(
    hass: HomeAssistant, statistic_id: str, unit: str, rows: list[StatisticData]
) -> None:
    unit_class = {"°C": "temperature", "kWh": "energy"}.get(unit)
    cumulative = unit == "kWh"
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE
            if cumulative
            else StatisticMeanType.ARITHMETIC,
            has_sum=cumulative,
            name=None,
            source="recorder",
            statistic_id=statistic_id,
            unit_class=unit_class,
            unit_of_measurement=unit,
        ),
        rows,
    )


def add_history(hass: HomeAssistant) -> None:
    start = history_start()
    hours = [start + timedelta(hours=h) for h in range(HOURS)]
    import_series(
        hass, OUTDOOR, "°C", [StatisticData(start=h, mean=-10.0) for h in hours]
    )
    import_series(
        hass, PRICE, "c/kWh", [StatisticData(start=h, mean=10.0) for h in hours]
    )
    import_series(
        hass,
        ENERGY,
        "kWh",
        [
            StatisticData(start=h, state=100 + 0.5 * (i + 1), sum=0.5 * (i + 1))
            for i, h in enumerate(hours)
        ],
    )


@pytest.fixture
async def garage(
    recorder_mock: object, hass: HomeAssistant, hass_storage: dict[str, Any]
) -> AsyncIterator[MockConfigEntry]:
    """A running space with a known room and a day of history."""
    del recorder_mock, hass_storage
    fake_space(hass)
    entry = config_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    space: Space = entry.runtime_data
    await space.async_set_config(Config(manual_room=KNOWN_ROOM))
    add_history(hass)
    await async_wait_recording_done(hass)
    yield entry
    assert await hass.config_entries.async_unload(entry.entry_id)


async def read_sum(hass: HomeAssistant, statistic_id: str) -> float | None:
    def query() -> dict[str, list[StatisticsRow]]:
        return statistics_during_period(
            hass, history_start(), None, {statistic_id}, "hour", None, {"sum"}
        )

    rows = await hass.async_add_executor_job(query)
    series = rows.get(statistic_id, [])
    return series[-1].get("sum") if series else None


# --- The series -----------------------------------------------------------------------


async def test_rebuild_writes_the_thermostat_and_metered_series(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    space: Space = garage.runtime_data
    await space.async_rebuild_comparisons()
    await async_wait_recording_done(hass)

    thermostat = statistics.thermostat_cost(5.0, "EUR")
    metered = statistics.metered_cost("EUR")
    # 25 W/deg C * 15 deg C = 0.375 kWh an hour at 10 + 8.5 c
    expected_thermostat = HOURS * 0.375 * (10 + FIXED) / 100
    expected_metered = HOURS * 0.5 * (10 + FIXED) / 100
    thermostat_sum = await read_sum(hass, statistics.statistic_id(garage, thermostat))
    metered_sum = await read_sum(hass, statistics.statistic_id(garage, metered))
    assert thermostat_sum == pytest.approx(expected_thermostat)
    assert metered_sum == pytest.approx(expected_metered)


# --- The action -----------------------------------------------------------------------


async def compare(hass: HomeAssistant, entry_id: str, **data: str) -> dict[str, Any]:
    start = history_start().date()
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
    assert actual == pytest.approx(HOURS * 0.5 * (10 + FIXED) / 100, abs=1e-3)
    at_5, at_10 = response["thermostats"]
    assert at_5["temperature"] == 5
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
    start = history_start().date()
    with pytest.raises(ServiceValidationError):
        await compare(
            hass,
            garage.entry_id,
            start=start.isoformat(),
            end=(start - timedelta(days=1)).isoformat(),
        )


async def test_action_needs_a_learned_room(
    hass: HomeAssistant, garage: MockConfigEntry
) -> None:
    space: Space = garage.runtime_data
    await space.async_set_config(Config())  # forget the manual room
    with pytest.raises(ServiceValidationError):
        await compare(hass, garage.entry_id)

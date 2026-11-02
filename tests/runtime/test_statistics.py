"""Writing series into Home Assistant's real recorder."""

from datetime import timedelta

import pytest
from homeassistant.components.recorder.statistics import (
    StatisticsRow,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.spot_heating_planner.runtime import statistics
from tests.fakes import config_entry


@pytest.fixture
def mock_recorder_before_hass(async_setup_recorder_instance: object) -> None:
    """Set up a real recorder before Home Assistant, as the recorder needs."""
    del async_setup_recorder_instance


@pytest.mark.usefixtures("recorder_mock")
async def test_series_are_accepted_by_the_recorder(hass: HomeAssistant) -> None:
    entry = config_entry(hass)
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    start -= timedelta(hours=2)
    statistics.write_hour(
        hass,
        entry,
        statistics.DAY_AHEAD_ENERGY,
        statistics.Hour(start=start, value=0.5, total=0.5),
    )
    statistics.write_hour(
        hass,
        entry,
        statistics.DAY_AHEAD_TEMPERATURE,
        statistics.Hour(start=start, value=4.2),
    )
    await async_wait_recording_done(hass)

    energy_id = statistics.statistic_id(entry, statistics.DAY_AHEAD_ENERGY)
    temperature_id = statistics.statistic_id(entry, statistics.DAY_AHEAD_TEMPERATURE)

    def read() -> dict[str, list[StatisticsRow]]:
        return statistics_during_period(
            hass,
            start,
            None,
            {energy_id, temperature_id},
            "hour",
            None,
            {"sum", "mean"},
        )

    rows = await hass.async_add_executor_job(read)
    assert rows[energy_id][0]["sum"] == 0.5
    assert rows[temperature_id][0]["mean"] == 4.2


async def test_nothing_is_written_without_the_recorder(hass: HomeAssistant) -> None:
    entry = config_entry(hass)
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    statistics.write_hour(  # would raise if it tried to reach a recorder
        hass, entry, statistics.DAY_AHEAD_ENERGY, statistics.Hour(start=start, value=1)
    )

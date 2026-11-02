"""Taking the day-ahead forecast and writing it into the statistics."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.spot_heating_planner.core.config import Config
from custom_components.spot_heating_planner.runtime import statistics
from custom_components.spot_heating_planner.runtime.space import Space
from tests.fakes import KNOWN_ROOM, config_entry, fake_space


@pytest.fixture
async def space(hass: HomeAssistant) -> AsyncIterator[Space]:
    """A known room with two days of prices: tomorrow is known from the start."""
    fake_space(hass)
    running = Space(hass, config_entry(hass), cfg=Config(manual_room=KNOWN_ROOM))
    await running.async_start()
    yield running
    await running.async_stop()


@pytest.fixture
def written(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, statistics.Hour]]:
    """Every hour written into the statistics, by series key."""
    rows: list[tuple[str, statistics.Hour]] = []

    def capture(
        hass: HomeAssistant,
        entry: object,
        series: statistics.Series,
        hour: statistics.Hour,
    ) -> None:
        del hass, entry
        rows.append((series.key, hour))

    monkeypatch.setattr(statistics, "write_hour", capture)
    return rows


def tomorrow_at(hour: int) -> datetime:
    start = dt_util.start_of_local_day(dt_util.utcnow()) + timedelta(days=1)
    return dt_util.as_utc(start + timedelta(hours=hour))


async def test_takes_tomorrows_forecast_once_prices_are_known(space: Space) -> None:
    memory = space._memory  # noqa: SLF001 - checking what was kept
    assert memory.day_ahead
    assert all(tomorrow_at(0) <= h.start < tomorrow_at(24) for h in memory.day_ahead)
    assert memory.day_ahead_date == dt_util.as_local(tomorrow_at(0)).date().isoformat()


async def test_writes_each_hour_when_it_ends(
    space: Space, written: list[tuple[str, statistics.Hour]]
) -> None:
    forecast = space._memory.day_ahead[0]  # noqa: SLF001
    await space.async_tick(forecast.start + timedelta(hours=1))
    keys = {key for key, _ in written}
    assert keys == {"day_ahead_energy", "day_ahead_cost", "day_ahead_temperature"}
    energy = next(hour for key, hour in written if key == "day_ahead_energy")
    assert energy.start == forecast.start
    assert energy.value == forecast.energy_kwh
    assert energy.total == forecast.energy_kwh  # the first hour starts the total


async def test_written_hours_are_forgotten(
    space: Space, written: list[tuple[str, statistics.Hour]]
) -> None:
    forecast = space._memory.day_ahead[0]  # noqa: SLF001
    await space.async_tick(forecast.start + timedelta(hours=1))
    assert forecast not in space._memory.day_ahead  # noqa: SLF001
    del written


async def test_the_forecast_survives_a_restart(
    hass: HomeAssistant, space: Space
) -> None:
    await space.async_stop()
    again = Space(hass, space.entry, cfg=space.cfg)
    await again.async_start()
    assert again._memory.day_ahead == space._memory.day_ahead  # noqa: SLF001
    await again.async_stop()

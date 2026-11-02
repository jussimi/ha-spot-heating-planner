"""What a space remembers across restarts."""

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.spot_heating_planner.core.learning import StepSample
from custom_components.spot_heating_planner.runtime.storage import Memory, SpaceStore


def sample() -> StepSample:
    return StepSample(
        start=dt_util.utcnow().replace(microsecond=0),
        minutes=15,
        indoor_temperature_start=5.0,
        indoor_temperature_end=5.3,
        outdoor_temperature=-10.0,
        heat_share=1.0,
        energy_kwh=0.25,
    )


async def test_memory_survives_a_restart(hass: HomeAssistant) -> None:
    now = dt_util.utcnow().replace(microsecond=0)
    memory = Memory(
        samples=[sample()],
        calibration_start=now,
        override_until=now + timedelta(hours=3),
    )
    await SpaceStore(hass, "entry-1").save_now(memory)
    assert await SpaceStore(hass, "entry-1").load() == memory


async def test_spaces_dont_share_memory(hass: HomeAssistant) -> None:
    await SpaceStore(hass, "entry-1").save_now(Memory(samples=[sample()]))
    assert await SpaceStore(hass, "entry-2").load() == Memory()


async def test_damaged_memory_starts_afresh(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    hass_storage["spot_heating_planner.entry-1"] = {
        "version": 1,
        "data": {"samples": [{"start": "not a time"}]},
    }
    assert await SpaceStore(hass, "entry-1").load() == Memory()

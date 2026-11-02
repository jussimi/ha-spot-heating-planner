"""What a space remembers across restarts, in Home Assistant's own storage.

Kept in .storage/spot_heating_planner.<entry id>: the logged learning steps,
a calibration run's start, when a manual override ends, whether control is
paused, the heating energy and cost so far, and the day-ahead forecast.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import DOMAIN, STORAGE_VERSION
from ..core import learning
from ..core.day_ahead import ForecastHour

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant

    from ..core.learning import StepSample

SAVE_DELAY_SECONDS = 60
"""Coalesce saves: the steps change every 15 minutes, not every second."""


@dataclass
class Memory:
    """Everything a space keeps across restarts."""

    samples: list[StepSample] = field(default_factory=list)
    calibration_start: datetime | None = None
    override_until: datetime | None = None
    enabled: bool = True
    """Whether the space switches its heaters; off pauses control."""
    cost_total: float = 0.0
    """Heating cost so far, in currency units incl. fixed costs."""
    energy_total: float = 0.0
    """Heating energy so far, kWh: measured, or estimated without meters."""
    day_ahead: list[ForecastHour] = field(default_factory=list)
    """Tomorrow's (and what's left of today's) hours as forecast the day before."""
    day_ahead_date: str | None = None
    """The local date (ISO) whose day-ahead forecast has been taken."""
    day_ahead_energy_total: float = 0.0
    day_ahead_cost_total: float = 0.0


class SpaceStore:
    """Loads and saves one space's Memory."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Store under the config entry's id, so spaces don't mix."""
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}"
        )

    async def load(self) -> Memory:
        """The saved memory; empty if there is none or it is damaged."""
        data = await self._store.async_load()
        if data is None:
            return Memory()
        try:
            return _from_json(data)
        except KeyError, TypeError, ValueError:
            return Memory()

    def save_soon(self, memory: Memory) -> None:
        """Save within SAVE_DELAY_SECONDS, together with any other changes."""
        self._store.async_delay_save(lambda: _to_json(memory), SAVE_DELAY_SECONDS)

    async def save_now(self, memory: Memory) -> None:
        """Save straight away, e.g. when the integration is unloaded."""
        await self._store.async_save(_to_json(memory))


def _to_json(memory: Memory) -> dict[str, Any]:
    return {
        "samples": [learning.sample_to_dict(s) for s in memory.samples],
        "calibration_start": _time_to_json(memory.calibration_start),
        "override_until": _time_to_json(memory.override_until),
        "enabled": memory.enabled,
        "cost_total": memory.cost_total,
        "energy_total": memory.energy_total,
        "day_ahead": [_forecast_to_json(h) for h in memory.day_ahead],
        "day_ahead_date": memory.day_ahead_date,
        "day_ahead_energy_total": memory.day_ahead_energy_total,
        "day_ahead_cost_total": memory.day_ahead_cost_total,
    }


def _from_json(data: dict[str, Any]) -> Memory:
    return Memory(
        samples=[learning.sample_from_dict(s) for s in data["samples"]],
        calibration_start=_time_from_json(data.get("calibration_start")),
        override_until=_time_from_json(data.get("override_until")),
        enabled=bool(data.get("enabled", True)),
        cost_total=float(data.get("cost_total", 0.0)),
        energy_total=float(data.get("energy_total", 0.0)),
        day_ahead=[_forecast_from_json(h) for h in data.get("day_ahead", [])],
        day_ahead_date=data.get("day_ahead_date"),
        day_ahead_energy_total=float(data.get("day_ahead_energy_total", 0.0)),
        day_ahead_cost_total=float(data.get("day_ahead_cost_total", 0.0)),
    )


def _forecast_to_json(hour: ForecastHour) -> dict[str, Any]:
    return {
        "start": hour.start.isoformat(),
        "energy_kwh": hour.energy_kwh,
        "cost": hour.cost,
        "temperature": hour.temperature,
    }


def _forecast_from_json(data: dict[str, Any]) -> ForecastHour:
    start = dt_util.parse_datetime(data["start"])
    if start is None:
        raise ValueError(data["start"])
    return ForecastHour(
        start=start,
        energy_kwh=float(data["energy_kwh"]),
        cost=float(data["cost"]),
        temperature=float(data["temperature"]),
    )


def _time_to_json(time: datetime | None) -> str | None:
    return None if time is None else time.isoformat()


def _time_from_json(text: str | None) -> datetime | None:
    return None if text is None else dt_util.parse_datetime(text)

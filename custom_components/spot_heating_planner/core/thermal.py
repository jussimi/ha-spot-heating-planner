"""How a room warms and cools.

Newton's law of cooling: heat leaks out in proportion to how much warmer
the room is than outside, and the heaters add their power:

    C * dT/dt = -UA * (T - T_outdoor) + P

The room settles exponentially towards an equilibrium temperature. All
temperatures are deg C. Derivation: docs/physics.md#warming-and-cooling
"""

import math
from dataclasses import dataclass

MINUTES_PER_HOUR = 60
WATTS_PER_KW = 1000.0
LN_2 = math.log(2)


@dataclass(frozen=True, kw_only=True)
class Room:
    """The space itself, independent of what heats it."""

    heat_loss_kw: float
    """UA, kW per deg C: heat leaking out per degree above outside."""

    heat_capacity_kwh: float
    """C, kWh per deg C: heat stored per degree of warming."""


@dataclass(frozen=True, kw_only=True)
class HeatedRoom:
    """A room with heaters in it: everything the planner needs."""

    room: Room

    heater_power_kw: float
    """P: total draw of the heaters while on."""

    @property
    def cooling_rate(self) -> float:
        """Share of the indoor-outdoor difference lost per hour (k = UA / C)."""
        return self.room.heat_loss_kw / self.room.heat_capacity_kwh

    @property
    def max_rise(self) -> float:
        """How far above outside the heaters could hold the room (G = P / UA)."""
        return self.heater_power_kw / self.room.heat_loss_kw

    @property
    def half_life_hours(self) -> float:
        """Hours to lose half the warmth above outside, unheated (ln 2 / k)."""
        return LN_2 / self.cooling_rate


def settle(start: float, target: float, hours: float, cooling_rate: float) -> float:
    """Temperature after `hours` of settling from `start` towards `target`.

    T(t) = target + (start - target) * exp(-k * t)
    """
    return target + (start - target) * math.exp(-cooling_rate * hours)


def temperature_after(
    start: float,
    outdoor_temperature: float,
    hours: float,
    heated_room: HeatedRoom,
    *,
    heating_minutes: float = 0,
) -> float:
    """Indoor temperature after `hours`, heating for the first `heating_minutes`.

    While heating the room settles towards outdoor_temperature + max_rise, then
    coasts towards outdoor_temperature.
    """
    k = heated_room.cooling_rate
    hours_on = min(heating_minutes / MINUTES_PER_HOUR, hours)
    heated = settle(start, outdoor_temperature + heated_room.max_rise, hours_on, k)
    return settle(heated, outdoor_temperature, hours - hours_on, k)


def coasting_hours(
    start: float,
    outdoor_temperatures: list[float],
    lower_limit: float,
    heated_room: HeatedRoom,
) -> float | None:
    """Hours the room can go unheated before it cools to `lower_limit`.

    Follows the hourly outdoor temperatures given; None if the room stays
    warmer than `lower_limit` through all of them. With a constant outdoor
    temperature: ln((start - outdoor) / (lower_limit - outdoor)) / k
    """
    if start <= lower_limit:
        return 0.0
    indoor_temperature = start
    for hour, outdoor_temperature in enumerate(outdoor_temperatures):
        an_hour_later = temperature_after(
            indoor_temperature, outdoor_temperature, 1, heated_room
        )
        if an_hour_later <= lower_limit < indoor_temperature:
            drop = indoor_temperature - an_hour_later
            return hour + (indoor_temperature - lower_limit) / drop
        indoor_temperature = an_hour_later
    return None

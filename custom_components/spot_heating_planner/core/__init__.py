"""The planner's logic: plain Python with no Home Assistant imports.

Everything here can be run and tested on any machine. The Home Assistant
side gathers readings into `Inputs` and settings into `Config`, then calls

    sensors.plausible_*(...) every reading: impossible values count as missing
    sensors.stuck_while_heating(...)  a sensor that stopped reporting
    safety.check(...)        every minute: the three emergency rules
    learning.estimate(...)   every 15 minutes: the room (UA, C) from logged steps
    learning.choose(...)     which room to use: manual, learned, or none yet
    planner.plan_hour(...)   every hour, with a room: minutes to heat this hour
    planner.thermostat(...)  every minute, without one: a plain on/off band
    calibration.phase(...)   during a calibration run: heat, then coast

humidity.py and thermal.py hold the physics, explained in docs/physics.md.
"""

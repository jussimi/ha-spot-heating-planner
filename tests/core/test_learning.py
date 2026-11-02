"""Learning the room from logged 15-minute steps."""

import json
import random
from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.spot_heating_planner.core import learning, thermal
from custom_components.spot_heating_planner.core.config import ManualRoom
from custom_components.spot_heating_planner.core.learning import (
    RoomEstimate,
    StepSample,
)
from custom_components.spot_heating_planner.core.thermal import HeatedRoom, Room

from .example import CFG, HEATED_ROOM, NOW, ROOM

STEP_MINUTES = CFG.learning.step_minutes
STEP_HOURS = STEP_MINUTES / 60
SENSOR_RESOLUTION = 0.1  # deg C, like a typical BTHome sensor


def read(t: float, rnd: random.Random, noise: float) -> float:
    """A sensor reading: noise, then rounded to the sensor's resolution."""
    return round((t + rnd.gauss(0, noise)) / SENSOR_RESOLUTION) * SENSOR_RESOLUTION


def simulate(  # noqa: PLR0913 - one knob per scenario
    pattern: list[float],
    *,
    outdoor_temperature: float = -10.0,
    indoor_temperature_start: float = 8.0,
    noise: float = 0.02,
    seed: int = 1,
    metered: bool = True,
    surge_kwh: float = 0.0,
    open_doors: tuple[int, ...] = (),
) -> list[StepSample]:
    """Steps from the example space following an on/off pattern per step.

    surge_kwh is extra energy, and so extra heat, whenever the heater starts.
    """
    rnd = random.Random(seed)
    warming_per_kwh = 1 / ROOM.heat_capacity_kwh  # a burst of heat warms by E / C
    t, was_on, samples = indoor_temperature_start, False, []
    for i, share in enumerate(pattern):
        surge = surge_kwh if share > 0 and not was_on else 0.0
        t_end = thermal.temperature_after(
            t,
            outdoor_temperature,
            STEP_HOURS,
            HEATED_ROOM,
            heating_minutes=share * STEP_MINUTES,
        )
        t_end += surge * warming_per_kwh
        if i in open_doors:
            t_end -= 1.5  # a door left open: a step the model can't explain
        kwh = share * HEATED_ROOM.heater_power_kw * STEP_HOURS + surge
        samples.append(
            StepSample(
                start=NOW + i * timedelta(minutes=STEP_MINUTES),
                minutes=STEP_MINUTES,
                indoor_temperature_start=read(t, rnd, noise),
                indoor_temperature_end=read(t_end, rnd, noise),
                outdoor_temperature=outdoor_temperature,
                heat_share=share,
                energy_kwh=kwh if metered else None,
            )
        )
        t, was_on = t_end, share > 0
    return samples


def calibration_run(cycles: int = 1) -> list[float]:
    """1 h heating then 2.5 h coasting, in 15-minute steps."""
    return ([1.0] * 4 + [0.0] * 10) * cycles


def fit(samples: list[StepSample]) -> RoomEstimate:
    """The estimate, failing the test if there is none."""
    estimate = learning.estimate(samples, CFG)
    assert estimate is not None
    return estimate


def test_one_calibration_run_in_the_cold_is_enough() -> None:
    estimate = fit(simulate(calibration_run(), outdoor_temperature=-10))
    assert estimate.confident
    room = estimate.heated_room.room
    assert room.heat_loss_kw == pytest.approx(ROOM.heat_loss_kw, rel=0.25)
    assert room.heat_capacity_kwh == pytest.approx(ROOM.heat_capacity_kwh, rel=0.25)


def test_small_temperature_difference_needs_more_data() -> None:
    # Only 2 deg C above outside: one run leaves UA and C uncertain...
    first = learning.estimate(
        simulate(calibration_run(), outdoor_temperature=3, indoor_temperature_start=5),
        CFG,
    )
    assert first is None or not first.confident
    # ...three runs pin them down
    estimate = fit(
        simulate(
            calibration_run(cycles=3), outdoor_temperature=3, indoor_temperature_start=5
        )
    )
    assert estimate.confident


def test_uncertainty_shrinks_with_data() -> None:
    one = fit(simulate(calibration_run(1)))
    four = fit(simulate(calibration_run(4)))
    assert four.heat_loss_error < one.heat_loss_error
    assert four.heat_capacity_error < one.heat_capacity_error


def test_learns_the_power_from_the_meter() -> None:
    estimate = fit(simulate(calibration_run(3)))
    assert estimate.heated_room.heater_power_kw == pytest.approx(1.0, abs=0.01)


def test_without_a_meter_uses_the_configured_power() -> None:
    estimate = fit(simulate(calibration_run(3), metered=False))
    assert estimate.heated_room.heater_power_kw == CFG.heaters.power_kw
    room = estimate.heated_room.room
    assert room.heat_loss_kw == pytest.approx(ROOM.heat_loss_kw, rel=0.25)


def test_counts_the_cold_start_surge_as_heat() -> None:
    estimate = fit(simulate(calibration_run(4), surge_kwh=0.05))
    assert estimate.heated_room.heater_power_kw > HEATED_ROOM.heater_power_kw
    room = estimate.heated_room.room
    assert room.heat_loss_kw == pytest.approx(ROOM.heat_loss_kw, rel=0.25)
    assert room.heat_capacity_kwh == pytest.approx(ROOM.heat_capacity_kwh, rel=0.25)


def test_ignores_open_door_steps() -> None:
    samples = simulate(calibration_run(4), open_doors=(10, 30))
    estimate = fit(samples)
    assert estimate.steps_used <= len(samples) - 2
    room = estimate.heated_room.room
    assert room.heat_loss_kw == pytest.approx(ROOM.heat_loss_kw, rel=0.25)
    assert room.heat_capacity_kwh == pytest.approx(ROOM.heat_capacity_kwh, rel=0.25)


def test_drops_the_recovery_after_an_anomaly_too() -> None:
    samples = simulate(calibration_run(4), open_doors=(10,))
    kept = learning.drop_anomalies(samples, CFG)
    assert kept is not None
    kept_starts = {s.start for s in kept}
    door = samples[10].start
    recovery = timedelta(minutes=CFG.learning.after_anomaly_minutes)
    assert not any(door <= start <= door + recovery for start in kept_starts)


def test_many_anomalies_dont_hide_each_other() -> None:
    # One step in eight disturbed: a plain RMS limit would swell and let
    # them through; the median-based one doesn't
    doors = tuple(range(5, 14 * 6, 8))
    clean = fit(simulate(calibration_run(6)))
    disturbed = fit(simulate(calibration_run(6), open_doors=doors))
    clean_room, disturbed_room = clean.heated_room.room, disturbed.heated_room.room
    assert disturbed_room.heat_loss_kw == pytest.approx(
        clean_room.heat_loss_kw, rel=0.15
    )
    assert disturbed_room.heat_capacity_kwh == pytest.approx(
        clean_room.heat_capacity_kwh, rel=0.15
    )


def test_clean_data_keeps_almost_every_step() -> None:
    samples = simulate(calibration_run(4))
    kept = learning.drop_anomalies(samples, CFG)
    assert kept is not None
    assert len(kept) >= 0.9 * len(samples)


def test_needs_both_heating_and_coasting() -> None:
    assert learning.estimate(simulate([1.0] * 20), CFG) is None
    assert learning.estimate(simulate([0.0] * 20), CFG) is None


def test_skips_steps_with_gaps() -> None:
    samples = [replace(s, minutes=40) for s in simulate(calibration_run(2))]
    assert learning.estimate(samples, CFG) is None


def test_keeps_only_the_learning_window() -> None:
    samples = simulate(calibration_run(130))  # about 20 days
    now = samples[-1].start
    kept = learning.recent(samples, now, CFG)
    assert all(now - s.start <= timedelta(days=CFG.learning.window_days) for s in kept)
    assert len(kept) < len(samples)


# --- Choosing the model -------------------------------------------------------


LEARNED_ROOM = Room(heat_loss_kw=0.03, heat_capacity_kwh=0.5)


def estimate_with(*, confident: bool) -> RoomEstimate:
    return RoomEstimate(
        heated_room=HeatedRoom(room=LEARNED_ROOM, heater_power_kw=0.9),
        heat_loss_error=0.1,
        heat_capacity_error=0.1,
        steps_used=50,
        rms_error=0.05,
        confident=confident,
    )


def test_no_model_while_learning() -> None:
    assert learning.choose(CFG, None) == learning.RoomChoice("learning", None)
    unsure = estimate_with(confident=False)
    assert learning.choose(CFG, unsure).status == "learning"


def test_confident_estimate_is_used() -> None:
    sure = estimate_with(confident=True)
    assert learning.choose(CFG, sure) == learning.RoomChoice(
        "learned", sure.heated_room
    )


def test_manual_room_wins_and_keeps_the_measured_power() -> None:
    cfg = CFG.with_groups(ManualRoom(heat_loss_w=40.0, heat_capacity_kwh=1.2))
    choice = learning.choose(cfg, estimate_with(confident=True))
    assert choice.status == "manual"
    manual_room = Room(heat_loss_kw=0.04, heat_capacity_kwh=1.2)
    assert choice.heated_room == HeatedRoom(room=manual_room, heater_power_kw=0.9)


def test_adding_a_heater_changes_max_rise_but_not_the_room() -> None:
    bigger = replace(HEATED_ROOM, heater_power_kw=2 * HEATED_ROOM.heater_power_kw)
    assert bigger.max_rise == pytest.approx(2 * HEATED_ROOM.max_rise)
    assert bigger.cooling_rate == HEATED_ROOM.cooling_rate


# --- Saving logged steps ------------------------------------------------------


def test_samples_survive_a_round_trip_through_json() -> None:
    samples = simulate(calibration_run(), metered=True)
    samples.append(replace(samples[0], energy_kwh=None))  # a step without a meter
    stored = json.loads(json.dumps([learning.sample_to_dict(s) for s in samples]))
    assert [learning.sample_from_dict(d) for d in stored] == samples


def test_damaged_sample_raises() -> None:
    data = learning.sample_to_dict(simulate([1.0])[0])
    del data["outdoor_temperature"]
    with pytest.raises(KeyError):
        learning.sample_from_dict(data)

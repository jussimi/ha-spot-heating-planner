"""Learning the room (heat loss UA and heat capacity C) from logged steps.

Over one short step of length dt, with the outside temperature constant:

    dT_end = a * dT_start + c * E,     dT = T_in - T_out
    a = exp(-k * dt),  k = UA / C,  c = warming per kWh,  E = kWh used in the step

That is linear in a and c, so least squares over the logged steps finds
them, and their standard errors tell how well the data pins them down. The
room follows from them, independent of the heaters:

    UA = (1 - a) / (c * dt)          C = UA / k = UA * dt / -ln(a)

The heaters' power P comes from the energy meters. The room is used once UA
and C are both known to within learn_max_relative_error; until then the space
runs as a plain thermostat. Derivation and caveats: docs/physics.md#learning
"""

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .thermal import MINUTES_PER_HOUR, WATTS_PER_KW, HeatedRoom, Room

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .config import Config

# Below this the normal equations can't tell a from c apart
SINGULAR = 1e-12
# Turns a median absolute deviation into a standard deviation (normal errors)
MAD_TO_SIGMA = 1.4826
# A step this far off the configured length is a gap, not a step
STEP_TOLERANCE = 0.1
# Least squares with two unknowns needs more points than that
PARAMETERS = 2


@dataclass(frozen=True, kw_only=True)
class StepSample:
    """One logged step of learn_step_minutes."""

    start: datetime

    minutes: float
    """Actual length of the step."""

    indoor_temperature_start: float
    """Indoor temperature at the start, deg C."""

    indoor_temperature_end: float
    """Indoor temperature at the end, deg C."""

    outdoor_temperature: float
    """Outdoor sensor, average over the step, deg C."""

    heat_share: float
    """Share of the step the heaters were on."""

    energy_kwh: float | None = None
    """Measured by the plugs; None without an energy meter."""


@dataclass(frozen=True, kw_only=True)
class RoomEstimate:
    """The room fitted to logged steps, with its uncertainty, and its heaters."""

    heated_room: HeatedRoom

    heat_loss_error: float
    """Standard error of UA relative to UA."""

    heat_capacity_error: float
    """Standard error of C relative to C."""

    steps_used: int

    rms_error: float
    """Typical miss of the fitted model per step, deg C."""

    confident: bool
    """Whether UA and C are both known well enough to plan with."""


@dataclass(frozen=True)
class RoomChoice:
    """The heated room to plan with, and where it came from."""

    status: str
    """'manual', 'learned' or 'learning' (no usable room yet)."""

    heated_room: HeatedRoom | None


def choose(cfg: Config, estimate: RoomEstimate | None) -> RoomChoice:
    """A manual room if set, else the learned one once it is confident.

    The heaters' power is the measured one when there is an estimate.
    """
    manual = cfg.manual_room
    if manual.heat_loss_w is not None and manual.heat_capacity_kwh is not None:
        power = (
            estimate.heated_room.heater_power_kw if estimate else cfg.heaters.power_kw
        )
        room = Room(
            heat_loss_kw=manual.heat_loss_w / WATTS_PER_KW,
            heat_capacity_kwh=manual.heat_capacity_kwh,
        )
        return RoomChoice("manual", HeatedRoom(room=room, heater_power_kw=power))
    if estimate is not None and estimate.confident:
        return RoomChoice("learned", estimate.heated_room)
    return RoomChoice("learning", None)


def recent(samples: list[StepSample], now: datetime, cfg: Config) -> list[StepSample]:
    """The samples inside the learning window."""
    cutoff = now - timedelta(days=cfg.learning.window_days)
    return [s for s in samples if s.start >= cutoff]


def estimate(samples: list[StepSample], cfg: Config) -> RoomEstimate | None:
    """The room fitted to the samples; None if the data won't do.

    Anomalies (a door left open, a warm car parked inside) are found and left
    out first; see `drop_anomalies`.
    """
    usable = [s for s in samples if _full_step(s, cfg)]
    kept = drop_anomalies(usable, cfg)
    if kept is None:
        return None
    fit = _least_squares(kept, cfg)
    if fit is None:
        return None
    return _to_estimate(fit, kept, cfg)


def drop_anomalies(samples: list[StepSample], cfg: Config) -> list[StepSample] | None:
    """The samples without anomalies; None if too little is left to learn from.

    Fit, then drop every step that misses by more than learn_outlier_sigma
    robust standard deviations, together with the steps right after it, and
    repeat until nothing changes. The spread is measured with the median
    absolute deviation (MAD), which the anomalies themselves can't inflate
    the way they would a plain RMS. docs/physics.md#anomalies
    """
    kept = samples
    for _ in range(cfg.learning.max_rounds):
        if not _enough_variety(kept, cfg):
            return None
        fit = _least_squares(kept, cfg)
        if fit is None:
            return None
        limit = max(
            cfg.learning.outlier_sigma * _robust_sigma(_errors(kept, fit, cfg)),
            cfg.learning.min_outlier_limit,
        )
        errors = _errors(samples, fit, cfg)
        anomalies = [
            s.start for s, e in zip(samples, errors, strict=True) if abs(e) > limit
        ]
        survivors = [s for s in samples if not _near_anomaly(s, anomalies, cfg)]
        if survivors == kept:
            break
        kept = survivors
    return kept if _enough_variety(kept, cfg) else None


def _robust_sigma(errors: list[float]) -> float:
    """Standard deviation estimated from the median absolute deviation.

    For normally distributed errors sigma = 1.4826 * MAD; a few huge errors
    barely move it.
    """
    median = statistics.median(errors)
    return MAD_TO_SIGMA * statistics.median(abs(e - median) for e in errors)


def _near_anomaly(sample: StepSample, anomalies: list[datetime], cfg: Config) -> bool:
    """Whether the step is an anomaly or starts within the recovery after one."""
    recovery = timedelta(minutes=cfg.learning.after_anomaly_minutes)
    return any(start <= sample.start <= start + recovery for start in anomalies)


def energy(sample: StepSample, cfg: Config) -> float:
    """KWh delivered in the step: measured, else estimated from the on-time."""
    if sample.energy_kwh is not None:
        return sample.energy_kwh
    return sample.heat_share * cfg.heaters.power_kw * sample.minutes / MINUTES_PER_HOUR


def sample_to_dict(sample: StepSample) -> dict[str, Any]:
    """The sample as JSON-friendly values, for Home Assistant's storage."""
    data = asdict(sample)
    data["start"] = sample.start.isoformat()
    return data


def sample_from_dict(data: Mapping[str, Any]) -> StepSample:
    """A sample saved by sample_to_dict.

    Raises KeyError, TypeError or ValueError if the data is damaged.
    """
    energy_kwh = data.get("energy_kwh")
    return StepSample(
        start=datetime.fromisoformat(data["start"]),
        minutes=float(data["minutes"]),
        indoor_temperature_start=float(data["indoor_temperature_start"]),
        indoor_temperature_end=float(data["indoor_temperature_end"]),
        outdoor_temperature=float(data["outdoor_temperature"]),
        heat_share=float(data["heat_share"]),
        energy_kwh=None if energy_kwh is None else float(energy_kwh),
    )


# --- The fit --------------------------------------------------------------


@dataclass(frozen=True)
class _Fit:
    """Least-squares a and c with their variances and covariance."""

    a: float
    c: float
    var_a: float
    var_c: float
    cov_ac: float


def _least_squares(samples: list[StepSample], cfg: Config) -> _Fit | None:
    """(a, c) minimising sum (dT_end - a*dT_start - c*E)^2, with uncertainty.

    From the 2x2 normal equations; the covariance of (a, c) is
    sigma^2 * inverse(X'X), sigma^2 = SSE / (n - 2).
    None if the equations are singular or there are too few samples.
    """
    if len(samples) <= PARAMETERS:
        return None
    sxx = sxe = see = sxy = sey = 0.0
    for s in samples:
        x, e, y = (
            s.indoor_temperature_start - s.outdoor_temperature,
            energy(s, cfg),
            s.indoor_temperature_end - s.outdoor_temperature,
        )
        sxx, sxe, see = sxx + x * x, sxe + x * e, see + e * e
        sxy, sey = sxy + x * y, sey + e * y
    det = sxx * see - sxe * sxe
    if abs(det) < SINGULAR:
        return None
    a = (sxy * see - sey * sxe) / det
    c = (sey * sxx - sxy * sxe) / det
    sse = sum(e * e for e in _residuals(samples, a, c, cfg))
    sigma2 = sse / (len(samples) - PARAMETERS)
    return _Fit(
        a=a,
        c=c,
        var_a=sigma2 * see / det,
        var_c=sigma2 * sxx / det,
        cov_ac=-sigma2 * sxe / det,
    )


def _residuals(
    samples: list[StepSample], a: float, c: float, cfg: Config
) -> list[float]:
    return [
        (s.indoor_temperature_end - s.outdoor_temperature)
        - a * (s.indoor_temperature_start - s.outdoor_temperature)
        - c * energy(s, cfg)
        for s in samples
    ]


def _errors(samples: list[StepSample], fit: _Fit, cfg: Config) -> list[float]:
    return _residuals(samples, fit.a, fit.c, cfg)


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def _full_step(sample: StepSample, cfg: Config) -> bool:
    """Whether the sample is a whole step; gaps would bias the fit."""
    expected = cfg.learning.step_minutes
    return abs(sample.minutes - expected) <= STEP_TOLERANCE * expected


def _enough_variety(samples: list[StepSample], cfg: Config) -> bool:
    heating = sum(1 for s in samples if s.heat_share > 0)
    return (
        heating >= cfg.learning.min_heating_steps
        and len(samples) - heating >= cfg.learning.min_coasting_steps
    )


def _average_power(samples: list[StepSample], cfg: Config) -> float:
    """KW while on: measured energy over hours on; the setting if unmeasured."""
    measured = [s for s in samples if s.energy_kwh is not None and s.heat_share > 0]
    hours_on = sum(s.heat_share * s.minutes / MINUTES_PER_HOUR for s in measured)
    if hours_on <= 0:
        return cfg.heaters.power_kw
    return sum(s.energy_kwh or 0.0 for s in measured) / hours_on


def _to_estimate(fit: _Fit, kept: list[StepSample], cfg: Config) -> RoomEstimate | None:
    """The room and heater power from the fit, if physically plausible.

    Relative errors by the delta method, for f = UA or C:
        var(f) = (df/da)^2 var(a) + (df/dc)^2 var(c) + 2 df/da df/dc cov(a, c)
    """
    a, c = fit.a, fit.c
    if not 0 < a < 1 or c <= 0:
        return None
    dt = cfg.learning.step_minutes / MINUTES_PER_HOUR
    log_a = -math.log(a)  # k * dt
    heat_loss = (1 - a) / (c * dt)
    heat_capacity = heat_loss * dt / log_a
    if not _plausible(heat_loss, heat_capacity, cfg):
        return None

    # UA = (1 - a) / (c dt)
    loss_da = -1 / (c * dt)
    loss_dc = -(1 - a) / (c * c * dt)
    # C = (1 - a) / (c * -ln a)
    capacity_da = (-log_a + (1 - a) / a) / (log_a * log_a * c)
    capacity_dc = -(1 - a) / (log_a * c * c)
    loss_error = _propagate(fit, loss_da, loss_dc) / heat_loss
    capacity_error = _propagate(fit, capacity_da, capacity_dc) / heat_capacity

    room = Room(heat_loss_kw=heat_loss, heat_capacity_kwh=heat_capacity)
    return RoomEstimate(
        heated_room=HeatedRoom(room=room, heater_power_kw=_average_power(kept, cfg)),
        heat_loss_error=loss_error,
        heat_capacity_error=capacity_error,
        steps_used=len(kept),
        rms_error=_rms(_errors(kept, fit, cfg)),
        confident=max(loss_error, capacity_error) <= cfg.learning.max_relative_error,
    )


def _plausible(heat_loss_kw: float, heat_capacity_kwh: float, cfg: Config) -> bool:
    loss_low, loss_high = cfg.learning.heat_loss_range_w
    capacity_low, capacity_high = cfg.learning.heat_capacity_range_kwh
    return (
        loss_low <= heat_loss_kw * WATTS_PER_KW <= loss_high
        and capacity_low <= heat_capacity_kwh <= capacity_high
    )


def _propagate(fit: _Fit, d_da: float, d_dc: float) -> float:
    """Standard error of a function of (a, c) with these partial derivatives."""
    variance = (
        d_da * d_da * fit.var_a + d_dc * d_dc * fit.var_c + 2 * d_da * d_dc * fit.cov_ac
    )
    return math.sqrt(max(variance, 0.0))

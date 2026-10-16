"""Seasonal vegetation anomaly methods.

Reference construction (leakage-safe by design, tested in tests/scientific):
  * only composites from years strictly BEFORE the target composite's year;
  * only the N most recent such years (configurable);
  * only composites with the same 16-day composite start (optionally ±k composites);
  * only quality-accepted observations;
  * only observations whose ``available_at`` is not later than the assessment's ``as_of``.

Methods:
  standard z   Z = (x − μ_ref) / σ_ref          (σ with ddof=1)
  robust z     Z_r = (x − median_ref) / (1.4826 · MAD_ref)
  percentile   mid-rank empirical percentile of x within the reference sample

Small samples and near-zero dispersion return explicit statuses instead of numbers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

import numpy as np

MAD_SCALE = 1.4826


class AnomalyStatus(StrEnum):
    ok = "ok"
    missing_value = "missing_value"
    insufficient_reference = "insufficient_reference"
    zero_variance = "zero_variance"


@dataclass(frozen=True)
class SeriesPoint:
    period_start: date
    value: float | None
    accepted: bool
    available_at: datetime


@dataclass
class ReferenceStats:
    n: int
    years: list[int]
    mean: float | None
    std: float | None
    median: float | None
    mad_scaled: float | None
    p10: float | None
    p90: float | None


@dataclass
class AnomalyResult:
    period_start: date
    value: float | None
    status: AnomalyStatus
    reference: ReferenceStats
    z: float | None = None
    robust_z: float | None = None
    percentile: float | None = None
    robust_z_interval: tuple[float, float] | None = None
    flags: list[str] = field(default_factory=list)


def composite_index(d: date) -> int:
    """0-based index of a MOD13 16-day composite within its year (DOY 1, 17, 33, … → 0, 1, 2, …)."""
    return (d.timetuple().tm_yday - 1) // 16


def reference_sample(
    series: Sequence[SeriesPoint],
    target_start: date,
    as_of: datetime,
    n_years: int,
    pool: int = 0,
) -> list[tuple[int, float]]:
    target_year = target_start.year
    target_idx = composite_index(target_start)
    first_year = target_year - n_years
    out: dict[int, list[float]] = {}
    for p in series:
        y = p.period_start.year
        if not (first_year <= y < target_year):
            continue
        if abs(composite_index(p.period_start) - target_idx) > pool:
            continue
        if not p.accepted or p.value is None or (isinstance(p.value, float) and math.isnan(p.value)):
            continue
        if p.available_at > as_of:
            continue
        out.setdefault(y, []).append(p.value)
    # One value per year (mean over pooled composites) so years are weighted equally.
    return sorted((y, float(np.mean(v))) for y, v in out.items())


def mid_rank_percentile(x: float, ref: Sequence[float]) -> float:
    arr = np.asarray(ref, dtype=float)
    if arr.size == 0:
        raise ValueError("percentile of an empty reference sample is undefined")
    less = float(np.sum(arr < x))
    equal = float(np.sum(arr == x))
    return 100.0 * (less + 0.5 * equal) / len(arr)


def reference_stats(sample: list[tuple[int, float]]) -> ReferenceStats:
    vals = np.array([v for _, v in sample], dtype=float)
    n = len(vals)
    if n == 0:
        return ReferenceStats(0, [], None, None, None, None, None, None)
    med = float(np.median(vals))
    return ReferenceStats(
        n=n,
        years=[y for y, _ in sample],
        mean=float(vals.mean()),
        std=float(vals.std(ddof=1)) if n > 1 else None,
        median=med,
        mad_scaled=float(MAD_SCALE * np.median(np.abs(vals - med))),
        p10=float(np.percentile(vals, 10)),
        p90=float(np.percentile(vals, 90)),
    )


def bootstrap_robust_z_interval(x: float, ref: Sequence[float], variance_floor: float, n_boot: int = 400, seed: int = 0) -> tuple[float, float] | None:
    """5–95 % interval of the robust z when the reference years are resampled.

    Expresses how sensitive the anomaly is to which historical years happen to be
    in the reference sample. It is not a calibrated probability.
    """
    arr = np.asarray(ref, dtype=float)
    rng = np.random.default_rng(seed)
    zs = []
    for _ in range(n_boot):
        s = rng.choice(arr, size=len(arr), replace=True)
        med = np.median(s)
        mad = MAD_SCALE * np.median(np.abs(s - med))
        if mad < variance_floor:
            continue
        zs.append((x - med) / mad)
    if len(zs) < n_boot * 0.5:
        return None
    return float(np.percentile(zs, 5)), float(np.percentile(zs, 95))


def compute_anomaly(
    series: Sequence[SeriesPoint],
    target: SeriesPoint,
    as_of: datetime,
    *,
    n_years: int,
    min_samples: int,
    variance_floor: float,
    pool: int = 0,
) -> AnomalyResult:
    sample = reference_sample(series, target.period_start, as_of, n_years, pool)
    ref = reference_stats(sample)
    if target.value is None or not target.accepted:
        return AnomalyResult(target.period_start, None, AnomalyStatus.missing_value, ref)
    x = float(target.value)
    res = AnomalyResult(target.period_start, x, AnomalyStatus.ok, ref)
    floor_n = max(min_samples, 2)  # dispersion is undefined below two reference years
    if ref.n < floor_n:
        res.status = AnomalyStatus.insufficient_reference
        res.flags.append(f"reference_n_below_{floor_n}")
        return res
    vals = [v for _, v in sample]
    res.percentile = mid_rank_percentile(x, vals)
    assert ref.std is not None and ref.mean is not None and ref.median is not None and ref.mad_scaled is not None
    if ref.std < variance_floor or ref.mad_scaled < variance_floor:
        res.status = AnomalyStatus.zero_variance
        res.flags.append("reference_dispersion_below_floor")
        return res
    res.z = (x - ref.mean) / ref.std
    res.robust_z = (x - ref.median) / ref.mad_scaled
    res.robust_z_interval = bootstrap_robust_z_interval(x, vals, variance_floor)
    return res


@dataclass
class PersistenceResult:
    consecutive_low: int
    composites_considered: list[date]
    gap_break: bool


def low_persistence(
    anomalies: Sequence[AnomalyResult],
    robust_z_threshold: float,
    percentile_threshold: float,
    max_gap_days: int = 32,
) -> PersistenceResult:
    """Count the most recent run of consecutive 'low' composites (newest first).

    Missing composites are skipped but a gap > ``max_gap_days`` between usable
    composites breaks the run (a long cloudy gap is not evidence of persistence).
    """
    usable = sorted((a for a in anomalies if a.status == AnomalyStatus.ok), key=lambda a: a.period_start, reverse=True)
    count, used, prev, gap_break = 0, [], None, False
    for a in usable:
        if prev is not None and (prev - a.period_start).days > max_gap_days:
            gap_break = True
            break
        is_low = (a.robust_z is not None and a.robust_z <= robust_z_threshold) and (a.percentile is not None and a.percentile <= percentile_threshold)
        if not is_low:
            break
        count += 1
        used.append(a.period_start)
        prev = a.period_start
    return PersistenceResult(count, used, gap_break)

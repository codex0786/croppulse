"""Seasonal baseline and anomaly methods."""

from datetime import UTC, date, datetime

import numpy as np
import pytest

from croppulse.science.anomaly import (
    AnomalyStatus,
    SeriesPoint,
    composite_index,
    compute_anomaly,
    low_persistence,
    mid_rank_percentile,
    reference_sample,
)

T0 = datetime(2000, 1, 1, tzinfo=UTC)


def series(values_by_year: dict[int, float | None], d=(9, 14), accepted=True):
    return [SeriesPoint(date(y, *d), v, accepted and v is not None, T0) for y, v in values_by_year.items()]


def test_composite_index():
    assert composite_index(date(2026, 1, 1)) == 0
    assert composite_index(date(2026, 1, 17)) == 1
    assert composite_index(date(2026, 9, 14)) == 16  # DOY 257


def test_standard_and_robust_z_match_hand_calculation():
    ref = {2010 + i: v for i, v in enumerate([0.60, 0.62, 0.58, 0.61, 0.59, 0.63, 0.57, 0.60, 0.62, 0.58])}
    s = series(ref | {2026: 0.45})
    a = compute_anomaly(s, s[-1], datetime(2026, 12, 1, tzinfo=UTC), n_years=20, min_samples=8, variance_floor=0.005)
    vals = np.array(list(ref.values()))
    assert a.status == AnomalyStatus.ok
    assert a.z == pytest.approx((0.45 - vals.mean()) / vals.std(ddof=1))
    med = np.median(vals)
    assert a.robust_z == pytest.approx((0.45 - med) / (1.4826 * np.median(np.abs(vals - med))))
    assert a.percentile == 0.0
    lo, hi = a.robust_z_interval
    assert lo <= a.robust_z <= hi or lo < hi


def test_insufficient_reference():
    s = series({2020: 0.6, 2021: 0.6, 2022: 0.62, 2026: 0.4})
    a = compute_anomaly(s, s[-1], datetime(2026, 12, 1, tzinfo=UTC), n_years=15, min_samples=8, variance_floor=0.005)
    assert a.status == AnomalyStatus.insufficient_reference and a.z is None and a.robust_z is None


def test_zero_variance_is_not_infinite():
    s = series({y: 0.6 for y in range(2010, 2026)} | {2026: 0.4})
    a = compute_anomaly(s, s[-1], datetime(2026, 12, 1, tzinfo=UTC), n_years=20, min_samples=8, variance_floor=0.005)
    assert a.status == AnomalyStatus.zero_variance and a.z is None


def test_missing_target_is_missing_not_low():
    s = series({y: 0.6 + 0.01 * (y % 3) for y in range(2010, 2026)} | {2026: None})
    a = compute_anomaly(s, s[-1], datetime(2026, 12, 1, tzinfo=UTC), n_years=20, min_samples=8, variance_floor=0.005)
    assert a.status == AnomalyStatus.missing_value and a.value is None and a.robust_z is None


def test_rejected_reference_values_are_excluded():
    s = series({y: 0.6 + 0.01 * (y % 3) for y in range(2010, 2026)})
    s.append(SeriesPoint(date(2015, 9, 14), 0.05, False, T0))  # cloudy duplicate, not accepted
    sample = reference_sample(s, date(2026, 9, 14), datetime(2026, 12, 1, tzinfo=UTC), 20)
    assert all(v > 0.5 for _, v in sample)


def test_outlier_robustness():
    base = {2010 + i: v for i, v in enumerate([0.60, 0.61, 0.59, 0.60, 0.62, 0.58, 0.61, 0.60, 0.59, 0.05])}  # one bad year
    s = series(base | {2026: 0.50})
    a = compute_anomaly(s, s[-1], datetime(2026, 12, 1, tzinfo=UTC), n_years=20, min_samples=8, variance_floor=0.005)
    assert a.robust_z < -5 < a.z  # robust z still flags; classic z is diluted by the outlier


def test_mid_rank_percentile():
    assert mid_rank_percentile(0.5, [0.4, 0.5, 0.6, 0.7]) == pytest.approx(37.5)


def test_persistence_breaks_on_long_gap_and_normal_value():
    def a(d, z, p):
        r = compute_anomaly([], SeriesPoint(d, 0.5, True, T0), T0, n_years=1, min_samples=0, variance_floor=0.0)
        r.status, r.robust_z, r.percentile = AnomalyStatus.ok, z, p
        return r

    runs = [a(date(2026, 9, 14), -2, 3), a(date(2026, 8, 29), -2, 5), a(date(2026, 8, 13), 0.1, 50)]
    p = low_persistence(runs, -1.5, 10)
    assert p.consecutive_low == 2
    gap = [a(date(2026, 9, 14), -2, 3), a(date(2026, 6, 26), -2, 3)]
    p2 = low_persistence(gap, -1.5, 10)
    assert p2.consecutive_low == 1 and p2.gap_break

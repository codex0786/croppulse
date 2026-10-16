"""Scientific guards: no future information, chronological splits, reproducible metrics."""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from croppulse.config import science_config
from croppulse.research.backtest import backtest_unit
from croppulse.research.evaluation import (
    check_feature_availability,
    check_split,
    group_holdout,
    metrics_from_table,
    pr_auc,
    precision_recall,
    temporal_holdout,
)
from croppulse.research.reports import SyntheticDataError, assert_real_data
from croppulse.risk.engine import FieldContext
from croppulse.science.anomaly import SeriesPoint, compute_anomaly, reference_sample
from croppulse.science.weather import compute_weather_features

T0 = datetime(2000, 1, 1, tzinfo=UTC)


def _series(years, d=(9, 14), base=0.6):
    rng = np.random.default_rng(1)
    return [SeriesPoint(date(y, *d), base + rng.normal(0, 0.03), True, T0) for y in years]


def test_reference_excludes_target_year_and_later_years():
    s = _series(range(2005, 2031))
    sample = reference_sample(s, date(2020, 9, 14), datetime(2035, 1, 1, tzinfo=UTC), n_years=15)
    years = [y for y, _ in sample]
    assert max(years) == 2019 and min(years) == 2005 and 2020 not in years


def test_reference_excludes_observations_not_yet_available():
    s = _series(range(2010, 2026))
    late = [SeriesPoint(p.period_start, p.value, True, datetime(2030, 1, 1, tzinfo=UTC)) if p.period_start.year == 2024 else p for p in s]
    sample = reference_sample(late, date(2025, 9, 14), datetime(2025, 10, 15, tzinfo=UTC), n_years=15)
    assert 2024 not in [y for y, _ in sample]


def test_anomaly_invariant_to_appending_future_data():
    s = _series(range(2008, 2026))
    target = SeriesPoint(date(2025, 9, 14), 0.4, True, T0)
    as_of = datetime(2025, 10, 15, tzinfo=UTC)
    a1 = compute_anomaly(s + [target], target, as_of, n_years=15, min_samples=8, variance_floor=0.005)
    future = [SeriesPoint(date(y, 9, 14), 0.01, True, T0) for y in range(2026, 2035)]
    a2 = compute_anomaly(s + [target] + future, target, as_of, n_years=15, min_samples=8, variance_floor=0.005)
    assert a1.robust_z == a2.robust_z and a1.percentile == a2.percentile and a1.reference.years == a2.reference.years


def _weather(end: date, days: int = 36 * 365) -> pd.DataFrame:
    idx = [end - timedelta(days=i) for i in range(days)][::-1]
    rng = np.random.default_rng(2)
    return pd.DataFrame({"PRECTOTCORR": rng.gamma(0.5, 6, days), "T2M_MAX": 33 + rng.normal(0, 2, days)}, index=pd.Index(idx, name="date"))


def test_weather_features_invariant_to_future_rows():
    w = _weather(date(2026, 10, 1))
    kw = dict(windows=[7, 30, 90], reference_years=30, min_reference_years=20, min_coverage=0.9, rainy_day_mm=2.5, heat_tmax_c=40, heat_window_days=14)
    f1 = compute_weather_features(w[w.index <= date(2025, 8, 15)], date(2025, 8, 15), **kw)
    f2 = compute_weather_features(w, date(2025, 8, 15), **kw)
    assert f1.to_dict() == f2.to_dict()


def test_backtest_prediction_unchanged_by_later_data():
    years = range(2005, 2027)
    s = [
        (
            SeriesPoint(date(y, m, d), 0.5 + 0.1 * np.sin(y), True, T0),
            date(y, m, d) + timedelta(days=15),
            {"valid_fraction": 1.0, "selection_rule": "pixel_center_in_polygon"},
        )
        for y in years
        for (m, d) in ((7, 28), (8, 13), (8, 29), (9, 14))
    ]
    w = _weather(date(2026, 10, 1))
    ctx = FieldContext("u", "soybean", "kharif", None, False, "polygon", 12, 2024)
    cfg = science_config()
    full = backtest_unit("u", ctx, s, w, [date(2020, 9, 15)], cfg)
    cut = [t for t in s if t[0].period_start <= date(2020, 9, 15)]
    trunc = backtest_unit("u", ctx, cut, w[w.index <= date(2020, 9, 15)], [date(2020, 9, 15)], cfg)
    pd.testing.assert_frame_equal(full, trunc)
    # simulated 21-day latency: the 2020-08-13 composite ends 08-28 → available 09-18, i.e. NOT on 09-15;
    # the latest usable composite is 2020-07-28 (ends 08-12 → available 09-02).
    assert full.loc[0, "veg_period_start"] == "2020-07-28"


def test_temporal_and_geographic_splits_and_detectors():
    df = pd.DataFrame({"t": pd.date_range("2016-01-01", periods=10, freq="365D"), "district": list("AABBCCDDEE"), "key": range(10)})
    sp = temporal_holdout(df, "t", date(2022, 1, 1))
    assert check_split(df, sp, time_col="t").ok
    bad = type(sp)("bad", np.array([0, 9]), np.array([1, 2]))
    assert not check_split(df, bad, time_col="t").ok
    g = group_holdout(df, "district", ["E"])
    assert check_split(df, g, group_col="district").ok
    leak = type(g)("leak", np.array([0, 1, 2]), np.array([1, 8]))
    rep = check_split(df, leak, group_col="district", id_cols=["key"])
    assert not rep.ok and any("both train and test" in p for p in rep.problems)


def test_feature_availability_check():
    df = pd.DataFrame({"pred_t": ["2025-09-15T00:00Z"], "ndvi_available": ["2025-09-20T00:00Z"]})
    assert not check_feature_availability(df, "pred_t", ["ndvi_available"]).ok


def test_metrics_hand_calculated_and_reproducible(tmp_path):
    pred = pd.DataFrame({"label": [1, 0, 1, 0, 1, 0], "flag": [1, 1, 0, 0, 1, 0], "score": [0.9, 0.8, 0.3, 0.2, 0.7, 0.1], "block": list("aabbcc")})
    pr = precision_recall(pred["label"], pred["flag"])
    assert pr["precision"] == pytest.approx(2 / 3) and pr["recall"] == pytest.approx(2 / 3)
    assert pr_auc(pred["label"], pred["score"]) == pytest.approx((1 + 2 / 3 + 3 / 4) / 3)  # precision at each positive: ranks 1, 3, 4
    m1 = metrics_from_table(pred, block_col="block")
    path = tmp_path / "pred.parquet"
    pred.to_parquet(path)
    m2 = metrics_from_table(pd.read_parquet(path), block_col="block")
    assert m1 == m2


def test_synthetic_rows_are_refused_by_real_reports():
    with pytest.raises(SyntheticDataError):
        assert_real_data(pd.DataFrame({"is_synthetic": [False, True]}), "test")
    assert_real_data(pd.DataFrame({"is_synthetic": [False]}), "test")

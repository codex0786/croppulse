"""NASA POWER parsing (real recorded response) and weather feature calculations."""

import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from croppulse.science.weather import compute_weather_features, window_total
from croppulse.sources.base import SourceSchemaError
from croppulse.sources.nasa_power import grid_cell_for, parse_power_payload
from tests.conftest import RECORDED


def test_real_power_response_parses_with_fill_as_nan():
    payload = json.loads((RECORDED / "power_daily_20260920_20261015.json").read_text())
    s = parse_power_payload(payload, grid_cell_for(20.0, 75.625), datetime.now(UTC), None, "u")
    assert s.units["PRECTOTCORR"] == "mm/day"
    assert s.time_standard == "LST"
    # The live response had trailing fill (-999) days: they must become NaN, never 0 or -999.
    assert not (s.frame == -999).any().any()
    assert s.frame["PRECTOTCORR"].isna().sum() >= 1
    assert s.last_valid_date is not None and s.last_valid_date < date(2026, 10, 15)


def test_power_unit_change_is_detected():
    payload = json.loads((RECORDED / "power_daily_20260920_20261015.json").read_text())
    payload["parameters"]["PRECTOTCORR"]["units"] = "kg m-2 s-1"
    with pytest.raises(SourceSchemaError):
        parse_power_payload(payload, grid_cell_for(20.0, 75.625), datetime.now(UTC), None, "u")


def test_grid_cell_snapping_hides_exact_location():
    c = grid_cell_for(19.8812345, 75.3398765)
    assert (c.lat, c.lon) == (20.0, 75.625)
    assert grid_cell_for(19.80, 75.40).key == c.key  # neighbours share a cell


def _frame(days: int, rain: float = 1.0, end: date = date(2026, 9, 30)) -> pd.DataFrame:
    idx = [end - timedelta(days=i) for i in range(days)][::-1]
    return pd.DataFrame({"PRECTOTCORR": [rain] * days, "T2M_MAX": [35.0] * days}, index=pd.Index(idx, name="date"))


def test_window_total_coverage_gate_and_no_zero_fill():
    f = _frame(30, rain=2.0)
    total, cov = window_total(f["PRECTOTCORR"], date(2026, 9, 30), 30, 0.9)
    assert total == pytest.approx(60.0) and cov == 1.0
    f.iloc[:5, 0] = np.nan
    total, cov = window_total(f["PRECTOTCORR"], date(2026, 9, 30), 30, 0.9)
    assert total is None and cov == pytest.approx(25 / 30)


def test_features_ignore_rows_after_as_of():
    f = _frame(40 * 365, rain=1.0)
    f.loc[date(2026, 9, 30), "PRECTOTCORR"] = 500.0  # a "future" spike relative to as_of
    feats = compute_weather_features(
        f, date(2026, 9, 29), windows=[7], reference_years=30, min_reference_years=20, min_coverage=0.9, rainy_day_mm=2.5, heat_tmax_c=40, heat_window_days=14
    )
    assert feats.window_end == date(2026, 9, 29)
    assert feats.rain_window(7).total_mm == pytest.approx(7.0)


def test_rain_percentile_deficit_and_dry_spell():
    end = date(2026, 9, 30)
    days = 35 * 365
    idx = [end - timedelta(days=i) for i in range(days)][::-1]
    rain = np.array([5.0 if d.month in (7, 8, 9) else 0.0 for d in idx])
    f = pd.DataFrame({"PRECTOTCORR": rain, "T2M_MAX": 33.0}, index=pd.Index(idx, name="date"))
    # Current year: no rain in the last 20 days.
    f.loc[[end - timedelta(days=i) for i in range(20)], "PRECTOTCORR"] = 0.0
    feats = compute_weather_features(
        f, end, windows=[30], reference_years=30, min_reference_years=20, min_coverage=0.9, rainy_day_mm=2.5, heat_tmax_c=40, heat_window_days=14
    )
    r = feats.rain_window(30)
    assert r.total_mm == pytest.approx(50.0) and r.reference_mean_mm == pytest.approx(150.0)
    assert r.percentile == pytest.approx(0.0) and r.deficit_pct == pytest.approx(-66.67, abs=0.01)
    assert feats.current_dry_spell_days == 20 and not feats.dry_spell_truncated
    assert feats.heat_days == 0 and feats.tmax_anomaly_c == pytest.approx(0.0)


def test_dry_season_suppresses_deficit():
    f = _frame(35 * 365, rain=0.0)
    feats = compute_weather_features(
        f, date(2026, 9, 30), windows=[30], reference_years=30, min_reference_years=20, min_coverage=0.9, rainy_day_mm=2.5, heat_tmax_c=40, heat_window_days=14
    )
    r = feats.rain_window(30)
    assert r.climatologically_dry and r.deficit_pct is None


def test_dry_spell_truncated_at_missing_day():
    f = _frame(30, rain=0.0)
    f.iloc[10, 0] = np.nan
    feats = compute_weather_features(
        f, date(2026, 9, 30), windows=[7], reference_years=30, min_reference_years=20, min_coverage=0.9, rainy_day_mm=2.5, heat_tmax_c=40, heat_window_days=14
    )
    assert feats.dry_spell_truncated and feats.current_dry_spell_days == 19

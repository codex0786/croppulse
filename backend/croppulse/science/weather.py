"""Weather-derived stress indicators from a daily series (NASA POWER).

Every feature is computed from rows with date <= as_of only; the effective
window end is the last day with valid precipitation on or before as_of
(the source's latency is reported, not hidden). Missing days are never filled
with zero: a window with coverage below ``min_window_coverage`` yields None.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from croppulse.science.anomaly import mid_rank_percentile


@dataclass
class RainWindow:
    days: int
    total_mm: float | None
    coverage: float
    reference_mean_mm: float | None
    reference_n: int
    percentile: float | None
    deficit_pct: float | None
    climatologically_dry: bool


@dataclass
class WeatherFeatures:
    as_of: date
    window_end: date | None
    data_age_days: int | None
    rain: list[RainWindow] = field(default_factory=list)
    current_dry_spell_days: int | None = None
    dry_spell_truncated: bool = False
    heat_days: int | None = None
    heat_window_days: int = 14
    heat_threshold_c: float = 40.0
    tmax_mean_recent_c: float | None = None
    tmax_reference_mean_c: float | None = None
    tmax_anomaly_c: float | None = None
    reference_years: list[int] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        d["window_end"] = self.window_end.isoformat() if self.window_end else None
        return d

    def rain_window(self, days: int) -> RainWindow | None:
        return next((r for r in self.rain if r.days == days), None)


def _same_day(year: int, d: date) -> date:
    try:
        return d.replace(year=year)
    except ValueError:  # 29 Feb in a non-leap year
        return date(year, 2, 28)


def window_total(series: pd.Series, end: date, days: int, min_coverage: float) -> tuple[float | None, float]:
    start = end - timedelta(days=days - 1)
    idx = pd.date_range(start, end, freq="D").date
    w = series.reindex(idx)
    coverage = float(w.notna().mean())
    if coverage < min_coverage:
        return None, coverage
    # Sum of observed days scaled to the full window would invent rain; we report the
    # observed sum and rely on the coverage gate to keep missingness small.
    return float(w.sum(skipna=True)), coverage


def compute_weather_features(
    frame: pd.DataFrame,
    as_of: date,
    *,
    windows: list[int],
    reference_years: int,
    min_reference_years: int,
    min_coverage: float,
    rainy_day_mm: float,
    heat_tmax_c: float,
    heat_window_days: int,
) -> WeatherFeatures:
    frame = frame[frame.index <= as_of]  # leakage guard: nothing after as_of
    rain = frame["PRECTOTCORR"] if "PRECTOTCORR" in frame else pd.Series(dtype=float)
    valid = rain.dropna()
    if valid.empty:
        return WeatherFeatures(as_of=as_of, window_end=None, data_age_days=None, flags=["no_valid_precipitation"])
    end: date = valid.index.max()
    feats = WeatherFeatures(as_of=as_of, window_end=end, data_age_days=(as_of - end).days)
    feats.heat_window_days, feats.heat_threshold_c = heat_window_days, heat_tmax_c
    ref_years = [y for y in range(end.year - reference_years, end.year)]
    feats.reference_years = ref_years

    for w in windows:
        total, cov = window_total(rain, end, w, min_coverage)
        refs = []
        for y in ref_years:
            t, _ = window_total(rain, _same_day(y, end), w, min_coverage)
            if t is not None:
                refs.append(t)
        rmean = float(np.mean(refs)) if refs else None
        dry = rmean is not None and rmean < max(1.0, rainy_day_mm * w / 30)
        pct = mid_rank_percentile(total, refs) if (total is not None and len(refs) >= min_reference_years) else None
        deficit = ((total - rmean) / rmean * 100.0) if (total is not None and rmean and not dry and len(refs) >= min_reference_years) else None
        feats.rain.append(RainWindow(w, total, cov, rmean, len(refs), pct, deficit, dry))
        if len(refs) < min_reference_years:
            feats.flags.append(f"rain_{w}d_reference_years_below_{min_reference_years}")

    # Current dry spell: consecutive days < rainy_day_mm ending at `end`; NaN stops the count.
    run = 0
    truncated = False
    d = end
    first = rain.index.min()
    while d >= first:
        v = rain.get(d, np.nan)
        if pd.isna(v):
            truncated = True
            break
        if v >= rainy_day_mm:
            break
        run += 1
        d -= timedelta(days=1)
    feats.current_dry_spell_days = run
    feats.dry_spell_truncated = truncated

    if "T2M_MAX" in frame:
        tmax = frame["T2M_MAX"]
        idx = pd.date_range(end - timedelta(days=heat_window_days - 1), end, freq="D").date
        recent = tmax.reindex(idx)
        if recent.notna().mean() >= min_coverage:
            feats.heat_days = int((recent >= heat_tmax_c).sum())
            feats.tmax_mean_recent_c = float(recent.mean())
            ref_means = []
            for y in ref_years:
                ye = _same_day(y, end)
                r = tmax.reindex(pd.date_range(ye - timedelta(days=heat_window_days - 1), ye, freq="D").date)
                if r.notna().mean() >= min_coverage:
                    ref_means.append(float(r.mean()))
            if len(ref_means) >= min_reference_years:
                feats.tmax_reference_mean_c = float(np.mean(ref_means))
                feats.tmax_anomaly_c = feats.tmax_mean_recent_c - feats.tmax_reference_mean_c
        else:
            feats.flags.append("tmax_coverage_insufficient")
    return feats

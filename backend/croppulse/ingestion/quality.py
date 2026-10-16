"""Data-quality checks. They return explicit warnings; they never silently drop records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pandas as pd


def check_vegetation_composites(composites: Sequence[Any]) -> list[str]:
    warnings: list[str] = []
    if not composites:
        return ["no_composites_returned"]
    starts = [c.period_start for c in composites]
    if len(starts) != len(set(starts)):
        warnings.append("duplicate_composite_periods")
    if starts != sorted(starts):
        warnings.append("composites_out_of_order")
    for a, b in zip(starts, starts[1:], strict=False):
        if a.year == b.year and (b - a) > timedelta(days=16):
            warnings.append(f"composite_gap:{a.isoformat()}..{b.isoformat()}")
    for c in composites:
        if c.ndvi is not None and not (-0.2 <= c.ndvi <= 1.0):
            warnings.append(f"ndvi_out_of_range:{c.period_start.isoformat()}")
        if c.published_at is not None and c.published_at.date() < c.period_start:
            warnings.append(f"published_before_period:{c.period_start.isoformat()}")
    accepted = sum(1 for c in composites if c.accepted)
    if accepted / len(composites) < 0.5:
        warnings.append(f"low_accepted_share:{accepted}/{len(composites)}")
    # Suspicious discontinuity: |ΔNDVI| > 0.5 between consecutive accepted composites ≤ 16 days apart
    acc = [c for c in composites if c.accepted and c.ndvi is not None]
    for a, b in zip(acc, acc[1:], strict=False):
        if (b.period_start - a.period_start).days <= 16 and abs(b.ndvi - a.ndvi) > 0.5:
            warnings.append(f"ndvi_discontinuity:{b.period_start.isoformat()}")
    return warnings


def check_weather_frame(frame: pd.DataFrame) -> list[str]:
    warnings: list[str] = []
    if frame.empty:
        return ["empty_weather_frame"]
    if frame.index.has_duplicates:
        warnings.append("duplicate_dates")
    if not frame.index.is_monotonic_increasing:
        warnings.append("dates_out_of_order")
    full = pd.date_range(min(frame.index), max(frame.index), freq="D").date
    missing_dates = len(full) - len(frame.index.unique())
    if missing_dates:
        warnings.append(f"missing_dates:{missing_dates}")
    precip = frame.get("PRECTOTCORR")
    if precip is not None:
        tail_nan = 0
        for v in precip.iloc[::-1]:
            if pd.isna(v):
                tail_nan += 1
            else:
                break
        if tail_nan:
            warnings.append(f"trailing_missing_days:{tail_nan}")
        body = precip.iloc[: len(precip) - tail_nan]
        if body.isna().mean() > 0.01:
            warnings.append(f"interior_missing_share:{body.isna().mean():.3f}")
    if {"T2M_MAX", "T2M_MIN"} <= set(frame.columns):
        inverted = (frame["T2M_MAX"] < frame["T2M_MIN"]).sum()
        if inverted:
            warnings.append(f"tmax_below_tmin_days:{int(inverted)}")
    return warnings

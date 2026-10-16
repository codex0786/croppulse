"""Historical backtest of the screening engine with simulated data availability.

Observations stored by CropPulse carry ``available_at`` = when CropPulse retrieved them.
For a historical replay that would hide every past composite, so the backtest assigns
each composite a *simulated* availability: ``period_end + assumed_latency_days``
(default 21 days; observed live latency on 2026-10-15 was ~16 days after period end).
Weather rows are truncated at ``as_of − weather_latency_days``. The engine itself then
excludes anything not yet available, and reference years are strictly earlier years.

Output: one row per (unit, as_of) with state, flag and a continuous score suitable for
PR-AUC once independent labels exist. Without labels only descriptive statistics
(alert burden, abstention rate) are valid.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pandas as pd

from croppulse.enums import RiskState
from croppulse.risk.engine import FieldContext, assess
from croppulse.science.anomaly import SeriesPoint


def simulate_availability(series: list[tuple[SeriesPoint, date, dict[str, Any]]], latency_days: int) -> list[tuple[SeriesPoint, date, dict[str, Any]]]:
    return [(replace(p, available_at=datetime.combine(end + timedelta(days=latency_days), time(0), tzinfo=UTC)), end, meta) for p, end, meta in series]


def backtest_unit(
    unit: str,
    ctx: FieldContext,
    series: list[tuple[SeriesPoint, date, dict[str, Any]]],
    weather: pd.DataFrame | None,
    as_of_dates: list[date],
    cfg: dict[str, Any],
    *,
    modis_latency_days: int = 21,
    weather_latency_days: int = 3,
) -> pd.DataFrame:
    sim = simulate_availability(series, modis_latency_days)
    rows = []
    for d in as_of_dates:
        as_of = datetime.combine(d, time(12), tzinfo=UTC)
        wx = weather[weather.index <= d - timedelta(days=weather_latency_days)] if weather is not None else None
        r = assess(ctx, sim, wx, as_of, cfg)
        latest = (r.vegetation or {}).get("latest") or {}
        rz = latest.get("robust_z")
        r30 = next((w for w in (r.weather or {}).get("rain", []) if w["days"] == 30), None)
        rows.append(
            {
                "unit": unit,
                "as_of": d,
                "state": r.state.value,
                "sufficiency": r.sufficiency.value,
                "flag_watch_or_higher": r.state in (RiskState.watch, RiskState.elevated_risk, RiskState.expert_review_recommended),
                "flag_elevated": r.state in (RiskState.elevated_risk, RiskState.expert_review_recommended),
                "score": -rz if rz is not None else None,
                "ndvi": latest.get("value"),
                "ndvi_robust_z": rz,
                "ndvi_z": latest.get("z"),
                "ndvi_percentile": latest.get("percentile"),
                "ndvi_reference_n": (latest.get("reference") or {}).get("n"),
                "veg_period_start": latest.get("period_start"),
                "veg_age_days": (r.vegetation or {}).get("age_days"),
                "rain30_percentile": r30.get("percentile") if r30 else None,
                "rain30_total_mm": r30.get("total_mm") if r30 else None,
                "dry_spell_days": (r.weather or {}).get("current_dry_spell_days"),
                **{f"ind_{k}": v for k, v in r.indicators.items()},
            }
        )
    return pd.DataFrame(rows)


def season_as_of_dates(years: list[int], months: tuple[int, ...] = (8, 9, 10), day: int = 15) -> list[date]:
    return [date(y, m, day) for y in years for m in months]

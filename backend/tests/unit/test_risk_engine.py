"""Evidence sufficiency gate and risk-state transitions (pure engine, no DB)."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from croppulse.config import science_config
from croppulse.enums import EvidenceSufficiency, RiskState
from croppulse.risk.engine import FieldContext, assess
from croppulse.science.anomaly import SeriesPoint

AS_OF = datetime(2026, 10, 15, 12, tzinfo=UTC)
T_AVAIL = datetime(2000, 1, 1, tzinfo=UTC)


def ctx(**kw):
    base = dict(
        field_id="f",
        crop="soybean",
        season="kharif",
        sowing_date=date(2026, 6, 25),
        sowing_date_uncertain=False,
        geometry_kind="polygon",
        land_cover_class=12,
        land_cover_year=2024,
    )
    base.update(kw)
    return FieldContext(**base)


def veg(target_values: dict[date, float | None], ref_value: float = 0.6, years=range(2010, 2026), spread=0.02):
    out = []
    for d in sorted(target_values):
        for i, y in enumerate(years):
            v = ref_value + spread * ((i % 5) - 2) / 2
            out.append(
                (
                    SeriesPoint(d.replace(year=y), v, True, T_AVAIL),
                    d.replace(year=y) + timedelta(days=15),
                    {"valid_fraction": 1.0, "selection_rule": "pixel_center_in_polygon"},
                )
            )
        v = target_values[d]
        out.append(
            (
                SeriesPoint(d, v, v is not None, T_AVAIL),
                d + timedelta(days=15),
                {"valid_fraction": 1.0 if v is not None else 0.0, "selection_rule": "pixel_center_in_polygon"},
            )
        )
    return out


def weather(rain_last_days: float = 5.0, end: date = date(2026, 10, 10), tmax=33.0):
    days = 35 * 365
    idx = [end - timedelta(days=i) for i in range(days)][::-1]
    rain = [5.0 if (end - d).days >= 60 or d.year < end.year else rain_last_days for d in idx]
    return pd.DataFrame({"PRECTOTCORR": rain, "T2M_MAX": tmax}, index=pd.Index(idx, name="date"))


RECENT = {date(2026, 8, 29): 0.6, date(2026, 9, 14): 0.6}
LOW = {date(2026, 8, 29): 0.35, date(2026, 9, 14): 0.33}


def test_normal_when_evidence_is_complete_and_unremarkable():
    r = assess(ctx(), veg(RECENT), weather(5.0), AS_OF, science_config())
    assert r.state == RiskState.normal_for_reference_period
    assert r.sufficiency in (EvidenceSufficiency.sufficient, EvidenceSufficiency.partial)
    assert r.uncertainty["probability"] is None


def test_elevated_requires_persistent_vegetation_and_weather():
    r = assess(ctx(), veg(LOW), weather(0.0), AS_OF, science_config())
    assert r.indicators["vegetation_low_persistent"] and r.indicators["rain_deficit"]
    assert r.state == RiskState.elevated_risk
    assert r.escalate_to_expert  # unvalidated model → expert
    keys = [e["key"] for e in r.explanations]
    assert "expl_vegetation_below_reference" in keys and "expl_low_greenness_alternatives" in keys and "expl_rain_30d_low" in keys


def test_low_vegetation_without_weather_is_only_watch():
    r = assess(ctx(), veg(LOW), weather(5.0), AS_OF, science_config())
    assert r.state == RiskState.watch


def test_unknown_crop_blocks():
    r = assess(ctx(crop=None), veg(LOW), weather(0.0), AS_OF, science_config())
    assert r.state == RiskState.insufficient_evidence and r.sufficiency == EvidenceSufficiency.insufficient


def test_missing_vegetation_never_reads_as_healthy():
    r = assess(ctx(), [], weather(5.0), AS_OF, science_config())
    assert r.state == RiskState.insufficient_evidence
    r2 = assess(ctx(), veg({date(2026, 9, 14): None}), weather(5.0), AS_OF, science_config())
    assert r2.state == RiskState.insufficient_evidence


def test_stale_vegetation_is_not_used():
    old = {date(2026, 6, 26): 0.30, date(2026, 7, 12): 0.30}
    r = assess(ctx(), veg(old), weather(5.0), AS_OF, science_config())
    assert r.freshness["vegetation"]["status"] == "stale"
    assert r.state == RiskState.insufficient_evidence


def test_stale_weather_and_no_vegetation_is_insufficient():
    r = assess(ctx(), [], weather(0.0, end=date(2026, 8, 1)), AS_OF, science_config())
    assert r.state == RiskState.insufficient_evidence


def test_non_cropland_pixel_downgrades():
    r = assess(ctx(land_cover_class=13), veg(LOW), weather(0.0), AS_OF, science_config())
    assert r.state == RiskState.watch  # weather signal only; vegetation unrepresentative
    assert any(c.id == "pixel_is_cropland" and not c.passed for c in r.checks)


def test_farmer_report_routes_to_expert():
    r = assess(ctx(open_farmer_report=True), veg(LOW), weather(5.0), AS_OF, science_config())
    assert r.state == RiskState.expert_review_recommended and r.escalate_to_expert


def test_future_observations_are_ignored():
    future = veg({date(2026, 9, 14): 0.6})
    future.append((SeriesPoint(date(2026, 9, 30), 0.1, True, AS_OF + timedelta(days=5)), date(2026, 10, 15), {"valid_fraction": 1.0, "selection_rule": "x"}))
    r = assess(ctx(), future, weather(5.0), AS_OF, science_config())
    assert r.vegetation["latest_period_end"] == "2026-09-29"


@pytest.mark.parametrize("state_kw", [{}, {"open_farmer_report": True}])
def test_guidance_is_always_process_only(state_kw):
    r = assess(ctx(**state_kw), veg(LOW), weather(0.0), AS_OF, science_config())
    assert r.guidance_ids and all(g.startswith(("next_step_", "symptom_")) for g in r.guidance_ids)

"""Risk engine: evidence → sufficiency gate → screening state → explanation → next step.

This is a transparent, rule-based SCREENING model ("screening-rules"), not a
calibrated probability model. Its thresholds live in config/science.yaml and are
unvalidated (risk.model_validated=false). Consequences of that status:
  * the output never contains a probability;
  * elevated states are routed to an expert (escalate_to_expert=True);
  * farmer-facing guidance is limited to approved process guidance.

The engine is pure: it takes already-loaded inputs and returns an AssessmentResult,
so it can be backtested on historical as_of dates without touching the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from croppulse.enums import EvidenceSufficiency, Freshness, RiskState
from croppulse.guidance.library import approved_ids_for_state
from croppulse.science.anomaly import AnomalyResult, AnomalyStatus, SeriesPoint, compute_anomaly, low_persistence
from croppulse.science.weather import WeatherFeatures, compute_weather_features

MODEL_NAME = "screening-rules"
MODEL_VERSION = "0.1.0"

NEXT_STEP = {
    RiskState.insufficient_evidence: "next_step_insufficient",
    RiskState.normal_for_reference_period: "next_step_normal",
    RiskState.watch: "next_step_watch",
    RiskState.elevated_risk: "next_step_elevated",
    RiskState.expert_review_recommended: "next_step_elevated",
    RiskState.verified_stress: "next_step_verified",
    RiskState.resolved: "next_step_verified",
}


@dataclass
class FieldContext:
    field_id: str
    crop: str | None
    season: str | None
    sowing_date: date | None
    sowing_date_uncertain: bool
    geometry_kind: str  # polygon | point
    land_cover_class: int | None
    land_cover_year: int | None
    open_farmer_report: bool = False
    expert_verified_state: RiskState | None = None


@dataclass
class Check:
    id: str
    passed: bool
    severity: str  # blocking | degrading | info
    detail: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssessmentResult:
    as_of: datetime
    state: RiskState
    sufficiency: EvidenceSufficiency
    checks: list[Check]
    vegetation: dict[str, Any]
    weather: dict[str, Any]
    soil_moisture: dict[str, Any]
    context: dict[str, Any]
    freshness: dict[str, Any]
    input_periods: dict[str, Any]
    explanations: list[dict[str, Any]]
    uncertainty: dict[str, Any]
    next_step_key: str
    guidance_ids: list[str]
    escalate_to_expert: bool
    model_validated: bool
    expires_at: datetime
    indicators: dict[str, bool]


def _iso(d: date | datetime | None) -> str | None:
    return d.isoformat() if d else None


def _anomaly_dict(a: AnomalyResult | None) -> dict[str, Any] | None:
    if a is None:
        return None
    r = a.reference
    return {
        "period_start": _iso(a.period_start),
        "value": a.value,
        "status": a.status.value,
        "z": a.z,
        "robust_z": a.robust_z,
        "robust_z_interval_5_95": list(a.robust_z_interval) if a.robust_z_interval else None,
        "percentile": a.percentile,
        "reference": {
            "n": r.n,
            "years": r.years,
            "mean": r.mean,
            "std": r.std,
            "median": r.median,
            "mad_scaled": r.mad_scaled,
            "p10": r.p10,
            "p90": r.p90,
        },
        "flags": a.flags,
    }


def assess(
    ctx: FieldContext,
    vegetation_series: list[tuple[SeriesPoint, date, dict[str, Any]]],
    weather_frame: pd.DataFrame | None,
    as_of: datetime,
    cfg: dict[str, Any],
    *,
    soil_moisture_status: str = "not_configured",
) -> AssessmentResult:
    """Run the screening assessment.

    vegetation_series: list of (point, period_end, meta) where meta has valid_fraction,
    selection_rule; points must already be filtered to the current revision.
    """
    vcfg, wcfg, lcfg, rcfg = cfg["vegetation"], cfg["weather"], cfg["land_cover"], cfg["risk"]
    model_validated = bool(rcfg.get("model_validated", False))
    checks: list[Check] = []
    explanations: list[dict[str, Any]] = []
    indicators = {
        "vegetation_low_persistent": False,
        "vegetation_low_single": False,
        "rain_deficit": False,
        "dry_spell": False,
        "heat": False,
    }
    as_of_date = as_of.astimezone(UTC).date()

    # ---------------------------------------------------------------- context
    crop_known = bool(ctx.crop and ctx.season)
    checks.append(Check("crop_season_known", crop_known, "blocking", "crop_and_season_recorded" if crop_known else "crop_or_season_missing"))
    das = (as_of_date - ctx.sowing_date).days if ctx.sowing_date else None
    if ctx.sowing_date is None:
        checks.append(Check("sowing_date_known", False, "info", "sowing_date_missing"))
        explanations.append({"key": "expl_sowing_unknown", "kind": "farmer_reported", "params": {}})
    elif ctx.sowing_date_uncertain:
        checks.append(Check("sowing_date_known", True, "info", "sowing_date_uncertain"))

    cropland_classes = set(lcfg["cropland_classes"])
    lc_ok = ctx.land_cover_class in cropland_classes if ctx.land_cover_class is not None else None
    if lc_ok is False:
        checks.append(Check("pixel_is_cropland", False, "degrading", "land_cover_not_cropland", {"class": ctx.land_cover_class, "year": ctx.land_cover_year}))
        explanations.append(
            {
                "key": "expl_land_cover_not_cropland",
                "kind": "observed",
                "params": {"class": ctx.land_cover_class, "year": ctx.land_cover_year},
                "source": "modis_mcd12q1",
            }
        )
    elif lc_ok is None:
        checks.append(Check("pixel_is_cropland", False, "info", "land_cover_unknown"))

    # ---------------------------------------------------------------- vegetation
    usable = [(p, end, meta) for p, end, meta in vegetation_series if p.available_at <= as_of and p.period_start <= as_of_date]
    points = [p for p, _, _ in usable]
    latest_accepted = next(((p, end, meta) for p, end, meta in sorted(usable, key=lambda t: t[0].period_start, reverse=True) if p.accepted), None)
    latest_any = max(usable, key=lambda t: t[0].period_start) if usable else None
    veg: dict[str, Any] = {"index": vcfg["index"], "source": "modis_mod13q1", "status": "unavailable"}
    veg_fresh = False
    veg_reliable = False
    latest_anom: AnomalyResult | None = None
    if latest_accepted is None:
        checks.append(Check("vegetation_available", False, "degrading", "no_accepted_composite"))
        explanations.append({"key": "expl_vegetation_unavailable", "kind": "derived", "params": {}})
    else:
        p, end, meta = latest_accepted
        age = (as_of_date - end).days
        veg_fresh = age <= vcfg["max_age_days_for_assessment"]
        checks.append(
            Check(
                "vegetation_fresh",
                veg_fresh,
                "degrading",
                "vegetation_fresh" if veg_fresh else "vegetation_stale",
                {"period_end": end.isoformat(), "age_days": age},
            )
        )
        # recent anomalies (last ~4 composites) for persistence
        recent = sorted([q for q in points if q.period_start <= p.period_start], key=lambda q: q.period_start, reverse=True)[:4]
        anoms = [
            compute_anomaly(
                points,
                q,
                as_of,
                n_years=vcfg["reference_years"],
                min_samples=vcfg["min_reference_samples"],
                variance_floor=vcfg["variance_floor"],
                pool=vcfg["pool_adjacent_composites"],
            )
            for q in recent
        ]
        latest_anom = next((a for a in anoms if a.period_start == p.period_start), None)
        persistence = low_persistence(anoms, vcfg["low_anomaly_robust_z"], vcfg["low_anomaly_percentile"])
        ref_ok = latest_anom is not None and latest_anom.status == AnomalyStatus.ok
        checks.append(
            Check(
                "vegetation_reference_sufficient",
                ref_ok,
                "degrading",
                latest_anom.status.value if latest_anom else "missing",
                {"n": latest_anom.reference.n if latest_anom else 0, "min": vcfg["min_reference_samples"]},
            )
        )
        vf = meta.get("valid_fraction")
        rule = meta.get("selection_rule")
        quality_ok = vf is not None and vf >= vcfg["min_valid_pixel_fraction"]
        checks.append(Check("vegetation_quality", quality_ok, "degrading", "valid_pixel_fraction", {"valid_fraction": vf}))
        if rule == "pixel_containing_centroid" or ctx.geometry_kind == "point":
            checks.append(Check("field_resolved_by_pixels", False, "degrading", "single_pixel_represents_field"))
            explanations.append({"key": "expl_coarse_resolution", "kind": "derived", "params": {}, "source": "modis_mod13q1"})
        veg_reliable = veg_fresh and ref_ok and quality_ok and lc_ok is not False
        if latest_anom is not None and latest_anom.status == AnomalyStatus.ok and latest_anom.robust_z is not None:
            low_now = (
                latest_anom.robust_z <= vcfg["low_anomaly_robust_z"]
                and latest_anom.percentile is not None
                and latest_anom.percentile <= vcfg["low_anomaly_percentile"]
            )
            if veg_reliable:
                indicators["vegetation_low_single"] = low_now
                indicators["vegetation_low_persistent"] = persistence.consecutive_low >= vcfg["persistence_composites"]
            if low_now:
                explanations.append(
                    {
                        "key": "expl_vegetation_below_reference",
                        "kind": "derived",
                        "source": "modis_mod13q1",
                        "params": {
                            "index": vcfg["index"],
                            "value": round(latest_anom.value or 0, 3),
                            "percentile": round(latest_anom.percentile or 0, 1),
                            "reference_years": f"{min(latest_anom.reference.years)}–{max(latest_anom.reference.years)}",
                            "n": latest_anom.reference.n,
                            "period_start": p.period_start.isoformat(),
                            "period_end": end.isoformat(),
                            "consecutive": persistence.consecutive_low,
                        },
                    }
                )
                explanations.append({"key": "expl_low_greenness_alternatives", "kind": "derived", "params": {}})
            else:
                explanations.append(
                    {
                        "key": "expl_vegetation_within_reference",
                        "kind": "derived",
                        "source": "modis_mod13q1",
                        "params": {
                            "index": vcfg["index"],
                            "percentile": round(latest_anom.percentile or 0, 1),
                            "period_start": p.period_start.isoformat(),
                            "period_end": end.isoformat(),
                            "n": latest_anom.reference.n,
                        },
                    }
                )
        explanations.append(
            {
                "key": "expl_latest_composite",
                "kind": "observed",
                "source": "modis_mod13q1",
                "params": {"period_start": p.period_start.isoformat(), "period_end": end.isoformat(), "age_days": age},
            }
        )
        veg = {
            "index": vcfg["index"],
            "source": "modis_mod13q1",
            "status": "current" if veg_fresh else "stale",
            "latest": _anomaly_dict(latest_anom),
            "latest_period_end": end.isoformat(),
            "age_days": age,
            "valid_fraction": vf,
            "selection_rule": rule,
            "persistence": {"consecutive_low": persistence.consecutive_low, "gap_break": persistence.gap_break},
            "reliable_for_screening": veg_reliable,
            "latest_composite_any_quality": latest_any[0].period_start.isoformat() if latest_any else None,
        }

    # ---------------------------------------------------------------- weather
    wx: dict[str, Any] = {"source": "nasa_power_daily", "status": "unavailable"}
    wx_fresh = False
    feats: WeatherFeatures | None = None
    if weather_frame is not None and not weather_frame.empty:
        feats = compute_weather_features(
            weather_frame,
            as_of_date,
            windows=wcfg["rain_windows_days"],
            reference_years=wcfg["reference_years"],
            min_reference_years=wcfg["min_reference_years"],
            min_coverage=wcfg["min_window_coverage"],
            rainy_day_mm=wcfg["rainy_day_mm"],
            heat_tmax_c=wcfg["heat_tmax_c"],
            heat_window_days=wcfg["heat_window_days"],
        )
    if feats is None or feats.window_end is None:
        checks.append(Check("weather_available", False, "degrading", "no_weather_data"))
        explanations.append({"key": "expl_weather_unavailable", "kind": "derived", "params": {}})
    else:
        wx_fresh = (feats.data_age_days or 0) <= wcfg["max_age_days_for_assessment"]
        checks.append(
            Check(
                "weather_fresh",
                wx_fresh,
                "degrading",
                "weather_fresh" if wx_fresh else "weather_stale",
                {"window_end": feats.window_end.isoformat(), "age_days": feats.data_age_days},
            )
        )
        r30 = feats.rain_window(30)
        if wx_fresh and r30 and r30.percentile is not None and not r30.climatologically_dry:
            indicators["rain_deficit"] = r30.percentile <= wcfg["deficit_percentile"]
            explanations.append(
                {
                    "key": "expl_rain_30d_low" if indicators["rain_deficit"] else "expl_rain_30d_context",
                    "kind": "derived",
                    "source": "nasa_power_daily",
                    "params": {
                        "total_mm": round(r30.total_mm or 0, 1),
                        "reference_mean_mm": round(r30.reference_mean_mm or 0, 1),
                        "percentile": round(r30.percentile, 1),
                        "window_end": feats.window_end.isoformat(),
                        "reference_years": f"{feats.reference_years[0]}–{feats.reference_years[-1]}",
                    },
                }
            )
        elif r30 and r30.climatologically_dry:
            explanations.append(
                {"key": "expl_rain_dry_season", "kind": "derived", "source": "nasa_power_daily", "params": {"window_end": feats.window_end.isoformat()}}
            )
        if wx_fresh and feats.current_dry_spell_days is not None and r30 and not r30.climatologically_dry:
            indicators["dry_spell"] = feats.current_dry_spell_days >= wcfg["dry_spell_trigger_days"]
            if indicators["dry_spell"]:
                explanations.append(
                    {
                        "key": "expl_dry_spell",
                        "kind": "derived",
                        "source": "nasa_power_daily",
                        "params": {"days": feats.current_dry_spell_days, "threshold_mm": wcfg["rainy_day_mm"], "lower_bound": feats.dry_spell_truncated},
                    }
                )
        if wx_fresh and feats.heat_days is not None:
            indicators["heat"] = feats.heat_days >= wcfg["heat_days_trigger"]
            if indicators["heat"]:
                explanations.append(
                    {
                        "key": "expl_heat_days",
                        "kind": "derived",
                        "source": "nasa_power_daily",
                        "params": {"days": feats.heat_days, "threshold_c": wcfg["heat_tmax_c"], "window_days": wcfg["heat_window_days"]},
                    }
                )
        wx = {"source": "nasa_power_daily", "status": "current" if wx_fresh else "stale", **feats.to_dict()}

    # ---------------------------------------------------------------- soil moisture
    sm = {"status": soil_moisture_status, "source": "smap_l4"}
    explanations.append({"key": "expl_soil_moisture_unavailable", "kind": "derived", "params": {"status": soil_moisture_status}})

    # ---------------------------------------------------------------- decision
    weather_signal = indicators["rain_deficit"] or indicators["dry_spell"] or indicators["heat"]
    independent = sum([veg_reliable, wx_fresh])
    checks.append(Check("independent_indicators", independent >= 2, "degrading", "independent_sources", {"count": independent}))
    checks.append(Check("model_validated", model_validated, "degrading", "model_validated" if model_validated else "model_not_validated"))

    if not crop_known or not veg_reliable and not wx_fresh:
        state = RiskState.insufficient_evidence
    elif not veg_reliable:
        # Missing or unreliable vegetation must never read as "healthy".
        state = RiskState.watch if weather_signal else RiskState.insufficient_evidence
    elif indicators["vegetation_low_persistent"] and weather_signal:
        state = RiskState.elevated_risk
    elif indicators["vegetation_low_persistent"] or indicators["vegetation_low_single"] or weather_signal:
        state = RiskState.watch
    else:
        state = RiskState.normal_for_reference_period

    if ctx.open_farmer_report and state in (RiskState.watch, RiskState.elevated_risk):
        state = RiskState.expert_review_recommended
        explanations.append({"key": "expl_farmer_report_open", "kind": "farmer_reported", "params": {}})
    if ctx.expert_verified_state is not None:
        state = ctx.expert_verified_state
        explanations.append({"key": "expl_expert_verified", "kind": "expert_verified", "params": {}})

    blocking_failed = any(c.severity == "blocking" and not c.passed for c in checks)
    degrading_failed = sum(1 for c in checks if c.severity == "degrading" and not c.passed and c.id != "model_validated")
    if blocking_failed or state == RiskState.insufficient_evidence:
        sufficiency = EvidenceSufficiency.insufficient
    elif degrading_failed:
        sufficiency = EvidenceSufficiency.partial
    else:
        sufficiency = EvidenceSufficiency.sufficient

    escalate = state in (RiskState.elevated_risk, RiskState.expert_review_recommended) or (
        state == RiskState.watch and not model_validated and indicators["vegetation_low_persistent"]
    )

    freshness = {
        "vegetation": {
            "status": (Freshness.current if veg_fresh else Freshness.stale) if latest_accepted else Freshness.unavailable,
            "period_end": veg.get("latest_period_end"),
            "age_days": veg.get("age_days"),
            "max_age_days": vcfg["max_age_days_for_assessment"],
        },
        "weather": {
            "status": (Freshness.current if wx_fresh else Freshness.stale) if feats and feats.window_end else Freshness.unavailable,
            "window_end": _iso(feats.window_end) if feats else None,
            "age_days": feats.data_age_days if feats else None,
            "max_age_days": wcfg["max_age_days_for_assessment"],
        },
        "soil_moisture": {"status": Freshness.unavailable},
    }
    uncertainty = {
        "statement_key": "uncertainty_screening_unvalidated" if not model_validated else "uncertainty_validated",
        "probability": None,
        "reference_n": latest_anom.reference.n if latest_anom else 0,
        "robust_z_interval_5_95": list(latest_anom.robust_z_interval) if latest_anom and latest_anom.robust_z_interval else None,
        "valid_pixel_fraction": veg.get("valid_fraction"),
        "pixel_rule": veg.get("selection_rule"),
        "model_validated": model_validated,
    }
    guidance_ids = approved_ids_for_state(state)
    if any(e["key"] == "expl_vegetation_below_reference" for e in explanations) or ctx.open_farmer_report:
        guidance_ids.append("symptom_not_diagnosis")
    if not any(c.id == "guidance_available" for c in checks):
        checks.append(Check("guidance_available", bool(guidance_ids), "info", "approved_guidance" if guidance_ids else "no_approved_guidance"))
    return AssessmentResult(
        as_of=as_of,
        state=state,
        sufficiency=sufficiency,
        checks=checks,
        vegetation=veg,
        weather=wx,
        soil_moisture=sm,
        context={
            "crop": ctx.crop,
            "season": ctx.season,
            "sowing_date": _iso(ctx.sowing_date),
            "sowing_date_uncertain": ctx.sowing_date_uncertain,
            "days_after_sowing": das,
            "land_cover_class": ctx.land_cover_class,
            "land_cover_year": ctx.land_cover_year,
            "geometry_kind": ctx.geometry_kind,
        },
        freshness={k: {kk: (vv.value if hasattr(vv, "value") else vv) for kk, vv in v.items()} for k, v in freshness.items()},
        input_periods={
            "vegetation_period": [veg.get("latest", {}) and veg["latest"]["period_start"], veg.get("latest_period_end")] if latest_accepted else None,
            "weather_window_end": _iso(feats.window_end) if feats else None,
        },
        explanations=explanations,
        uncertainty=uncertainty,
        next_step_key=NEXT_STEP[state],
        guidance_ids=guidance_ids,
        escalate_to_expert=escalate,
        model_validated=model_validated,
        expires_at=as_of + timedelta(days=int(rcfg["assessment_ttl_days"])),
        indicators=indicators,
    )

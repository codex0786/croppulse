"""Assessment service: load evidence from storage, run the engine, persist, alert, escalate."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from croppulse.alerting.engine import AlertDecision, evaluate_assessment
from croppulse.config import config_version, get_settings, science_config
from croppulse.db import utcnow
from croppulse.enums import CaseStatus, ConsentPurpose, RiskState, SourceStatus, VerifiedFinding
from croppulse.governance import latest_consent
from croppulse.ingestion.jobs import load_weather_frame
from croppulse.models import CaseEvent, CropSeason, DataSource, ExpertCase, FarmerReport, Field, Observation, RiskAssessment, VerifiedOutcome
from croppulse.risk.engine import MODEL_NAME, MODEL_VERSION, AssessmentResult, FieldContext, assess
from croppulse.science.anomaly import SeriesPoint
from croppulse.sources.earthdata import SmapAdapter


def active_season(field: Field) -> CropSeason | None:
    act = [s for s in field.seasons if s.active]
    return act[-1] if act else None


def vegetation_series(session: Session, field_id: str, variable: str = "NDVI") -> list[tuple[SeriesPoint, Any, dict[str, Any]]]:
    rows = session.scalars(
        select(Observation)
        .where(Observation.field_id == field_id, Observation.variable == variable, Observation.source_id == "modis_mod13q1", Observation.is_current.is_(True))
        .order_by(Observation.period_start)
    ).all()
    return [
        (
            SeriesPoint(o.period_start, o.value, o.accepted, o.available_at),
            o.period_end,
            {"valid_fraction": o.valid_fraction, "selection_rule": (o.quality_summary or {}).get("selection_rule"), "is_synthetic": o.is_synthetic},
        )
        for o in rows
    ]


def build_context(session: Session, field: Field, as_of: datetime) -> FieldContext:
    season = active_season(field)
    lc = session.scalars(
        select(Observation)
        .where(Observation.field_id == field.id, Observation.variable == "LC_Type1", Observation.is_current.is_(True))
        .order_by(Observation.period_start.desc())
    ).first()
    open_report = session.scalars(
        select(ExpertCase.id).where(ExpertCase.field_id == field.id, ExpertCase.report_id.is_not(None), ExpertCase.status.not_in([CaseStatus.closed, CaseStatus.verified]))
    ).first()
    verified_state: RiskState | None = None
    vo = session.scalars(select(VerifiedOutcome).where(VerifiedOutcome.field_id == field.id).order_by(VerifiedOutcome.verified_at.desc())).first()
    if vo is not None and (as_of - vo.verified_at).days <= science_config()["risk"]["assessment_ttl_days"]:
        verified_state = RiskState.verified_stress if vo.finding == VerifiedFinding.stress_confirmed else None
    return FieldContext(
        field_id=field.id,
        crop=season.crop if season else None,
        season=season.season if season else None,
        sowing_date=season.sowing_date if season else None,
        sowing_date_uncertain=season.sowing_date_uncertain if season else False,
        geometry_kind="point" if field.geometry_source == "point" else "polygon",
        land_cover_class=int(lc.value) if lc and lc.value is not None else None,
        land_cover_year=lc.period_start.year if lc else None,
        open_farmer_report=open_report is not None,
        expert_verified_state=verified_state,
    )


def run_assessment(session: Session, field: Field, as_of: datetime | None = None) -> tuple[RiskAssessment, AlertDecision, AssessmentResult]:
    as_of = as_of or utcnow()
    cfg = science_config()
    ctx = build_context(session, field, as_of)
    series = vegetation_series(session, field.id)
    weather, dv = load_weather_frame(session, field.centroid_lat, field.centroid_lon)
    sm_status = SmapAdapter().status().value
    result = assess(ctx, series, weather, as_of, cfg, soil_moisture_status=sm_status)
    season = active_season(field)
    is_synth = field.is_synthetic or bool(dv and dv.is_synthetic) or any(meta.get("is_synthetic") for _, _, meta in series)
    ra = RiskAssessment(
        field_id=field.id,
        crop_season_id=season.id if season else None,
        as_of=as_of,
        state=result.state.value,
        sufficiency=result.sufficiency.value,
        sufficiency_checks=[c.__dict__ for c in result.checks],
        vegetation=result.vegetation,
        weather=result.weather,
        soil_moisture=result.soil_moisture,
        context=result.context,
        freshness=result.freshness,
        input_periods=result.input_periods,
        explanations=result.explanations,
        uncertainty=result.uncertainty,
        next_step_key=result.next_step_key,
        guidance_ids=result.guidance_ids,
        escalate_to_expert=result.escalate_to_expert,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        model_validated=result.model_validated,
        config_version=config_version(get_settings().science_config_path),
        expires_at=result.expires_at,
        is_synthetic=is_synth,
    )
    session.add(ra)
    session.flush()
    decision = evaluate_assessment(session, ra, field, now=as_of if as_of <= utcnow() else None)
    if result.escalate_to_expert:
        escalate(session, field, ra)
    session.commit()
    return ra, decision, result


def escalate(session: Session, field: Field, ra: RiskAssessment) -> ExpertCase | None:
    """Open (or update) an expert case for an escalated assessment — only with expert_review consent."""
    if not latest_consent(session, field.owner_id, ConsentPurpose.expert_review):
        return None
    case = session.scalars(
        select(ExpertCase).where(ExpertCase.field_id == field.id, ExpertCase.status.not_in([CaseStatus.closed, CaseStatus.verified]))
    ).first()
    if case is None:
        case = ExpertCase(
            field_id=field.id,
            organization_id=field.organization_id,
            assessment_id=ra.id,
            origin="assessment_escalation",
            status=CaseStatus.open,
            priority=1 if ra.state in (RiskState.elevated_risk, RiskState.expert_review_recommended) else 2,
        )
        session.add(case)
        session.flush()
    else:
        case.assessment_id = ra.id
        case.updated_at = utcnow()
    session.add(CaseEvent(case_id=case.id, actor_id=field.owner_id, kind="system_assessment", authored_by="system", data={"assessment_id": ra.id, "state": ra.state}))
    return case


def open_report_case(session: Session, field: Field, report: FarmerReport) -> ExpertCase:
    case = session.scalars(
        select(ExpertCase).where(ExpertCase.field_id == field.id, ExpertCase.status.not_in([CaseStatus.closed, CaseStatus.verified]))
    ).first()
    if case is None:
        case = ExpertCase(field_id=field.id, organization_id=field.organization_id, report_id=report.id, origin="farmer_request", status=CaseStatus.open, priority=2)
        session.add(case)
        session.flush()
    else:
        case.report_id = report.id
        case.updated_at = utcnow()
    session.add(CaseEvent(case_id=case.id, actor_id=report.reporter_id, kind="farmer_report", authored_by="human", data={"report_id": report.id, "symptoms": report.symptoms}))
    return case


def source_statuses(session: Session) -> dict[str, str]:
    return {ds.id: ds.status for ds in session.scalars(select(DataSource)).all()} | {
        "smap_l4": SmapAdapter().status().value,
        "gpm_imerg": SourceStatus.not_configured.value if not get_settings().earthdata_token else SourceStatus.implemented_untested.value,
    }

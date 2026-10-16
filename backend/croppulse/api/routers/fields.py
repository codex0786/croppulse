from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from croppulse.api.deps import current_user, db, readable_field, writable_field
from croppulse.api.presenters import assessment_out
from croppulse.config import get_settings, load_yaml, science_config
from croppulse.db import get_sessionmaker, utcnow
from croppulse.enums import ConsentPurpose, Role
from croppulse.geo.geometry import GeometryError, validate_field_geometry
from croppulse.governance import audit, latest_consent, record_consent
from croppulse.ingestion.jobs import ingest_field, load_weather_frame
from croppulse.logging_setup import log
from croppulse.models import CropSeason, Field, IngestionJob, Observation, RiskAssessment, User
from croppulse.risk.service import run_assessment
from croppulse.schemas import (
    AssessmentOut,
    BoundaryCheckIn,
    BoundaryCheckOut,
    FieldCreate,
    FieldOut,
    FieldSummary,
    SeasonIn,
    SeasonOut,
    VegetationPoint,
    VegetationSeriesOut,
    WeatherDaily,
    WeatherOut,
)
from croppulse.science.anomaly import SeriesPoint, reference_sample, reference_stats
from croppulse.sources.nasa_power import grid_cell_for

router = APIRouter(prefix="/api/v1/fields", tags=["fields"])
logger = logging.getLogger(__name__)


def _calendar() -> dict[str, Any]:
    return load_yaml(str(get_settings().crop_calendar_path))


def _field_out(field: Field, user: User) -> FieldOut:
    out = FieldOut.model_validate(field)
    out.is_owner = field.owner_id == user.id
    return out


def _validate_season(season: SeasonIn) -> None:
    crops = _calendar()["crops"]
    if season.crop not in crops:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown crop '{season.crop}'. Use one of: {', '.join(crops)}")
    if season.season.value not in crops[season.crop]["seasons"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{season.crop} is not configured for the {season.season.value} season")


@router.get("/reference-data")
def reference_data() -> dict[str, Any]:
    cal = _calendar()
    return {
        "crops": {k: v["seasons"] for k, v in cal["crops"].items()},
        "districts": cal["maharashtra_districts"],
        "crop_calendar_reviewed": cal.get("reviewed", False),
        "seasons": ["kharif", "rabi", "zaid", "annual"],
        "irrigation": ["rainfed", "partially_irrigated", "irrigated", "unknown"],
    }


@router.post("/validate-boundary", response_model=BoundaryCheckOut)
def validate_boundary(body: BoundaryCheckIn, user: User = Depends(current_user)) -> BoundaryCheckOut:
    try:
        g = validate_field_geometry(body.geometry)
    except GeometryError as exc:
        return BoundaryCheckOut(valid=False, error=str(exc))
    return BoundaryCheckOut(valid=True, area_ha=g.area_ha, kind=g.kind, warnings=g.warnings)


@router.post("", response_model=FieldOut, status_code=201)
def create_field(body: FieldCreate, user: User = Depends(current_user), session: Session = Depends(db)) -> FieldOut:
    if user.role != Role.farmer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only farmer accounts register fields")
    if body.district not in _calendar()["maharashtra_districts"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "District must be one of the supported Maharashtra districts")
    _validate_season(body.season)
    try:
        g = validate_field_geometry(body.geometry)
    except GeometryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    field = Field(
        owner_id=user.id,
        organization_id=user.organization_id,
        name=body.name,
        state=body.state,
        district=body.district,
        geometry_geojson=g.geojson,
        geometry_source="point" if g.kind == "point" else "drawn",
        centroid_lat=g.centroid_lat,
        centroid_lon=g.centroid_lon,
        min_lon=g.bbox[0],
        min_lat=g.bbox[1],
        max_lon=g.bbox[2],
        max_lat=g.bbox[3],
        area_ha=g.area_ha,
    )
    session.add(field)
    session.flush()
    session.add(CropSeason(field_id=field.id, **body.season.model_dump()))
    if body.share_with_organization and user.organization_id:
        record_consent(session, user.id, ConsentPurpose.share_with_organization, True)
    audit(session, user, "field.create", "field", field.id, warnings=g.warnings)
    session.commit()
    session.refresh(field)
    return _field_out(field, user)


@router.get("", response_model=list[FieldSummary])
def list_fields(
    user: User = Depends(current_user),
    session: Session = Depends(db),
    district: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[FieldSummary]:
    q = select(Field).where(Field.deleted_at.is_(None))
    if user.role == Role.farmer:
        q = q.where(Field.owner_id == user.id)
    elif user.role in (Role.agronomist, Role.fpo_manager) and user.organization_id:
        q = q.where(Field.organization_id == user.organization_id)
    elif user.role == Role.admin:
        pass
    else:
        return []
    if district:
        q = q.where(Field.district == district)
    fields = session.scalars(q.order_by(Field.created_at.desc()).offset(offset).limit(limit)).all()
    out = []
    for f in fields:
        if f.owner_id != user.id and user.role != Role.admin and not latest_consent(session, f.owner_id, ConsentPurpose.share_with_organization):
            continue
        season = next((s for s in reversed(f.seasons) if s.active), None)
        ra = session.scalars(select(RiskAssessment).where(RiskAssessment.field_id == f.id).order_by(RiskAssessment.assessed_at.desc())).first()
        out.append(
            FieldSummary(
                id=f.id,
                name=f.name,
                district=f.district,
                crop=season.crop if season else None,
                season=season.season if season else None,
                area_ha=f.area_ha,
                latest_state=ra.state if ra else None,  # type: ignore[arg-type]
                latest_assessed_at=ra.assessed_at if ra else None,
                is_synthetic=f.is_synthetic,
            )
        )
    return out


@router.get("/{field_id}", response_model=FieldOut)
def get_field(field_id: str, user: User = Depends(current_user), session: Session = Depends(db)) -> FieldOut:
    return _field_out(readable_field(field_id, session, user), user)


@router.delete("/{field_id}", status_code=204)
def delete_field(field_id: str, user: User = Depends(current_user), session: Session = Depends(db)) -> None:
    field = writable_field(field_id, session, user)
    field.deleted_at = utcnow()
    audit(session, user, "field.delete", "field", field.id)
    session.commit()


@router.put("/{field_id}/boundary", response_model=FieldOut)
def update_boundary(field_id: str, body: BoundaryCheckIn, user: User = Depends(current_user), session: Session = Depends(db)) -> FieldOut:
    field = writable_field(field_id, session, user)
    try:
        g = validate_field_geometry(body.geometry)
    except GeometryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    field.geometry_geojson = g.geojson
    field.geometry_source = "point" if g.kind == "point" else "drawn"
    field.centroid_lat, field.centroid_lon = g.centroid_lat, g.centroid_lon
    field.min_lon, field.min_lat, field.max_lon, field.max_lat = g.bbox
    field.area_ha = g.area_ha
    field.boundary_version += 1
    audit(session, user, "field.boundary_update", "field", field.id, boundary_version=field.boundary_version)
    session.commit()
    return _field_out(field, user)


@router.post("/{field_id}/seasons", response_model=SeasonOut, status_code=201)
def add_season(field_id: str, body: SeasonIn, user: User = Depends(current_user), session: Session = Depends(db)) -> CropSeason:
    field = writable_field(field_id, session, user)
    _validate_season(body)
    for s in field.seasons:
        s.active = False
    season = CropSeason(field_id=field.id, **body.model_dump())
    session.add(season)
    session.commit()
    return season


def _refresh_job(field_id: str) -> None:
    session = get_sessionmaker()()
    try:
        field = session.get(Field, field_id)
        if field is None:
            return
        ingest_field(session, field)
        run_assessment(session, field)
    except Exception as exc:  # background task: record, never crash the server
        log(logger, logging.ERROR, "field refresh failed", field=field_id, error=str(exc)[:300])
    finally:
        session.close()


@router.post("/{field_id}/refresh", status_code=202)
def refresh(field_id: str, background: BackgroundTasks, user: User = Depends(current_user), session: Session = Depends(db)) -> dict[str, str]:
    field = readable_field(field_id, session, user)
    if field.owner_id != user.id and user.role not in (Role.agronomist, Role.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted to refresh this field")
    if not get_settings().enable_live_sources:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Live sources are disabled in this deployment (CROPPULSE_ENABLE_LIVE_SOURCES=false)")
    running = session.scalars(
        select(IngestionJob).where(
            IngestionJob.target_ref == field.id, IngestionJob.status == "running", IngestionJob.started_at > utcnow() - timedelta(minutes=15)
        )
    ).first()
    if running:
        return {"status": "already_running"}
    background.add_task(_refresh_job, field.id)
    return {"status": "queued"}


@router.get("/{field_id}/jobs")
def field_jobs(field_id: str, user: User = Depends(current_user), session: Session = Depends(db)) -> list[dict[str, Any]]:
    field = readable_field(field_id, session, user)
    cell = grid_cell_for(field.centroid_lat, field.centroid_lon).key
    jobs = session.scalars(select(IngestionJob).where(IngestionJob.target_ref.in_([field.id, cell])).order_by(IngestionJob.started_at.desc()).limit(10)).all()
    return [
        {
            "id": j.id,
            "source_id": j.source_id,
            "job_type": j.job_type,
            "status": j.status,
            "started_at": j.started_at,
            "finished_at": j.finished_at,
            "records_written": j.records_written,
            "records_unchanged": j.records_unchanged,
            "records_rejected": j.records_rejected,
            "warnings": j.warnings[:10],
            "message": j.message,
        }
        for j in jobs
    ]


@router.post("/{field_id}/assess", response_model=AssessmentOut)
def assess_now(field_id: str, user: User = Depends(current_user), session: Session = Depends(db)) -> AssessmentOut:
    field = readable_field(field_id, session, user)
    if field.owner_id != user.id and user.role not in (Role.agronomist, Role.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted")
    ra, _decision, _ = run_assessment(session, field)
    return assessment_out(ra, user.preferred_language)


@router.get("/{field_id}/assessments/latest", response_model=AssessmentOut | None)
def latest_assessment(field_id: str, user: User = Depends(current_user), session: Session = Depends(db)) -> AssessmentOut | None:
    readable_field(field_id, session, user)
    ra = session.scalars(select(RiskAssessment).where(RiskAssessment.field_id == field_id).order_by(RiskAssessment.assessed_at.desc())).first()
    return assessment_out(ra, user.preferred_language) if ra else None


@router.get("/{field_id}/assessments", response_model=list[AssessmentOut])
def assessment_history(
    field_id: str, user: User = Depends(current_user), session: Session = Depends(db), limit: int = Query(20, ge=1, le=100)
) -> list[AssessmentOut]:
    readable_field(field_id, session, user)
    rows = session.scalars(select(RiskAssessment).where(RiskAssessment.field_id == field_id).order_by(RiskAssessment.assessed_at.desc()).limit(limit)).all()
    return [assessment_out(r, user.preferred_language) for r in rows]


@router.get("/{field_id}/vegetation", response_model=VegetationSeriesOut)
def vegetation(
    field_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db),
    variable: str = Query("NDVI", pattern="^(NDVI|EVI)$"),
    years: int = Query(2, ge=1, le=25),
) -> VegetationSeriesOut:
    readable_field(field_id, session, user)
    vcfg = science_config()["vegetation"]
    rows = session.scalars(
        select(Observation)
        .where(Observation.field_id == field_id, Observation.variable == variable, Observation.source_id == "modis_mod13q1", Observation.is_current.is_(True))
        .order_by(Observation.period_start)
    ).all()
    pts = [SeriesPoint(o.period_start, o.value, o.accepted, o.available_at) for o in rows]
    now = datetime.now(UTC)
    since = date(now.year - years + 1, 1, 1)
    out: list[VegetationPoint] = []
    for o in rows:
        if o.period_start < since:
            continue
        ref = reference_stats(reference_sample(pts, o.period_start, now, vcfg["reference_years"], vcfg["pool_adjacent_composites"]))
        enough = ref.n >= vcfg["min_reference_samples"]
        out.append(
            VegetationPoint(
                period_start=o.period_start,
                period_end=o.period_end,
                value=o.value,
                accepted=o.accepted,
                rejection_reason=o.rejection_reason,
                valid_fraction=o.valid_fraction,
                reference_median=ref.median if enough else None,
                reference_p10=ref.p10 if enough else None,
                reference_p90=ref.p90 if enough else None,
                reference_n=ref.n,
                published_at=o.published_at,
                is_synthetic=o.is_synthetic,
            )
        )
    return VegetationSeriesOut(
        variable=variable,
        unit="dimensionless",
        source_id="modis_mod13q1",
        data_kind="observed",
        aggregation_method=rows[-1].aggregation_method if rows else None,
        retrieved_at=max((o.retrieved_at for o in rows), default=None),
        reference_description=(
            f"Median and 10th–90th percentile of the same 16-day period in the {vcfg['reference_years']} preceding years "
            f"(quality-accepted composites only; shown when at least {vcfg['min_reference_samples']} years are available)"
        ),
        points=out,
        is_synthetic=any(o.is_synthetic for o in rows),
    )


@router.get("/{field_id}/weather", response_model=WeatherOut)
def weather(field_id: str, user: User = Depends(current_user), session: Session = Depends(db), days: int = Query(90, ge=7, le=730)) -> WeatherOut:
    field = readable_field(field_id, session, user)
    frame, dv = load_weather_frame(session, field.centroid_lat, field.centroid_lon)
    if frame is None or dv is None:
        return WeatherOut(
            source_id="nasa_power_daily", data_kind="observed", grid_cell=None, units={}, retrieved_at=None, last_valid_date=None, daily=[], is_synthetic=False
        )
    end = frame.index.max()
    sub = frame[frame.index > end - timedelta(days=days)]

    def f(v: Any) -> float | None:
        return None if pd.isna(v) else round(float(v), 2)

    daily = [WeatherDaily(date=d, precipitation_mm=f(r.get("PRECTOTCORR")), tmax_c=f(r.get("T2M_MAX")), tmin_c=f(r.get("T2M_MIN"))) for d, r in sub.iterrows()]
    meta = dv.source_metadata or {}
    return WeatherOut(
        source_id="nasa_power_daily",
        data_kind="observed",
        grid_cell=meta.get("grid_cell"),
        units={k: v for k, v in (meta.get("units") or {}).items() if k in ("PRECTOTCORR", "T2M_MAX", "T2M_MIN")},
        retrieved_at=dv.retrieved_at,
        last_valid_date=dv.coverage_end,
        daily=daily,
        is_synthetic=dv.is_synthetic,
    )

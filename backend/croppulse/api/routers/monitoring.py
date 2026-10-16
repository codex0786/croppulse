"""Alerts, regional/FPO aggregates, research metadata, administration and advisories."""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from croppulse.api.deps import current_user, db, require_roles
from croppulse.config import get_settings, load_yaml, science_config
from croppulse.db import utcnow
from croppulse.enums import AlertStatus, ConsentPurpose, Role
from croppulse.governance import audit, latest_consent
from croppulse.ingestion.jobs import load_weather_frame
from croppulse.models import Advisory, Alert, AuditEvent, DataSource, EvaluationRun, Field, IngestionJob, ModelVersion, RiskAssessment, User
from croppulse.risk.service import active_season
from croppulse.schemas import AdvisoryIn, AdvisoryOut, AlertOut
from croppulse.science.features import FEATURES
from croppulse.science.weather import compute_weather_features
from croppulse.sources.nasa_power import grid_cell_for

router = APIRouter(prefix="/api/v1", tags=["monitoring"])

MIN_CELL_SIZE = 3  # small-cell suppression for aggregates


# ------------------------------------------------------------------ alerts


@router.get("/alerts", response_model=list[AlertOut])
def my_alerts(user: User = Depends(current_user), session: Session = Depends(db), include_inactive: bool = False) -> list[Alert]:
    q = select(Alert).join(Field, Field.id == Alert.field_id).where(Field.owner_id == user.id, Field.deleted_at.is_(None))
    if not include_inactive:
        q = q.where(Alert.status.in_([AlertStatus.active, AlertStatus.acknowledged]), Alert.expires_at > utcnow())
    return list(session.scalars(q.order_by(Alert.created_at.desc()).limit(100)).all())


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge(alert_id: str, user: User = Depends(current_user), session: Session = Depends(db)) -> Alert:
    alert = session.get(Alert, alert_id)
    field = session.get(Field, alert.field_id) if alert else None
    if alert is None or field is None or field.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    alert.acknowledged_at = utcnow()
    alert.status = AlertStatus.acknowledged
    session.commit()
    return alert


# ------------------------------------------------------------------ aggregates


def _latest_assessment(session: Session, field_id: str) -> RiskAssessment | None:
    return session.scalars(select(RiskAssessment).where(RiskAssessment.field_id == field_id).order_by(RiskAssessment.assessed_at.desc())).first()


def _aggregate(session: Session, fields: list[Field], key_fn: Any, crop: str | None, season: str | None) -> list[dict[str, Any]]:
    groups: dict[Any, list[tuple[Field, RiskAssessment | None]]] = defaultdict(list)
    for f in fields:
        s = active_season(f)
        if crop and (s is None or s.crop != crop):
            continue
        if season and (s is None or s.season != season):
            continue
        groups[key_fn(f)].append((f, _latest_assessment(session, f.id)))
    out = []
    now = utcnow()
    for key, items in groups.items():
        n = len(items)
        if n < MIN_CELL_SIZE:
            out.append({"key": key, "suppressed": True, "reason": f"fewer than {MIN_CELL_SIZE} consenting fields"})
            continue
        states = Counter((ra.state if ra and ra.expires_at > now else "no_current_assessment") for _, ra in items)
        veg_current = sum(1 for _, ra in items if ra and (ra.freshness.get("vegetation") or {}).get("status") == "current")
        latest_veg = max(((ra.freshness.get("vegetation") or {}).get("period_end") for _, ra in items if ra and (ra.freshness.get("vegetation") or {}).get("period_end")), default=None)
        out.append(
            {
                "key": key,
                "suppressed": False,
                "fields": n,
                "states": dict(states),
                "vegetation_current_share": round(veg_current / n, 3),
                "latest_vegetation_period_end": latest_veg,
                "synthetic_fields": sum(1 for f, _ in items if f.is_synthetic),
            }
        )
    return sorted(out, key=lambda g: str(g["key"]))


@router.get("/regional/summary")
def regional_summary(
    user: User = Depends(require_roles(Role.regional_analyst, Role.admin, Role.researcher)),
    session: Session = Depends(db),
    crop: str | None = None,
    season: str | None = None,
) -> dict[str, Any]:
    """District and coarse-grid aggregates over fields whose owners consented to aggregated use.

    No field identifiers, names or coordinates are returned. Groups with fewer than
    MIN_CELL_SIZE fields are suppressed. Grid cells are the ~0.5° NASA POWER cells.
    """
    fields = [f for f in session.scalars(select(Field).where(Field.deleted_at.is_(None))).all() if latest_consent(session, f.owner_id, ConsentPurpose.aggregated_research)]
    districts = _aggregate(session, fields, lambda f: f.district, crop, season)
    cells = _aggregate(session, fields, lambda f: grid_cell_for(f.centroid_lat, f.centroid_lon).key, crop, season)
    cell_out = []
    cfg = science_config()["weather"]
    for c in cells:
        if c["suppressed"]:
            continue  # do not even reveal where suppressed cells are
        sample = next(f for f in fields if grid_cell_for(f.centroid_lat, f.centroid_lon).key == c["key"])
        cell = grid_cell_for(sample.centroid_lat, sample.centroid_lon)
        frame, _ = load_weather_frame(session, sample.centroid_lat, sample.centroid_lon)
        rain30 = None
        window_end = None
        if frame is not None:
            feats = compute_weather_features(
                frame,
                datetime.now(UTC).date(),
                windows=[30],
                reference_years=cfg["reference_years"],
                min_reference_years=cfg["min_reference_years"],
                min_coverage=cfg["min_window_coverage"],
                rainy_day_mm=cfg["rainy_day_mm"],
                heat_tmax_c=cfg["heat_tmax_c"],
                heat_window_days=cfg["heat_window_days"],
            )
            r = feats.rain_window(30)
            window_end = feats.window_end.isoformat() if feats.window_end else None
            if r:
                rain30 = {"total_mm": r.total_mm, "percentile": r.percentile, "reference_mean_mm": r.reference_mean_mm, "climatologically_dry": r.climatologically_dry}
        cell_out.append({**c, "cell": {"lat": cell.lat, "lon": cell.lon, "dlat": 0.5, "dlon": 0.625}, "rain_30d": rain30, "weather_window_end": window_end})
    audit(session, user, "regional.summary", "aggregate", None, crop=crop, season=season)
    session.commit()
    return {
        "generated_at": utcnow(),
        "consenting_fields": len(fields),
        "min_group_size": MIN_CELL_SIZE,
        "districts": districts,
        "grid_cells": cell_out,
        "notes": [
            "Risk states are unvalidated screening indicators, not drought declarations or crop-loss assessments.",
            "Only fields whose owners consented to aggregated use are counted.",
            "Rainfall is NASA POWER (MERRA-2 based) reanalysis on a ~0.5° grid; percentile is relative to the 30 preceding years.",
        ],
    }


@router.get("/org/summary")
def org_summary(user: User = Depends(require_roles(Role.fpo_manager, Role.agronomist)), session: Session = Depends(db), crop: str | None = None) -> dict[str, Any]:
    if not user.organization_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No organisation")
    fields = [
        f
        for f in session.scalars(select(Field).where(Field.organization_id == user.organization_id, Field.deleted_at.is_(None))).all()
        if latest_consent(session, f.owner_id, ConsentPurpose.share_with_organization)
    ]
    rows = []
    for f in fields:
        s = active_season(f)
        if crop and (s is None or s.crop != crop):
            continue
        ra = _latest_assessment(session, f.id)
        rows.append(
            {
                "field_id": f.id,
                "field_name": f.name,
                "district": f.district,
                "crop": s.crop if s else None,
                "area_ha": f.area_ha,
                "state": ra.state if ra else None,
                "assessed_at": ra.assessed_at if ra else None,
                "expired": bool(ra and ra.expires_at <= utcnow()),
                "escalated": bool(ra and ra.escalate_to_expert),
                "vegetation_freshness": (ra.freshness.get("vegetation") or {}).get("status") if ra else None,
                "is_synthetic": f.is_synthetic,
            }
        )
    priority = {"expert_review_recommended": 0, "elevated_risk": 1, "watch": 2, "insufficient_evidence": 3, "normal_for_reference_period": 4}
    rows.sort(key=lambda r: (priority.get(r["state"] or "", 5), r["district"]))
    audit(session, user, "org.summary", "organization", user.organization_id)
    session.commit()
    return {"organization_id": user.organization_id, "consenting_fields": len(rows), "fields": rows, "states": dict(Counter(r["state"] or "not_assessed" for r in rows))}


@router.get("/org/export.csv")
def org_export(user: User = Depends(require_roles(Role.fpo_manager)), session: Session = Depends(db)) -> StreamingResponse:
    """Aggregated export: counts by district × crop × state. No field identifiers or coordinates."""
    data = org_summary(user=user, session=session)
    counts: Counter[tuple[str, str, str]] = Counter((r["district"], r["crop"] or "", r["state"] or "not_assessed") for r in data["fields"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["district", "crop", "screening_state", "fields", "note"])
    for (d, c, s), n in sorted(counts.items()):
        w.writerow([d, c, s, n if n >= MIN_CELL_SIZE else f"<{MIN_CELL_SIZE}", "unvalidated screening indicator"])
    audit(session, user, "org.export", "organization", user.organization_id)
    session.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=croppulse_org_summary.csv"})


# ------------------------------------------------------------------ research / metadata (no private data)


@router.get("/sources")
def sources(session: Session = Depends(db)) -> list[dict[str, Any]]:
    reg = load_yaml(str(get_settings().sources_path))["sources"]
    state = {d.id: d for d in session.scalars(select(DataSource)).all()}
    out = []
    for sid, meta in reg.items():
        d = state.get(sid)
        if d is not None:
            status_ = d.status
        elif meta["adapter"] == "manual":
            status_ = "manual_entry" if sid == "imd_advisories" else "not_configured"
        elif meta["adapter"] == "disabled":
            status_ = "unavailable"
        elif sid in ("gpm_imerg", "smap_l4"):
            status_ = "not_configured" if not get_settings().earthdata_token else "implemented_untested"
        elif meta["adapter"].startswith("croppulse.sources.crop_stats"):
            status_ = "not_configured"
        else:
            status_ = "implemented_untested"
        out.append(
            {
                "id": sid,
                **{k: meta[k] for k in ("name", "provider", "collection_id", "documentation", "access", "license", "spatial_resolution", "temporal_resolution", "units", "coverage", "quality_flags", "typical_latency", "limitations", "verified_on")},
                "status": status_,
                "last_success_at": d.last_success_at if d else None,
                "last_attempt_at": d.last_attempt_at if d else None,
                "last_error": d.last_error if d else None,
                "latest_observation_end": d.latest_observation_end if d else None,
                "observed_latency_days": d.observed_latency_days if d else None,
                "processing_version": d.processing_version if d else None,
            }
        )
    return out


@router.get("/features")
def features() -> list[dict[str, Any]]:
    return [f.to_dict() for f in FEATURES]


@router.get("/models")
def models(session: Session = Depends(db)) -> list[dict[str, Any]]:
    return [
        {
            "name": m.name,
            "version": m.version,
            "kind": m.kind,
            "status": m.status,
            "config_hash": m.config_hash,
            "intended_use": m.intended_use,
            "excluded_uses": m.excluded_uses,
            "evaluation_run_ids": m.evaluation_run_ids,
            "approved_at": m.approved_at,
            "created_at": m.created_at,
        }
        for m in session.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc())).all()
    ]


@router.get("/evaluations")
def evaluations(session: Session = Depends(db)) -> list[dict[str, Any]]:
    return [
        {
            "id": e.id,
            "model_name": e.model_name,
            "regime": e.regime,
            "is_synthetic": e.is_synthetic,
            "metrics": e.metrics,
            "report_path": e.report_path,
            "notes": e.notes,
            "created_at": e.created_at,
        }
        for e in session.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc())).all()
    ]


@router.get("/yield")
def yield_prediction() -> dict[str, Any]:
    if not get_settings().feature_yield_prediction:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "Yield prediction is disabled: no reliable, temporally compatible yield labels have been imported and validated (docs/LIMITATIONS.md).",
        )
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "No validated yield model is registered.")


# ------------------------------------------------------------------ advisories & admin


@router.get("/advisories", response_model=list[AdvisoryOut])
def advisories(user: User = Depends(current_user), session: Session = Depends(db), district: str | None = None) -> list[Advisory]:
    rows = session.scalars(select(Advisory).where(Advisory.valid_until > utcnow()).order_by(Advisory.issued_at.desc())).all()
    return [a for a in rows if district is None or district in a.districts]


@router.post("/admin/advisories", response_model=AdvisoryOut, status_code=201)
def add_advisory(body: AdvisoryIn, user: User = Depends(require_roles(Role.admin)), session: Session = Depends(db)) -> Advisory:
    if body.valid_until <= body.issued_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "valid_until must be after issued_at")
    adv = Advisory(**body.model_dump(), entered_by=user.id)
    session.add(adv)
    audit(session, user, "advisory.create", "advisory", None, source_org=body.source_org)
    session.commit()
    return adv


@router.get("/admin/jobs")
def admin_jobs(user: User = Depends(require_roles(Role.admin)), session: Session = Depends(db), limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    jobs = session.scalars(select(IngestionJob).order_by(IngestionJob.started_at.desc()).limit(limit)).all()
    return [
        {
            "id": j.id,
            "source_id": j.source_id,
            "job_type": j.job_type,
            "target_ref": j.target_ref,
            "status": j.status,
            "started_at": j.started_at,
            "finished_at": j.finished_at,
            "records_written": j.records_written,
            "records_unchanged": j.records_unchanged,
            "records_rejected": j.records_rejected,
            "warnings": j.warnings,
            "message": j.message,
            "config_version": j.config_version,
        }
        for j in jobs
    ]


@router.get("/admin/audit")
def admin_audit(user: User = Depends(require_roles(Role.admin)), session: Session = Depends(db), limit: int = Query(100, ge=1, le=1000)) -> list[dict[str, Any]]:
    rows = session.scalars(select(AuditEvent).order_by(AuditEvent.at.desc()).limit(limit)).all()
    return [{"at": r.at, "actor_id": r.actor_id, "action": r.action, "resource_type": r.resource_type, "resource_id": r.resource_id, "outcome": r.outcome} for r in rows]


@router.get("/admin/metrics")
def admin_metrics(user: User = Depends(require_roles(Role.admin)), session: Session = Depends(db)) -> dict[str, Any]:
    from croppulse.api.metrics import snapshot

    jobs = session.scalars(select(IngestionJob)).all()
    by_status = Counter(j.status for j in jobs)
    alerts = Counter(a.status for a in session.scalars(select(Alert)).all())
    return {
        "api": snapshot(),
        "ingestion_jobs": dict(by_status),
        "ingestion_success_rate": round(by_status.get("succeeded", 0) / max(1, sum(by_status.values()) - by_status.get("running", 0)), 3),
        "alerts": dict(alerts),
        "sources": {d.id: {"status": d.status, "latency_days": d.observed_latency_days, "last_success_at": d.last_success_at} for d in session.scalars(select(DataSource)).all()},
    }

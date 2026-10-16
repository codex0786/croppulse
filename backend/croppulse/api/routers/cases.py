"""Farmer reports and the agronomist case workflow.

Farmer reports are stored as UNVERIFIED observations. Only an authorised expert's
verification creates a VerifiedOutcome (the label table). Machine-generated case
events carry authored_by="system" and are displayed separately from expert input.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from croppulse.api.deps import current_user, db, readable_field, require_roles
from croppulse.api.presenters import assessment_out
from croppulse.config import get_settings
from croppulse.db import utcnow
from croppulse.enums import CaseStatus, ConsentPurpose, Role
from croppulse.governance import audit, can_handle_case, latest_consent, record_consent
from croppulse.models import CaseEvent, ExpertCase, FarmerReport, Field, Photo, RiskAssessment, User, VerifiedOutcome
from croppulse.risk.service import active_season, open_report_case
from croppulse.schemas import (
    AssignIn,
    CaseDetail,
    CaseEventIn,
    CaseEventOut,
    CaseOut,
    PhotoOut,
    ReportIn,
    ReportOut,
    VerifiedOutcomeOut,
    VerifyIn,
)
from croppulse.uploads import UploadError, store_photo

router = APIRouter(prefix="/api/v1", tags=["reports & cases"])


def _report_out(session: Session, r: FarmerReport) -> ReportOut:
    out = ReportOut.model_validate(r)
    case = session.scalars(select(ExpertCase).where(ExpertCase.report_id == r.id)).first()
    out.case_id = case.id if case else None
    out.photos = [PhotoOut.model_validate(p) for p in session.scalars(select(Photo).where(Photo.report_id == r.id)).all()]
    return out


@router.post("/fields/{field_id}/reports", response_model=ReportOut, status_code=201)
def create_report(field_id: str, body: ReportIn, user: User = Depends(current_user), session: Session = Depends(db)) -> ReportOut:
    field = readable_field(field_id, session, user)
    if field.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the field owner can submit farmer reports")
    if body.client_ref:
        existing = session.scalars(select(FarmerReport).where(FarmerReport.client_ref == body.client_ref, FarmerReport.reporter_id == user.id)).first()
        if existing:  # offline queue replay: idempotent
            return _report_out(session, existing)
    report = FarmerReport(
        field_id=field.id,
        reporter_id=user.id,
        symptoms=[s.value for s in body.symptoms],
        description=body.description,
        observed_on=body.observed_on,
        affected_fraction=body.affected_fraction,
        answers=body.answers,
        request_expert=body.request_expert,
        client_ref=body.client_ref,
    )
    session.add(report)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate client reference") from exc
    if body.request_expert:
        # Asking for help is consent to share this field with the organisation's experts.
        if not latest_consent(session, user.id, ConsentPurpose.expert_review):
            record_consent(session, user.id, ConsentPurpose.expert_review, True)
        open_report_case(session, field, report)
    audit(session, user, "report.create", "farmer_report", report.id, request_expert=body.request_expert)
    session.commit()
    return _report_out(session, report)


@router.get("/fields/{field_id}/reports", response_model=list[ReportOut])
def list_reports(field_id: str, user: User = Depends(current_user), session: Session = Depends(db)) -> list[ReportOut]:
    readable_field(field_id, session, user)
    rows = session.scalars(select(FarmerReport).where(FarmerReport.field_id == field_id).order_by(FarmerReport.created_at.desc())).all()
    return [_report_out(session, r) for r in rows]


@router.post("/reports/{report_id}/photos", response_model=PhotoOut, status_code=201)
async def upload_photo(report_id: str, file: UploadFile = File(...), user: User = Depends(current_user), session: Session = Depends(db)) -> Photo:
    report = session.get(FarmerReport, report_id)
    if report is None or report.reporter_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    if len(session.scalars(select(Photo.id).where(Photo.report_id == report_id)).all()) >= 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "At most 5 photos per report")
    s = get_settings()
    data = await file.read(s.max_upload_bytes + 1)
    try:
        stored = store_photo(data, s.upload_dir, s.max_upload_bytes)
    except UploadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    photo = Photo(report_id=report_id, **stored.__dict__)
    session.add(photo)
    audit(session, user, "photo.upload", "photo", None, report_id=report_id, size=stored.size_bytes)
    session.commit()
    return photo


# ------------------------------------------------------------------ expert console


def _case_out(session: Session, c: ExpertCase) -> CaseOut:
    f = session.get(Field, c.field_id)
    assert f is not None
    season = active_season(f)
    ra = session.get(RiskAssessment, c.assessment_id) if c.assessment_id else None
    return CaseOut(
        id=c.id,
        field_id=c.field_id,
        field_name=f.name,
        district=f.district,
        crop=season.crop if season else None,
        origin=c.origin,
        status=CaseStatus(c.status),
        priority=c.priority,
        assigned_to=c.assigned_to,
        created_at=c.created_at,
        updated_at=c.updated_at,
        age_days=(datetime.now(UTC) - c.created_at).days,
        latest_state=ra.state if ra else None,
    )


def _load_case(session: Session, case_id: str, user: User) -> ExpertCase:
    case = session.get(ExpertCase, case_id)
    if case is None or not can_handle_case(session, user, case):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


@router.get("/cases", response_model=list[CaseOut])
def case_queue(
    user: User = Depends(require_roles(Role.agronomist, Role.admin)),
    session: Session = Depends(db),
    status_filter: CaseStatus | None = Query(None, alias="status"),
    district: str | None = None,
    crop: str | None = None,
    risk_state: str | None = None,
    min_age_days: int | None = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> list[CaseOut]:
    q = select(ExpertCase)
    if user.role != Role.admin:
        q = q.where(ExpertCase.organization_id == user.organization_id)
    q = q.where(ExpertCase.status == status_filter.value) if status_filter else q.where(ExpertCase.status != CaseStatus.closed)
    cases = session.scalars(q.order_by(ExpertCase.priority, ExpertCase.created_at).limit(limit * 3)).all()
    out = [_case_out(session, c) for c in cases]
    if district:
        out = [c for c in out if c.district == district]
    if crop:
        out = [c for c in out if c.crop == crop]
    if risk_state:
        out = [c for c in out if c.latest_state == risk_state]
    if min_age_days is not None:
        out = [c for c in out if c.age_days >= min_age_days]
    return out[:limit]


@router.get("/cases/{case_id}", response_model=CaseDetail)
def case_detail(case_id: str, user: User = Depends(require_roles(Role.agronomist, Role.admin)), session: Session = Depends(db)) -> CaseDetail:
    case = _load_case(session, case_id, user)
    base = _case_out(session, case)
    report = session.get(FarmerReport, case.report_id) if case.report_id else None
    ra = session.get(RiskAssessment, case.assessment_id) if case.assessment_id else None
    if ra is None:
        ra = session.scalars(select(RiskAssessment).where(RiskAssessment.field_id == case.field_id).order_by(RiskAssessment.assessed_at.desc())).first()
    vo = session.scalars(select(VerifiedOutcome).where(VerifiedOutcome.case_id == case.id)).first()
    audit(session, user, "case.read", "expert_case", case.id)
    session.commit()
    return CaseDetail(
        **base.model_dump(),
        events=[CaseEventOut.model_validate(e) for e in case.events],
        report=_report_out(session, report) if report else None,
        assessment=assessment_out(ra) if ra else None,
        outcome=VerifiedOutcomeOut.model_validate(vo) if vo else None,
    )


@router.post("/cases/{case_id}/assign", response_model=CaseOut)
def assign(case_id: str, body: AssignIn, user: User = Depends(require_roles(Role.agronomist, Role.admin)), session: Session = Depends(db)) -> CaseOut:
    case = _load_case(session, case_id, user)
    assignee_id = body.assignee_id or user.id
    assignee = session.get(User, assignee_id)
    if assignee is None or assignee.role != Role.agronomist or assignee.organization_id != case.organization_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Assignee must be an agronomist in the case's organisation")
    case.assigned_to = assignee_id
    if case.status == CaseStatus.open:
        case.status = CaseStatus.assigned
    case.updated_at = utcnow()
    session.add(CaseEvent(case_id=case.id, actor_id=user.id, kind="assignment", data={"assignee_id": assignee_id}))
    audit(session, user, "case.assign", "expert_case", case.id)
    session.commit()
    return _case_out(session, case)


@router.post("/cases/{case_id}/events", response_model=CaseEventOut, status_code=201)
def add_event(case_id: str, body: CaseEventIn, user: User = Depends(require_roles(Role.agronomist, Role.admin)), session: Session = Depends(db)) -> CaseEvent:
    case = _load_case(session, case_id, user)
    if case.status == CaseStatus.closed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Case is closed; reopen it first")
    data: dict[str, str | None] = {}
    if body.kind == "info_request":
        case.status = CaseStatus.info_requested
    elif body.kind == "inspection_scheduled":
        if body.scheduled_for is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "scheduled_for is required")
        case.status = CaseStatus.inspection_scheduled
        data["scheduled_for"] = body.scheduled_for.isoformat()
    elif body.kind == "recommendation":
        data["source_ref"] = body.source_ref
        data["authored_role"] = user.role
    ev = CaseEvent(case_id=case.id, actor_id=user.id, kind=body.kind, body=body.body, data=data, authored_by="human")
    session.add(ev)
    case.updated_at = utcnow()
    audit(session, user, f"case.{body.kind}", "expert_case", case.id)
    session.commit()
    return ev


@router.post("/cases/{case_id}/verify", response_model=VerifiedOutcomeOut, status_code=201)
def verify(case_id: str, body: VerifyIn, user: User = Depends(require_roles(Role.agronomist)), session: Session = Depends(db)) -> VerifiedOutcome:
    """Record an expert-verified finding. Only agronomists (not admins) can verify."""
    case = _load_case(session, case_id, user)
    if session.scalars(select(VerifiedOutcome).where(VerifiedOutcome.case_id == case.id)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "This case already has a verified outcome; reopen creates a new case history entry")
    if body.observed_on > datetime.now(UTC).date():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "observed_on cannot be in the future")
    evidence = dict(body.evidence)
    evidence.update({"assessment_id": case.assessment_id, "report_id": case.report_id})
    vo = VerifiedOutcome(
        case_id=case.id,
        field_id=case.field_id,
        finding=body.finding.value,
        suspected_cause=body.suspected_cause,
        observed_on=body.observed_on,
        verified_by=user.id,
        method=body.method,
        evidence=evidence,
        notes=body.notes,
    )
    session.add(vo)
    case.status = CaseStatus.verified
    case.updated_at = utcnow()
    session.add(CaseEvent(case_id=case.id, actor_id=user.id, kind="verification", body=body.notes, data={"finding": body.finding.value, "method": body.method}))
    audit(session, user, "case.verify", "expert_case", case.id, finding=body.finding.value)
    session.commit()
    return vo


@router.post("/cases/{case_id}/close", response_model=CaseOut)
def close(case_id: str, user: User = Depends(require_roles(Role.agronomist, Role.admin)), session: Session = Depends(db)) -> CaseOut:
    case = _load_case(session, case_id, user)
    case.status = CaseStatus.closed
    case.closed_at = case.updated_at = utcnow()
    session.add(CaseEvent(case_id=case.id, actor_id=user.id, kind="status_change", data={"to": "closed"}))
    audit(session, user, "case.close", "expert_case", case.id)
    session.commit()
    return _case_out(session, case)


@router.post("/cases/{case_id}/reopen", response_model=CaseOut)
def reopen(case_id: str, user: User = Depends(require_roles(Role.agronomist, Role.admin)), session: Session = Depends(db)) -> CaseOut:
    case = _load_case(session, case_id, user)
    if case.status not in (CaseStatus.closed, CaseStatus.verified):
        raise HTTPException(status.HTTP_409_CONFLICT, "Case is not closed")
    case.status = CaseStatus.assigned if case.assigned_to else CaseStatus.open
    case.closed_at = None
    case.updated_at = utcnow()
    session.add(CaseEvent(case_id=case.id, actor_id=user.id, kind="status_change", data={"to": case.status}))
    audit(session, user, "case.reopen", "expert_case", case.id)
    session.commit()
    return _case_out(session, case)


@router.get("/fields/{field_id}/cases", response_model=list[CaseOut])
def field_cases(field_id: str, user: User = Depends(current_user), session: Session = Depends(db)) -> list[CaseOut]:
    """Farmer view of their own cases (status + expert recommendations only)."""
    readable_field(field_id, session, user)
    rows = session.scalars(select(ExpertCase).where(ExpertCase.field_id == field_id).order_by(ExpertCase.created_at.desc())).all()
    return [_case_out(session, c) for c in rows]


@router.get("/fields/{field_id}/recommendations")
def field_recommendations(field_id: str, user: User = Depends(current_user), session: Session = Depends(db)) -> list[dict[str, object]]:
    """Expert-authored recommendations and verified findings for the farmer (never system text)."""
    readable_field(field_id, session, user)
    cases = session.scalars(select(ExpertCase).where(ExpertCase.field_id == field_id)).all()
    out: list[dict[str, object]] = []
    for c in cases:
        for e in c.events:
            if e.authored_by == "human" and e.kind in ("recommendation", "info_request", "inspection_scheduled", "verification"):
                out.append(
                    {
                        "case_id": c.id,
                        "kind": e.kind,
                        "body": e.body,
                        "data": e.data,
                        "created_at": e.created_at,
                        "data_kind": "expert_verified" if e.kind == "verification" else "expert_authored",
                    }
                )
    return sorted(out, key=lambda x: x["created_at"], reverse=True)  # type: ignore[arg-type, return-value]

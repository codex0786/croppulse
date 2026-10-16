"""Consent, authorisation and audit helpers (single place for access rules).

Access rules (tested in tests/security):
  * farmer           — own fields only.
  * agronomist       — fields in their organisation whose owner granted share_with_organization,
                       plus fields with an expert case routed to their organisation (owner granted expert_review).
  * fpo_manager      — fields in their organisation with share_with_organization consent (read only).
  * admin            — any field, read only, every access audited.
  * regional_analyst, researcher — no field-level access; aggregates only.
Unauthorised access returns 404 (not 403) so identifiers cannot be enumerated.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from croppulse.enums import ConsentPurpose, Role
from croppulse.models import AuditEvent, ConsentRecord, ExpertCase, Field, User

POLICY_VERSION = "2026-10-v1"


def latest_consent(session: Session, user_id: str, purpose: ConsentPurpose) -> bool:
    rec = session.scalars(
        select(ConsentRecord)
        .where(ConsentRecord.user_id == user_id, ConsentRecord.purpose == purpose.value)
        .order_by(ConsentRecord.created_at.desc(), ConsentRecord.id.desc())
    ).first()
    return bool(rec and rec.granted)


def record_consent(session: Session, user_id: str, purpose: ConsentPurpose, granted: bool) -> ConsentRecord:
    rec = ConsentRecord(user_id=user_id, purpose=purpose.value, granted=granted, policy_version=POLICY_VERSION)
    session.add(rec)
    return rec


def consents_for(session: Session, user_id: str) -> dict[str, bool]:
    return {p.value: latest_consent(session, user_id, p) for p in ConsentPurpose}


def audit(session: Session, actor: User | None, action: str, resource_type: str, resource_id: str | None, outcome: str = "success", **details: Any) -> None:
    session.add(
        AuditEvent(
            actor_id=actor.id if actor else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            details=details,
        )
    )


def can_read_field(session: Session, user: User, field: Field) -> bool:
    if field.deleted_at is not None:
        return False
    if field.owner_id == user.id:
        return True
    if user.role == Role.admin:
        return True
    if user.role in (Role.agronomist, Role.fpo_manager) and user.organization_id and field.organization_id == user.organization_id:
        if latest_consent(session, field.owner_id, ConsentPurpose.share_with_organization):
            return True
    if user.role == Role.agronomist and user.organization_id:
        has_case = session.scalars(
            select(ExpertCase.id).where(ExpertCase.field_id == field.id, ExpertCase.organization_id == user.organization_id)
        ).first()
        if has_case and latest_consent(session, field.owner_id, ConsentPurpose.expert_review):
            return True
    return False


def can_write_field(user: User, field: Field) -> bool:
    return field.deleted_at is None and field.owner_id == user.id


def can_handle_case(session: Session, user: User, case: ExpertCase) -> bool:
    if user.role == Role.admin:
        return True
    return user.role == Role.agronomist and user.organization_id is not None and case.organization_id == user.organization_id

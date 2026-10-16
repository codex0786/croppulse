"""Rules-based alert engine with dedupe, cooldown, escalation, expiry and stale-data suppression.

An alert is only ever derived from a persisted RiskAssessment. Ingestion failures
never generate alerts; stale evidence suppresses them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from croppulse.config import get_settings, load_yaml
from croppulse.db import utcnow
from croppulse.enums import RISK_ORDER, AlertStatus, ConsentPurpose, DeliveryStatus, RiskState
from croppulse.governance import latest_consent
from croppulse.logging_setup import log
from croppulse.models import Alert, Field, NotificationDelivery, RiskAssessment, User

logger = logging.getLogger(__name__)
MAX_DELIVERY_ATTEMPTS = 3


@dataclass
class AlertDecision:
    outcome: str  # created | escalated | suppressed_* | no_rule
    alert: Alert | None = None


def rules() -> dict[str, Any]:
    return load_yaml(str(get_settings().alert_rules_path))


def expire_alerts(session: Session, now: datetime) -> int:
    res = session.execute(
        update(Alert).where(Alert.status == AlertStatus.active, Alert.expires_at <= now).values(status=AlertStatus.expired)
    )
    return int(res.rowcount or 0)  # type: ignore[attr-defined]


def evaluate_assessment(session: Session, assessment: RiskAssessment, field: Field, now: datetime | None = None) -> AlertDecision:
    now = now or utcnow()
    cfg = rules()
    expire_alerts(session, now)
    state = RiskState(assessment.state)
    level = RISK_ORDER[state]
    matching = [r for r in cfg["rules"] if level >= RISK_ORDER[RiskState(r["min_state"])] and state not in (RiskState.verified_stress, RiskState.resolved)]
    if not matching:
        return AlertDecision("no_rule")
    rule = max(matching, key=lambda r: RISK_ORDER[RiskState(r["min_state"])])
    if assessment.sufficiency not in rule["allowed_sufficiency"]:
        return AlertDecision("suppressed_insufficient_evidence")
    if rule.get("require_current_source"):
        fr = assessment.freshness or {}
        if not any((fr.get(k) or {}).get("status") == "current" for k in ("vegetation", "weather")):
            return AlertDecision("suppressed_stale_data")

    key = f"{field.id}:condition"
    active = session.scalars(
        select(Alert).where(Alert.dedupe_key == key, Alert.status == AlertStatus.active).order_by(Alert.created_at.desc())
    ).first()
    outcome = "created"
    if active is not None:
        if RISK_ORDER[state] <= RISK_ORDER[RiskState(active.severity)]:
            return AlertDecision("suppressed_duplicate", active)
        outcome = "escalated"
    else:
        last = session.scalars(select(Alert).where(Alert.dedupe_key == key).order_by(Alert.created_at.desc())).first()
        if last is not None and last.severity == state.value and now - last.created_at < timedelta(days=rule["cooldown_days"]):
            return AlertDecision("suppressed_cooldown", last)

    alert = Alert(
        field_id=field.id,
        assessment_id=assessment.id,
        rule_id=rule["id"],
        rule_version=cfg["version"],
        dedupe_key=key,
        severity=state.value,
        status=AlertStatus.active,
        title_key=rule["title_key"],
        message_key=rule["message_key"],
        explanation=assessment.explanations,
        next_step_key=assessment.next_step_key,
        requires_expert=bool(rule.get("requires_expert")) or assessment.escalate_to_expert,
        observation_period=assessment.input_periods,
        source_timestamps=assessment.freshness,
        model_version=f"{assessment.model_name}@{assessment.model_version}",
        created_at=now,
        expires_at=now + timedelta(days=rule["expiry_days"]),
    )
    session.add(alert)
    session.flush()
    if active is not None:
        active.status = AlertStatus.superseded
        active.superseded_by = alert.id
    _queue_deliveries(session, alert, field)
    return AlertDecision(outcome, alert)


def _queue_deliveries(session: Session, alert: Alert, field: Field) -> None:
    # In-app: the alert record itself is the delivery.
    session.add(NotificationDelivery(alert_id=alert.id, user_id=field.owner_id, channel="in_app", status=DeliveryStatus.sent, attempts=1, sent_at=utcnow()))
    if latest_consent(session, field.owner_id, ConsentPurpose.notifications):
        session.add(NotificationDelivery(alert_id=alert.id, user_id=field.owner_id, channel="email", status=DeliveryStatus.pending))
    else:
        session.add(NotificationDelivery(alert_id=alert.id, user_id=field.owner_id, channel="email", status=DeliveryStatus.suppressed, last_error="no_notification_consent"))


class NotificationProvider(Protocol):
    name: str

    def send(self, user: User, alert: Alert) -> None: ...


class DevOutboxProvider:
    """Development provider: appends to data/outbox/notifications.jsonl. Sends nothing externally."""

    name = "dev_outbox"

    def send(self, user: User, alert: Alert) -> None:
        out = get_settings().data_dir / "outbox"
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "notifications.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": utcnow().isoformat(), "user_id": user.id, "alert_id": alert.id, "title_key": alert.title_key, "language": user.preferred_language}) + "\n")


def provider() -> NotificationProvider | None:
    return DevOutboxProvider() if get_settings().notification_email_provider == "dev_outbox" else None


def deliver_pending(session: Session, prov: NotificationProvider | None = None) -> dict[str, int]:
    prov = prov or provider()
    stats = {"sent": 0, "failed": 0, "skipped": 0}
    pending = session.scalars(
        select(NotificationDelivery).where(
            NotificationDelivery.status.in_([DeliveryStatus.pending, DeliveryStatus.failed]),
            NotificationDelivery.attempts < MAX_DELIVERY_ATTEMPTS,
            NotificationDelivery.channel != "in_app",
        )
    ).all()
    for d in pending:
        alert = session.get(Alert, d.alert_id)
        user = session.get(User, d.user_id)
        if alert is None or user is None or alert.status != AlertStatus.active:
            d.status = DeliveryStatus.suppressed
            stats["skipped"] += 1
            continue
        if prov is None:
            stats["skipped"] += 1
            continue
        d.attempts += 1
        try:
            prov.send(user, alert)
            d.status = DeliveryStatus.sent
            d.sent_at = utcnow()
            stats["sent"] += 1
        except Exception as exc:  # provider errors are recorded and retried
            d.status = DeliveryStatus.failed
            d.last_error = str(exc)[:300]
            stats["failed"] += 1
            log(logger, logging.WARNING, "notification delivery failed", delivery=d.id, error=d.last_error)
    session.commit()
    return stats

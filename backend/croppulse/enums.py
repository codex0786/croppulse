"""Explicit enumerations shared by the database, API schemas and UI."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    farmer = "farmer"
    agronomist = "agronomist"
    fpo_manager = "fpo_manager"
    regional_analyst = "regional_analyst"
    researcher = "researcher"
    admin = "admin"


class Season(StrEnum):
    kharif = "kharif"
    rabi = "rabi"
    zaid = "zaid"
    annual = "annual"


class Irrigation(StrEnum):
    rainfed = "rainfed"
    partially_irrigated = "partially_irrigated"
    irrigated = "irrigated"
    unknown = "unknown"


class SourceStatus(StrEnum):
    live_tested = "live_tested"  # retrieved from the live service in this deployment
    implemented_untested = "implemented_untested"
    not_configured = "not_configured"  # credentials or settings missing
    unavailable = "unavailable"  # last attempt failed
    manual_entry = "manual_entry"  # human-entered from an official source
    fixture_only = "fixture_only"  # synthetic test data only


class DataKind(StrEnum):
    """How a displayed value came to exist. Shown on every value in the UI."""

    observed = "observed"  # satellite/analysis product value
    derived = "derived"  # computed from observations (aggregates, anomalies)
    estimated = "estimated"  # model output
    farmer_reported = "farmer_reported"
    expert_verified = "expert_verified"
    synthetic = "synthetic"  # test fixture; never shown as real


class RiskState(StrEnum):
    insufficient_evidence = "insufficient_evidence"
    normal_for_reference_period = "normal_for_reference_period"
    watch = "watch"
    elevated_risk = "elevated_risk"
    expert_review_recommended = "expert_review_recommended"
    verified_stress = "verified_stress"
    resolved = "resolved"


RISK_ORDER = {
    RiskState.insufficient_evidence: 0,
    RiskState.normal_for_reference_period: 0,
    RiskState.resolved: 0,
    RiskState.watch: 1,
    RiskState.elevated_risk: 2,
    RiskState.expert_review_recommended: 3,
    RiskState.verified_stress: 4,
}


class EvidenceSufficiency(StrEnum):
    sufficient = "sufficient"
    partial = "partial"
    insufficient = "insufficient"


class Freshness(StrEnum):
    current = "current"
    stale = "stale"
    unavailable = "unavailable"


class ReportSymptom(StrEnum):
    wilting = "wilting"
    yellowing = "yellowing"
    unusual_growth = "unusual_growth"
    waterlogging = "waterlogging"
    pest_or_disease = "pest_or_disease"
    irrigation_problem = "irrigation_problem"
    other = "other"


class CaseStatus(StrEnum):
    open = "open"
    assigned = "assigned"
    info_requested = "info_requested"
    inspection_scheduled = "inspection_scheduled"
    verified = "verified"
    closed = "closed"


class VerifiedFinding(StrEnum):
    stress_confirmed = "stress_confirmed"
    no_stress_found = "no_stress_found"
    false_alarm = "false_alarm"
    data_problem = "data_problem"
    inconclusive = "inconclusive"


class AlertStatus(StrEnum):
    active = "active"
    superseded = "superseded"
    expired = "expired"
    acknowledged = "acknowledged"


class DeliveryStatus(StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    suppressed = "suppressed"


class JobStatus(StrEnum):
    running = "running"
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"


class ApprovalStatus(StrEnum):
    approved = "approved"
    draft_requires_expert = "draft_requires_expert"
    retired = "retired"


class ConsentPurpose(StrEnum):
    core_service = "core_service"  # processing the field to show its own intelligence
    share_with_organization = "share_with_organization"
    expert_review = "expert_review"
    aggregated_research = "aggregated_research"
    notifications = "notifications"

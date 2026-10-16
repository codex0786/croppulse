"""SQLAlchemy ORM models.

Domain boundaries:
  identity & access  : Organization, User, ConsentRecord, AuditEvent
  fields             : Field, CropSeason
  data provenance    : DataSource, IngestionJob, DatasetVersion, Observation
  intelligence       : RiskAssessment, ModelVersion, EvaluationRun
  workflow           : FarmerReport, Photo, ExpertCase, CaseEvent, VerifiedOutcome
  alerting           : Alert, NotificationDelivery
  official content   : Advisory (manually entered official advisories)

Observation, inference and recommendation are stored separately:
  Observation (what a source reported) → RiskAssessment (what CropPulse inferred)
  → guidance keys/approved advisories (what to do next).

Geometry is stored as validated GeoJSON plus a centroid/bbox so the schema runs on
SQLite (development/tests) and PostgreSQL. See docs/ARCHITECTURE.md (ADR-003) for
the PostGIS migration path.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from croppulse.db import Base, UTCDateTime, new_id, utcnow


def _id() -> Mapped[str]:
    return mapped_column(String(32), primary_key=True, default=new_id)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))  # fpo | extension | government | research | business
    state: Mapped[str | None] = mapped_column(String(80))
    district: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = _id()
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(30), index=True)
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    organization: Mapped[Organization | None] = relationship()


class ConsentRecord(Base):
    """Append-only consent log. The latest record per (user, purpose, scope) wins."""

    __tablename__ = "consent_records"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(40))
    granted: Mapped[bool] = mapped_column(Boolean)
    scope_field_id: Mapped[str | None] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Field(Base):
    __tablename__ = "fields"
    id: Mapped[str] = _id()
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(80), default="Maharashtra")
    district: Mapped[str] = mapped_column(String(80), index=True)
    geometry_geojson: Mapped[dict[str, Any]] = mapped_column(JSON)
    geometry_source: Mapped[str] = mapped_column(String(20))  # drawn | uploaded | point
    boundary_version: Mapped[int] = mapped_column(Integer, default=1)
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lon: Mapped[float] = mapped_column(Float)
    min_lat: Mapped[float] = mapped_column(Float)
    min_lon: Mapped[float] = mapped_column(Float)
    max_lat: Mapped[float] = mapped_column(Float)
    max_lon: Mapped[float] = mapped_column(Float)
    area_ha: Mapped[float | None] = mapped_column(Float)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    owner: Mapped[User] = relationship()
    seasons: Mapped[list[CropSeason]] = relationship(back_populates="field", order_by="CropSeason.created_at")

    __table_args__ = (Index("ix_fields_bbox", "min_lat", "min_lon", "max_lat", "max_lon"),)


class CropSeason(Base):
    __tablename__ = "crop_seasons"
    id: Mapped[str] = _id()
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id"), index=True)
    crop: Mapped[str] = mapped_column(String(40))
    variety: Mapped[str | None] = mapped_column(String(80))
    season: Mapped[str] = mapped_column(String(20))
    season_year: Mapped[int] = mapped_column(Integer)
    sowing_date: Mapped[date | None] = mapped_column(Date)
    sowing_date_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    irrigation: Mapped[str] = mapped_column(String(30), default="unknown")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    field: Mapped[Field] = relationship(back_populates="seasons")


class DataSource(Base):
    """Operational state of a registered source. Static metadata lives in config/sources.yaml."""

    __tablename__ = "data_sources"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    status: Mapped[str] = mapped_column(String(30))
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    latest_observation_end: Mapped[date | None] = mapped_column(Date)
    observed_latency_days: Mapped[float | None] = mapped_column(Float)
    processing_version: Mapped[str | None] = mapped_column(String(40))


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[str] = _id()
    source_id: Mapped[str] = mapped_column(String(40), index=True)
    job_type: Mapped[str] = mapped_column(String(40))
    target_ref: Mapped[str | None] = mapped_column(String(80))  # field id or grid-cell key; never coordinates
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    records_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    message: Mapped[str | None] = mapped_column(Text)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config_version: Mapped[str | None] = mapped_column(String(20))


class DatasetVersion(Base):
    """Manifest entry for a stored analytical artifact (e.g. a Parquet weather series)."""

    __tablename__ = "dataset_versions"
    id: Mapped[str] = _id()
    source_id: Mapped[str] = mapped_column(String(40), index=True)
    dataset_key: Mapped[str] = mapped_column(String(120), index=True)
    path: Mapped[str] = mapped_column(String(400))
    sha256: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    coverage_start: Mapped[date | None] = mapped_column(Date)
    coverage_end: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    source_request: Mapped[str | None] = mapped_column(Text)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class Observation(Base):
    """A field-level aggregate of one source variable over one observation period.

    Time fields are deliberately separate:
      period_start/period_end : what the observation describes
      published_at            : when the provider produced it (if known)
      retrieved_at            : when CropPulse fetched it
      processed_at            : when CropPulse aggregated it
      available_at            : when it became usable inside CropPulse (for leakage control)
    A value of NULL means *no usable observation*; it is never coerced to zero.
    """

    __tablename__ = "observations"
    id: Mapped[str] = _id()
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(40))
    variable: Mapped[str] = mapped_column(String(40))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40))
    accepted: Mapped[bool] = mapped_column(Boolean)
    rejection_reason: Mapped[str | None] = mapped_column(String(120))
    valid_pixel_count: Mapped[int | None] = mapped_column(Integer)
    total_pixel_count: Mapped[int | None] = mapped_column(Integer)
    valid_fraction: Mapped[float | None] = mapped_column(Float)
    quality_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    aggregation_method: Mapped[str] = mapped_column(String(200))
    boundary_version: Mapped[int] = mapped_column(Integer, default=1)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime)
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_ref: Mapped[str | None] = mapped_column(String(400))

    __table_args__ = (
        UniqueConstraint("field_id", "source_id", "variable", "period_start", "revision", name="uq_obs_revision"),
        Index("ix_obs_series", "field_id", "source_id", "variable", "period_start"),
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(40))  # rules | statistical | ml
    status: Mapped[str] = mapped_column(String(20))  # research | approved | retired
    config_hash: Mapped[str] = mapped_column(String(20))
    intended_use: Mapped[str] = mapped_column(Text)
    excluded_uses: Mapped[str] = mapped_column(Text)
    training_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    evaluation_run_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    approved_by: Mapped[str | None] = mapped_column(String(32))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("name", "version"),)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[str] = _id()
    model_name: Mapped[str] = mapped_column(String(80))
    regime: Mapped[str] = mapped_column(String(40))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    data_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    report_path: Mapped[str | None] = mapped_column(String(400))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    id: Mapped[str] = _id()
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id"), index=True)
    crop_season_id: Mapped[str | None] = mapped_column(ForeignKey("crop_seasons.id"))
    assessed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    state: Mapped[str] = mapped_column(String(40))
    sufficiency: Mapped[str] = mapped_column(String(20))
    sufficiency_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    vegetation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    weather: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    soil_moisture: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    freshness: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_periods: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    explanations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    uncertainty: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    next_step_key: Mapped[str] = mapped_column(String(80))
    guidance_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    escalate_to_expert: Mapped[bool] = mapped_column(Boolean, default=False)
    model_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(40))
    model_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    config_version: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = _id()
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id"), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("risk_assessments.id"))
    rule_id: Mapped[str] = mapped_column(String(60))
    rule_version: Mapped[str] = mapped_column(String(20))
    dedupe_key: Mapped[str] = mapped_column(String(160), index=True)
    severity: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    title_key: Mapped[str] = mapped_column(String(80))
    message_key: Mapped[str] = mapped_column(String(80))
    explanation: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    next_step_key: Mapped[str] = mapped_column(String(80))
    requires_expert: Mapped[bool] = mapped_column(Boolean, default=False)
    observation_period: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_timestamps: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    superseded_by: Mapped[str | None] = mapped_column(String(32))
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[str] = _id()
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class FarmerReport(Base):
    __tablename__ = "farmer_reports"
    id: Mapped[str] = _id()
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id"), index=True)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    symptoms: Mapped[list[str]] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(Text)
    observed_on: Mapped[date] = mapped_column(Date)
    affected_fraction: Mapped[str | None] = mapped_column(String(20))  # under_quarter | quarter_half | over_half | unknown
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    client_ref: Mapped[str | None] = mapped_column(String(64), unique=True)  # offline-queue idempotency key
    request_expert: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Photo(Base):
    __tablename__ = "photos"
    id: Mapped[str] = _id()
    report_id: Mapped[str] = mapped_column(ForeignKey("farmer_reports.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    metadata_stripped: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ExpertCase(Base):
    __tablename__ = "expert_cases"
    id: Mapped[str] = _id()
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id"), index=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("farmer_reports.id"))
    assessment_id: Mapped[str | None] = mapped_column(ForeignKey("risk_assessments.id"))
    origin: Mapped[str] = mapped_column(String(30))  # farmer_request | assessment_escalation
    status: Mapped[str] = mapped_column(String(30), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 high … 3 low (from evidence, not a probability)
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    field: Mapped[Field] = relationship()
    events: Mapped[list[CaseEvent]] = relationship(order_by="CaseEvent.created_at")


class CaseEvent(Base):
    __tablename__ = "case_events"
    id: Mapped[str] = _id()
    case_id: Mapped[str] = mapped_column(ForeignKey("expert_cases.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30))
    body: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    authored_by: Mapped[str] = mapped_column(String(20), default="human")  # human | system
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class VerifiedOutcome(Base):
    """Expert-verified field finding. This — not farmer reports or model output — is the label table."""

    __tablename__ = "verified_outcomes"
    id: Mapped[str] = _id()
    case_id: Mapped[str] = mapped_column(ForeignKey("expert_cases.id"), unique=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id"), index=True)
    finding: Mapped[str] = mapped_column(String(30))
    suspected_cause: Mapped[str | None] = mapped_column(String(80))
    observed_on: Mapped[date] = mapped_column(Date)
    verified_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    method: Mapped[str] = mapped_column(String(30))  # field_inspection | remote_review | phone_call
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)


class Advisory(Base):
    """Manually entered official advisory (e.g. IMD) with mandatory source reference."""

    __tablename__ = "advisories"
    id: Mapped[str] = _id()
    source_org: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(40))  # heat_warning | heavy_rain | agromet | other
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    districts: Mapped[list[str]] = mapped_column(JSON, default=list)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime)
    entered_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = _id()
    actor_id: Mapped[str | None] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(60))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(20), default="success")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

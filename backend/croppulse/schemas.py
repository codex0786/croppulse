"""Typed API contracts (Pydantic v2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from croppulse.enums import (
    CaseStatus,
    ConsentPurpose,
    EvidenceSufficiency,
    Irrigation,
    ReportSymptom,
    RiskState,
    Role,
    Season,
    VerifiedFinding,
)

LANGS = Literal["en", "hi", "mr"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class ErrorOut(BaseModel):
    detail: str


# ------------------------------------------------------------------ auth


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)
    preferred_language: LANGS = "en"
    organization_id: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: int


class UserOut(ORM):
    id: str
    email: str
    display_name: str
    role: Role
    preferred_language: str
    organization_id: str | None


class ConsentIn(BaseModel):
    purpose: ConsentPurpose
    granted: bool


class ConsentsOut(BaseModel):
    policy_version: str
    consents: dict[str, bool]


class LanguageIn(BaseModel):
    preferred_language: LANGS


# ------------------------------------------------------------------ fields


class SeasonIn(BaseModel):
    crop: str = Field(min_length=1, max_length=40)
    variety: str | None = Field(default=None, max_length=80)
    season: Season
    season_year: int = Field(ge=2000, le=2100)
    sowing_date: date | None = None
    sowing_date_uncertain: bool = False
    irrigation: Irrigation = Irrigation.unknown

    @field_validator("sowing_date")
    @classmethod
    def _not_future(cls, v: date | None) -> date | None:
        if v is not None and v > date.today():
            raise ValueError("sowing_date cannot be in the future")
        return v


class SeasonOut(ORM):
    id: str
    crop: str
    variety: str | None
    season: str
    season_year: int
    sowing_date: date | None
    sowing_date_uncertain: bool
    irrigation: str
    active: bool


class FieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    district: str = Field(min_length=2, max_length=80)
    state: str = "Maharashtra"
    geometry: dict[str, Any]
    season: SeasonIn
    share_with_organization: bool = False


class BoundaryCheckIn(BaseModel):
    geometry: dict[str, Any]


class BoundaryCheckOut(BaseModel):
    valid: bool
    error: str | None = None
    area_ha: float | None = None
    kind: str | None = None
    warnings: list[str] = []


class FieldOut(ORM):
    id: str
    name: str
    state: str
    district: str
    geometry_geojson: dict[str, Any]
    geometry_source: str
    boundary_version: int
    area_ha: float | None
    centroid_lat: float
    centroid_lon: float
    organization_id: str | None
    is_synthetic: bool
    created_at: datetime
    seasons: list[SeasonOut]
    is_owner: bool = False


class FieldSummary(BaseModel):
    id: str
    name: str
    district: str
    crop: str | None
    season: str | None
    area_ha: float | None
    latest_state: RiskState | None
    latest_assessed_at: datetime | None
    is_synthetic: bool


# ------------------------------------------------------------------ observations


class VegetationPoint(BaseModel):
    period_start: date
    period_end: date
    value: float | None
    accepted: bool
    rejection_reason: str | None
    valid_fraction: float | None
    reference_median: float | None
    reference_p10: float | None
    reference_p90: float | None
    reference_n: int
    published_at: datetime | None
    is_synthetic: bool


class VegetationSeriesOut(BaseModel):
    variable: str
    unit: str
    source_id: str
    data_kind: str
    aggregation_method: str | None
    retrieved_at: datetime | None
    reference_description: str
    points: list[VegetationPoint]
    is_synthetic: bool


class WeatherDaily(BaseModel):
    date: date
    precipitation_mm: float | None
    tmax_c: float | None
    tmin_c: float | None


class WeatherOut(BaseModel):
    source_id: str
    data_kind: str
    grid_cell: dict[str, float] | None
    units: dict[str, str]
    retrieved_at: datetime | None
    last_valid_date: date | None
    daily: list[WeatherDaily]
    is_synthetic: bool


# ------------------------------------------------------------------ assessments


class CheckOut(BaseModel):
    id: str
    passed: bool
    severity: str
    detail: str
    params: dict[str, Any] = {}


class GuidanceOut(BaseModel):
    id: str
    language: str
    body: str
    translation_pending: bool
    unreviewed_translation: str | None
    source_org: str | None
    source_ref: str | None
    limitations: str


class AssessmentOut(ORM):
    id: str
    field_id: str
    assessed_at: datetime
    as_of: datetime
    state: RiskState
    sufficiency: EvidenceSufficiency
    sufficiency_checks: list[CheckOut]
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
    model_name: str
    model_version: str
    model_validated: bool
    config_version: str
    expires_at: datetime
    is_synthetic: bool
    is_expired: bool = False
    guidance: list[GuidanceOut] = []


class RefreshOut(BaseModel):
    jobs: list[dict[str, Any]]
    assessment: AssessmentOut | None
    alert_outcome: str | None


# ------------------------------------------------------------------ reports & cases


class ReportIn(BaseModel):
    symptoms: list[ReportSymptom] = Field(min_length=1, max_length=7)
    description: str | None = Field(default=None, max_length=2000)
    observed_on: date
    affected_fraction: Literal["under_quarter", "quarter_half", "over_half", "unknown"] = "unknown"
    answers: dict[str, str] = Field(default_factory=dict)
    request_expert: bool = False
    client_ref: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")

    @field_validator("observed_on")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("observed_on cannot be in the future")
        return v

    @field_validator("answers")
    @classmethod
    def _small_answers(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 20 or any(len(k) > 60 or len(x) > 500 for k, x in v.items()):
            raise ValueError("answers too large")
        return v


class PhotoOut(ORM):
    id: str
    content_type: str
    size_bytes: int
    metadata_stripped: bool
    created_at: datetime


class ReportOut(ORM):
    id: str
    field_id: str
    symptoms: list[str]
    description: str | None
    observed_on: date
    affected_fraction: str | None
    request_expert: bool
    created_at: datetime
    case_id: str | None = None
    photos: list[PhotoOut] = []


class CaseEventIn(BaseModel):
    kind: Literal["comment", "info_request", "inspection_scheduled", "recommendation"]
    body: str = Field(min_length=1, max_length=4000)
    scheduled_for: date | None = None
    source_ref: str | None = Field(default=None, max_length=500)


class CaseEventOut(ORM):
    id: str
    actor_id: str
    kind: str
    body: str | None
    data: dict[str, Any]
    authored_by: str
    created_at: datetime


class VerifyIn(BaseModel):
    finding: VerifiedFinding
    suspected_cause: str | None = Field(default=None, max_length=80)
    observed_on: date
    method: Literal["field_inspection", "remote_review", "phone_call"]
    notes: str | None = Field(default=None, max_length=4000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class VerifiedOutcomeOut(ORM):
    id: str
    finding: str
    suspected_cause: str | None
    observed_on: date
    verified_by: str
    verified_at: datetime
    method: str
    notes: str | None


class CaseOut(BaseModel):
    id: str
    field_id: str
    field_name: str
    district: str
    crop: str | None
    origin: str
    status: CaseStatus
    priority: int
    assigned_to: str | None
    created_at: datetime
    updated_at: datetime
    age_days: int
    latest_state: str | None


class CaseDetail(CaseOut):
    events: list[CaseEventOut]
    report: ReportOut | None
    assessment: AssessmentOut | None
    outcome: VerifiedOutcomeOut | None


class AssignIn(BaseModel):
    assignee_id: str | None = None  # None = assign to self


# ------------------------------------------------------------------ alerts


class AlertOut(ORM):
    id: str
    field_id: str
    assessment_id: str
    rule_id: str
    rule_version: str
    severity: str
    status: str
    title_key: str
    message_key: str
    explanation: list[dict[str, Any]]
    next_step_key: str
    requires_expert: bool
    observation_period: dict[str, Any]
    source_timestamps: dict[str, Any]
    model_version: str
    created_at: datetime
    expires_at: datetime
    acknowledged_at: datetime | None


# ------------------------------------------------------------------ advisories


class AdvisoryIn(BaseModel):
    source_org: Literal["IMD", "State Agriculture Department", "KVK", "Other official"]
    source_url: str = Field(pattern=r"^https://", max_length=500)
    kind: Literal["heat_warning", "heavy_rain", "agromet", "other"]
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=3, max_length=4000)
    districts: list[str] = Field(min_length=1)
    issued_at: datetime
    valid_until: datetime


class AdvisoryOut(ORM):
    id: str
    source_org: str
    source_url: str
    kind: str
    title: str
    body: str
    districts: list[str]
    issued_at: datetime
    valid_until: datetime
    created_at: datetime

export type Role = "farmer" | "agronomist" | "fpo_manager" | "regional_analyst" | "researcher" | "admin";
export type RiskState =
  | "insufficient_evidence"
  | "normal_for_reference_period"
  | "watch"
  | "elevated_risk"
  | "expert_review_recommended"
  | "verified_stress"
  | "resolved";
export type DataKind = "observed" | "derived" | "estimated" | "farmer_reported" | "expert_verified" | "expert_authored" | "synthetic";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  preferred_language: string;
  organization_id: string | null;
}

export interface Season {
  id: string;
  crop: string;
  variety: string | null;
  season: string;
  season_year: number;
  sowing_date: string | null;
  sowing_date_uncertain: boolean;
  irrigation: string;
  active: boolean;
}

export interface FieldOut {
  id: string;
  name: string;
  state: string;
  district: string;
  geometry_geojson: GeoJSON.Geometry;
  geometry_source: string;
  boundary_version: number;
  area_ha: number | null;
  centroid_lat: number;
  centroid_lon: number;
  is_synthetic: boolean;
  created_at: string;
  seasons: Season[];
  is_owner: boolean;
}

export interface FieldSummary {
  id: string;
  name: string;
  district: string;
  crop: string | null;
  season: string | null;
  area_ha: number | null;
  latest_state: RiskState | null;
  latest_assessed_at: string | null;
  is_synthetic: boolean;
}

export interface Explanation {
  key: string;
  kind: DataKind;
  source?: string;
  params: Record<string, string | number | boolean | null>;
}

export interface Check {
  id: string;
  passed: boolean;
  severity: string;
  detail: string;
  params: Record<string, unknown>;
}

export interface Guidance {
  id: string;
  language: string;
  body: string;
  translation_pending: boolean;
  unreviewed_translation: string | null;
  source_org: string | null;
  source_ref: string | null;
  limitations: string;
}

export interface FreshnessEntry {
  status: "current" | "stale" | "unavailable";
  period_end?: string | null;
  window_end?: string | null;
  age_days?: number | null;
  max_age_days?: number;
}

export interface Assessment {
  id: string;
  field_id: string;
  assessed_at: string;
  as_of: string;
  state: RiskState;
  sufficiency: "sufficient" | "partial" | "insufficient";
  sufficiency_checks: Check[];
  vegetation: Record<string, any>;
  weather: Record<string, any>;
  soil_moisture: Record<string, any>;
  context: Record<string, any>;
  freshness: { vegetation: FreshnessEntry; weather: FreshnessEntry; soil_moisture: FreshnessEntry };
  explanations: Explanation[];
  uncertainty: Record<string, any>;
  next_step_key: string;
  guidance: Guidance[];
  escalate_to_expert: boolean;
  model_name: string;
  model_version: string;
  model_validated: boolean;
  config_version: string;
  expires_at: string;
  is_expired: boolean;
  is_synthetic: boolean;
}

export interface VegPoint {
  period_start: string;
  period_end: string;
  value: number | null;
  accepted: boolean;
  rejection_reason: string | null;
  valid_fraction: number | null;
  reference_median: number | null;
  reference_p10: number | null;
  reference_p90: number | null;
  reference_n: number;
  published_at: string | null;
  is_synthetic: boolean;
}

export interface VegSeries {
  variable: string;
  unit: string;
  source_id: string;
  data_kind: string;
  aggregation_method: string | null;
  retrieved_at: string | null;
  reference_description: string;
  points: VegPoint[];
  is_synthetic: boolean;
}

export interface WeatherOut {
  source_id: string;
  grid_cell: { lat: number; lon: number } | null;
  units: Record<string, string>;
  retrieved_at: string | null;
  last_valid_date: string | null;
  daily: { date: string; precipitation_mm: number | null; tmax_c: number | null; tmin_c: number | null }[];
  is_synthetic: boolean;
}

export interface Alert {
  id: string;
  field_id: string;
  severity: RiskState;
  status: string;
  title_key: string;
  message_key: string;
  explanation: Explanation[];
  next_step_key: string;
  requires_expert: boolean;
  observation_period: Record<string, any>;
  source_timestamps: Record<string, any>;
  model_version: string;
  rule_id: string;
  rule_version: string;
  created_at: string;
  expires_at: string;
  acknowledged_at: string | null;
}

export interface CaseOut {
  id: string;
  field_id: string;
  field_name: string;
  district: string;
  crop: string | null;
  origin: string;
  status: string;
  priority: number;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
  age_days: number;
  latest_state: RiskState | null;
}

export interface CaseEvent {
  id: string;
  actor_id: string;
  kind: string;
  body: string | null;
  data: Record<string, any>;
  authored_by: "human" | "system";
  created_at: string;
}

export interface Report {
  id: string;
  field_id: string;
  symptoms: string[];
  description: string | null;
  observed_on: string;
  affected_fraction: string | null;
  request_expert: boolean;
  created_at: string;
  case_id: string | null;
  photos: { id: string; content_type: string; size_bytes: number }[];
}

export interface CaseDetail extends CaseOut {
  events: CaseEvent[];
  report: Report | null;
  assessment: Assessment | null;
  outcome: { finding: string; suspected_cause: string | null; observed_on: string; verified_by: string; verified_at: string; method: string; notes: string | null } | null;
}

export interface SourceInfo {
  id: string;
  name: string;
  provider: string;
  status: string;
  documentation: string[];
  license: string;
  spatial_resolution: string;
  temporal_resolution: string;
  typical_latency: string;
  limitations: string[];
  last_success_at: string | null;
  last_error: string | null;
  latest_observation_end: string | null;
  observed_latency_days: number | null;
  verified_on: string | null;
}

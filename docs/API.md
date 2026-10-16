# API

Interactive OpenAPI docs: `http://127.0.0.1:8000/docs`; schema: `/openapi.json` (generated from the Pydantic
models, always current). All endpoints except `/health`, `/ready`, `/api/v1/sources`, `/api/v1/features`,
`/api/v1/models`, `/api/v1/evaluations`, `/api/v1/yield` and the auth endpoints require `Authorization: Bearer <token>`.

Errors: `{"detail": "..."}` (validation errors add `errors[]` with location/message, never the submitted value).
Unauthorised access to another user's resource returns **404** (not 403) to prevent enumeration.

| Method | Path | Roles | Purpose |
|---|---|---|---|
| GET | /health | public | Liveness (no dependency checks) |
| GET | /ready | public | DB reachable + migrated, config loads |
| POST | /api/v1/auth/login | public (rate-limited) | Token |
| POST | /api/v1/auth/register | public (rate-limited) | Farmer self-registration (role always farmer) |
| GET | /api/v1/auth/me | any | Current user |
| PUT | /api/v1/me/language | any | Preferred language |
| GET/POST | /api/v1/me/consents | any | Read / change consent (append-only log) |
| POST | /api/v1/me/deletion-request | any | Record a deletion request |
| GET | /api/v1/fields/reference-data | public | Crops, seasons, districts, calendar review status |
| POST | /api/v1/fields/validate-boundary | any | Validate GeoJSON without saving |
| POST/GET | /api/v1/fields | farmer / org roles | Create; list (owner, or consented org fields) |
| GET/DELETE | /api/v1/fields/{id} | owner, consented org, admin | Read; soft-delete (owner) |
| PUT | /api/v1/fields/{id}/boundary | owner | New boundary version |
| POST | /api/v1/fields/{id}/seasons | owner | New active crop season |
| POST | /api/v1/fields/{id}/refresh | owner, agronomist, admin | Background ingestion + assessment (202) |
| GET | /api/v1/fields/{id}/jobs | readers | Ingestion job status for the field and its weather cell |
| POST | /api/v1/fields/{id}/assess | owner, agronomist, admin | Re-assess on stored data |
| GET | /api/v1/fields/{id}/assessments[/latest] | readers | Assessment history / latest (with rendered approved guidance) |
| GET | /api/v1/fields/{id}/vegetation?variable&years | readers | NDVI/EVI composites + reference band |
| GET | /api/v1/fields/{id}/weather?days | readers | Daily POWER series for the field's grid cell |
| POST/GET | /api/v1/fields/{id}/reports | owner / readers | Farmer report (idempotent `client_ref`) |
| POST | /api/v1/reports/{id}/photos | reporter | JPEG/PNG ≤ 5 MB, metadata stripped |
| GET | /api/v1/fields/{id}/cases, /recommendations | readers | Case status; expert-authored entries only |
| GET | /api/v1/cases | agronomist, admin | Queue (filters: status, district, crop, risk_state, min_age_days) |
| GET | /api/v1/cases/{id} | agronomist (same org), admin | Detail with evidence, report, history, outcome |
| POST | /api/v1/cases/{id}/assign, /events, /close, /reopen | agronomist, admin | Workflow |
| POST | /api/v1/cases/{id}/verify | agronomist (same org) | Verified finding (one per case) |
| GET | /api/v1/alerts; POST /alerts/{id}/acknowledge | owner | Active alerts |
| GET | /api/v1/regional/summary | regional_analyst, researcher, admin | k-suppressed aggregates, no identifiers |
| GET | /api/v1/org/summary; /org/export.csv | fpo_manager (+agronomist summary) | Consented org fields; aggregated CSV |
| GET | /api/v1/sources, /features, /models, /evaluations | public | Provenance & research metadata |
| GET | /api/v1/yield | public | 501 — disabled with reason |
| GET | /api/v1/advisories | any | Current manually-entered official advisories |
| POST | /api/v1/admin/advisories | admin | Enter official advisory (https source URL required) |
| GET | /api/v1/admin/jobs, /admin/audit, /admin/metrics | admin | Operations |

Pagination: `limit`/`offset` on list endpoints where result sets can grow (fields, cases, assessments, jobs, audit).

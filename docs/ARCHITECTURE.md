# Architecture

## Components

```
                    ┌──────────────────────── external, public ─────────────────────────┐
                    │ ORNL DAAC TESViS (MOD13Q1, MCD12Q1)   NASA POWER daily   (Earthdata: │
                    │                                                   IMERG, SMAP — n/c)│
                    └───────────────┬───────────────────────────┬────────────────────────┘
                                    │ HTTPS, retries, raw cache │
 ┌────────────────────────── backend/croppulse (Python 3.12) ───┴──────────────────────────────┐
 │ sources/        typed adapters, schema checks, units, fill/quality decoding, synthetic flag │
 │ ingestion/      jobs (idempotent upsert + revisions), quality checks, source state, Parquet │
 │ geo/            GeoJSON validation, area, MODIS sinusoidal pixel selection                   │
 │ science/        seasonal anomaly (z, robust z, percentile, bootstrap), weather features,    │
 │                 feature registry                                                             │
 │ risk/           engine (pure function: evidence → gate → state → explanations),             │
 │                 service (load from DB, persist, alert, escalate)                             │
 │ alerting/       rules (YAML), dedupe/cooldown/escalation/expiry, delivery providers          │
 │ guidance/       approved, source-backed text library (YAML), translation status             │
 │ research/       splits, leakage checks, metrics, bootstrap, backtest, real-data pipeline     │
 │ governance.py   consent, access rules, audit                                                 │
 │ api/            FastAPI app, routers, request metrics, security headers                      │
 └───────────────┬──────────────────────────────────────────────┬──────────────────────────────┘
                 │ SQLAlchemy (SQLite dev / PostgreSQL)          │ Parquet (data/processed)
          ┌──────┴──────┐                                 ┌──────┴───────┐
          │ relational  │ users, orgs, consent, fields,   │ analytical   │ POWER daily per grid cell,
          │ store       │ observations, assessments,      │ files        │ research tables; raw JSON
          └─────────────┘ alerts, cases, outcomes, audit  └──────────────┘ responses in data/raw
                 ▲
                 │ JSON over HTTPS (/api/v1, bearer token)
 ┌───────────────┴────────────── web (Next.js 14, TypeScript) ──────────────────────────────────┐
 │ farmer: register, fields, field intelligence, report (offline queue), alerts, profile/consent │
 │ expert: case queue, case review, verification   · org (FPO) · regional · research · admin      │
 │ shared: i18n (en/hi/mr + review status), status components, SVG charts, Leaflet map, PWA shell │
 └───────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Data flow

`source → adapter (raw cached, schema/units checked) → quality checks → Observation rows / Parquet
(+ DatasetVersion manifest) → features (anomaly, weather) → RiskAssessment (state, evidence gate,
explanations, uncertainty, freshness) → Alert (rules) → NotificationDelivery → UI`

Farmer reports and expert cases run alongside; only `VerifiedOutcome` (expert-verified) feeds evaluation labels.

## Time model

Every observation keeps: `period_start/period_end` (what it describes), `published_at` (provider processing time,
MODIS `proc_date`), `retrieved_at`, `processed_at`, `available_at` (usable in CropPulse). Assessments record
`as_of`, `assessed_at` and `expires_at`. The engine ignores anything with `available_at > as_of`.

## Architecture decision records

**ADR-001 — Separate project directory.** The supplied folder contained unrelated apps; CropPulse lives in
`croppulse/` with its own Git history (see REPOSITORY_AUDIT.md).

**ADR-002 — Python FastAPI + Next.js.** Matches the brief's defaults; the scientific stack (NumPy/pandas/Shapely)
and the API share one language; Next.js gives a small, mobile-first PWA. No chart library (hand-rolled SVG) and
Leaflet for maps keep first-load JS ≈ 115–122 kB.

**ADR-003 — Geometry as validated GeoJSON + bbox/centroid columns, not PostGIS (yet).** The local PostgreSQL has no
PostGIS and the MVP needs no spatial SQL (fields are looked up by id; regional grouping is by district and
grid-cell key). Geometry validation uses Shapely. Migration path: add a PostGIS `geometry(Polygon, 4326)` column
populated from GeoJSON plus a GiST index when spatial queries (e.g. "fields within a district boundary") are needed;
the compose file already uses the `postgis/postgis` image.

**ADR-004 — ORNL TESViS for MODIS instead of LP DAAC granules.** TESViS returns point-centred subsets with the
native sinusoidal grid geometry and per-composite `proc_date`, without Earthdata credentials. Trade-offs: ~10–45 s
per request and ≤ 10 composites per request (a field's 17-year history ≈ 40–60 requests). Granule/HDF processing
with rasterio would be needed for wall-to-wall regional products (roadmap).

**ADR-005 — Rules-based screening before ML.** No independent labels exist yet; a transparent rule set with an
explicit evidence gate is auditable and cannot overfit. ML models are deferred until labelled outcomes allow
temporal and geographic validation (VALIDATION_PROTOCOL.md).

**ADR-006 — Weather per POWER grid cell.** POWER meteorology is 0.5° × 0.625°; storing per cell avoids duplicate
downloads and never sends a farmer's exact coordinates to the provider (the cell centre is requested).

**ADR-007 — In-process background tasks and cron script instead of Celery.** Workload is small; field refresh uses
FastAPI background tasks and `scripts/run_ingestion.py` is the scheduler entry point. A queue (Celery/RQ) is the
upgrade path when concurrent refreshes or multiple API instances are needed.

**ADR-008 — Stateless HMAC bearer tokens.** Standard-library implementation (PBKDF2 password hashing, HMAC-SHA256
tokens, 12 h expiry). Tokens are held in `sessionStorage` by the web app. Upgrade path: httpOnly SameSite cookies +
CSRF protection, token revocation list, refresh tokens (SECURITY_AND_PRIVACY.md).

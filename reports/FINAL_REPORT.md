# CropPulse — engineering report, build session 1 (2026-10-15)

## A. What I found
- `~/Downloads/rcsa2` held two unrelated projects (an RCSA accounts-payable Next.js app and a Python policy-evaluation
  project), no Git repo and no CropPulse code. Nothing was reusable; nothing was modified except an additive entry in
  `rcsa2/.claude/launch.json`. CropPulse was built from scratch in `rcsa2/croppulse/` with its own Git history
  (docs/REPOSITORY_AUDIT.md).
- Environment: Python 3.12, Node 26, PostgreSQL 18 (no PostGIS), Docker CLI without a running daemon, open network
  access to NASA POWER and ORNL DAAC, no Earthdata credentials.

## B. What I built
- **Backend** (FastAPI, SQLAlchemy 2, Alembic; 22 tables): config validation, auth (PBKDF2 + HMAC tokens), RBAC with
  consent-gated organisation sharing, audit log, 47 versioned endpoints with OpenAPI.
- **Data connectors**: MODIS MOD13Q1 + MCD12Q1 via ORNL TESViS and NASA POWER (live), with retries, raw-response cache,
  schema/unit checks, fill and quality decoding, provenance timestamps, observation revisions and source status;
  Earthdata (IMERG, SMAP) contracts reporting `not_configured`; IMD manual-advisory workflow; DES crop-statistics importer.
- **Science**: sinusoidal-grid pixel selection, seasonal standard/robust anomalies with bootstrap sensitivity, weather
  windows/percentiles/dry spells/heat, feature registry, evidence-sufficiency gate, rule-based screening engine with
  abstention and generated explanations, alert engine (dedupe, cooldown, escalation, expiry, stale suppression,
  consent-aware delivery), evaluation framework (temporal/geographic splits, leakage checks, PR-AUC, Brier, log loss,
  reliability, block bootstrap, backtest with simulated availability).
- **Web** (Next.js 14, TypeScript): farmer registration with consent, map boundary drawing / GPS point / GeoJSON,
  field intelligence page (state, guidance, explanations, uncertainty, evidence checks, freshness, NDVI chart with
  historical band, rainfall chart, map, expert status), problem reports with photos and offline queue, alerts, profile
  and consent management; expert queue and case console with verification; FPO overview + aggregated CSV; regional
  dashboard with k-suppression; research provenance page; admin (advisories, jobs, metrics). en/hi/mr localisation with
  review status; PWA shell.
- **Ops/docs**: Makefile, .env.example, Dockerfiles, docker-compose (PostGIS), CI workflow, scheduler/backup scripts,
  15 documents in docs/.

## C. What I actually tested

| Command | Ran | Result | Notes |
|---|---|---|---|
| `cd backend && pytest` (offline) | yes | **99 passed**, 3 live deselected | unit, integration, scientific, security, e2e (TestClient) with synthetic fixtures |
| `pytest -m live` | yes | **3 passed** | real NASA POWER, MOD13Q1, MCD12Q1 responses |
| `alembic upgrade head && alembic check` on SQLite | yes | pass | |
| same on PostgreSQL 18.3 | yes | pass | temporary DB `croppulse_migration_check` |
| `ruff check`, `ruff format` | yes | pass | |
| `mypy croppulse` | yes | pass (49 files) | |
| `web: npm test` (i18n key/placeholder tests) | yes | 5 passed | |
| `web: tsc --noEmit`, `next lint`, `next build` | yes | pass | first-load JS 107–122 kB |
| `docker compose config` | yes | valid | |
| `docker compose up --build` | **no** | — | Docker daemon not running |
| CI workflow | **no** | — | not pushed anywhere |
| Browser verification of running UI | **attempted, not completed** | — | desktop preview processes stalled before start (likely a pending macOS permission prompt); UI verified only by build/type/lint/i18n tests |
| `scripts/seed_dev.py --synthetic-demo` | yes | pass | 6 dev accounts (credentials in gitignored `data/dev_credentials.txt`) |
| `make evaluate` | yes | pass | see section E |

Bugs found during live use (fixed, with regression tests): ingestion held an open SQLite write transaction during
slow NASA downloads, so concurrent field registration failed with "database is locked"; 500 responses lacked CORS
headers, so the browser showed "Failed to fetch" instead of the error.

Bugs found and fixed by tests: zero-percentile treated as "not low" (falsy 0 in `percentile or 100`), division by zero
on an empty reference sample, missing org commit in fixtures; two of my own hand-calculated test expectations were wrong
and were corrected.

## D. Data status

| Source | Classification |
|---|---|
| MODIS MOD13Q1 (ORNL) | Live integration tested |
| MODIS MCD12Q1 (ORNL) | Live integration tested |
| NASA POWER daily | Live integration tested |
| GPM IMERG | Awaiting credentials (Earthdata) |
| SMAP L4 | Awaiting credentials (Earthdata) |
| IMD | Unavailable programmatically → manual official-advisory entry |
| DES crop statistics | Importer implemented, no file imported (manual download needed) |
| District boundaries | Not imported |
| Agmarknet / e-NAM | Unavailable / disabled for MVP |
| Synthetic fixtures | Simulated test fixture only (flagged end-to-end) |

Real data actually downloaded and checksummed: see `reports/artifacts/research_data_manifest.json`.

## E. Scientific status
- **Datasets actually available and downloaded** (checksums in `reports/artifacts/research_data_manifest.json`):
  MOD13Q1 NDVI + pixel reliability, 569 composites (2002-01-01 → 2026-09-29) at 4 public Marathwada cropland sample
  points (S1, S3, S5, S7; MCD12Q1 2024 class 12); NASA POWER daily 1981 → 2026-10-12 for their 4 grid cells.
  Also recorded real response fixtures for parser tests.
- **Coverage finding**: usable composites ≈ 82–84 % overall but only ≈ 18–24 % in July and ≈ 44–62 % in June/August
  (monsoon cloud) — `reports/DATA_COVERAGE_REPORT.md`.
- **Baselines/models implemented**: historical seasonal reference (standard z, robust z, percentile, bootstrap
  sensitivity), weather percentile/deficit/dry-spell/heat indicators, `screening-rules@0.1.0` (rules). Logistic
  ablation code exists and was exercised on synthetic data only.
- **Validation procedures that ran on real data**: descriptive, unlabelled backtest — 96 assessments (4 points × 8
  kharif seasons 2018–2025 × 3 dates) with simulated publication latency. Abstention 70.8 %, watch 15.6 %,
  elevated 0 %; abstention falls to 53.1 % with ±1-composite reference pooling (label-free sensitivity).
  Standard and robust z flags agreed in 100 % of comparable cases; Spearman(NDVI robust z, 30-day rain percentile) = 0.16.
  `reports/BASELINE_BACKTEST.md`, predictions in `reports/artifacts/backtest_predictions.csv`.
- **Metrics with labels**: none — **no independent labels exist**, so precision/recall/PR-AUC/lead time/calibration were
  not computed on real data. The research question remains unresolved.
- **Synthetic mechanics check** (`reports/SYNTHETIC_EVALUATION_MECHANICS.md`) verifies the evaluation code; its numbers are
  not results.
- **Leakage**: guarded by design and by 9 scientific tests; residual risks — MODIS archive reprocessing (historic values
  are C6.1 reprocessed, not what was available at the time), latest-year land-cover map used as context.
- **Operational approval**: **no model is approved** (`model_versions.status = research`, `risk.model_validated = false`).
- **Yield prediction**: disabled (no labels).

## F. Known limitations
docs/LIMITATIONS.md (scientific, data, product, engineering) and docs/SECURITY_AND_PRIVACY.md §Known gaps.
Not ready for real farmer decisions: no validation, unreviewed translations, no legal review.

## G. How to run it

```bash
cd croppulse
make setup                     # venv + backend deps + web npm ci
cp .env.example .env           # configuration (no credentials required)
make migrate                   # database
make seed                      # dev accounts + labelled synthetic demo field
make api                       # backend  → http://127.0.0.1:8000/docs
make web                       # frontend → http://localhost:3000
make test                      # tests (add: make test-live)
make ingest                    # ingestion + assessment for all real fields
make research-fetch            # real data for research points (feature/data generation; slow)
make evaluate                  # reports/ (coverage, backtest, synthetic mechanics)
make docker-up                 # containers (needs Docker; POSTGRES_PASSWORD + CROPPULSE_SECRET_KEY in .env)
```

## H. Next priorities
See docs/ROADMAP.md: (1) independent labels via a partner pilot with stratified inspections; (2) Sentinel-2 for field-scale
attribution; (3) Earthdata IMERG/SMAP integration; (4) security hardening + Docker/CI verification + legal review;
(5) reviewed Marathi localisation and official crop calendars.

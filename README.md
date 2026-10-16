# CropPulse

Satellite- and weather-based **crop-stress screening and decision support** for India (Maharashtra pilot).
CropPulse compares a field's recent NASA MODIS greenness and NASA POWER weather with the same time of year in earlier
years, says how unusual it is, how old the data are and how confident it can be — and routes unusual cases to
agronomists who record verified findings.

> **Status: research prototype.** The screening rules are **not validated** against independent outcomes. Outputs are
> prompts to inspect a field, never diagnoses, crop-loss assessments or official determinations. See
> [docs/LIMITATIONS.md](docs/LIMITATIONS.md) and [reports/FINAL_REPORT.md](reports/FINAL_REPORT.md).

## What separates observation, inference and recommendation

| | Example | Labelled in UI as |
|---|---|---|
| Observation | NDVI 0.42 for 14–29 Sep, 9/9 pixels cloud-free | Observed (+ source, period) |
| Derived indicator | 4th percentile vs 2011–2025, robust z −1.9 | Derived |
| Screening state | `watch` (unvalidated rules, no probability) | Model estimate |
| Farmer input | "wilting, ¼–½ of field" | Farmer-reported |
| Expert finding | "stress confirmed, field inspection" | Expert-verified |
| Guidance | "Check the field … does not establish its cause" | Approved process guidance |

## Quick start (no credentials needed)

```bash
make setup && cp .env.example .env
make migrate
make seed     # dev accounts → data/dev_credentials.txt, plus a clearly labelled SYNTHETIC demo field
make api      # http://127.0.0.1:8000/docs
make web      # http://localhost:3000
```

Registering a field in the web app triggers **live** downloads from ORNL DAAC (MODIS) and NASA POWER (first run ≈ 30 min
for ~16 years of composites). Without network access, sources show as `unavailable` and assessments abstain — nothing
is filled in with invented data.

## Commands

| Command | What it does |
|---|---|
| `make test` | 93 backend tests (unit, integration, scientific/leakage, security, e2e; offline synthetic fixtures) + web i18n tests |
| `make test-live` | Tests against the real NASA/ORNL services |
| `make lint` / `make typecheck` | ruff + next lint / mypy + tsc |
| `make migrate` | Alembic migrations (SQLite or PostgreSQL) |
| `make ingest` | Ingest + assess all real fields; deliver notifications |
| `make research-fetch` | Download real data for public research sample points (slow) |
| `make evaluate` / `make report` | Coverage report, unlabelled backtest (real data), synthetic mechanics check |
| `make docker-up` | PostGIS + API + web via Docker Compose (not verified in the build environment) |
| `make backup` | Consistent SQLite backup |

## Layout

```
backend/croppulse/   sources/ ingestion/ geo/ science/ risk/ alerting/ guidance/ research/ api/ devtools/
backend/tests/       unit/ integration/ scientific/ security/ e2e/ fixtures/recorded (real responses)
backend/migrations/  Alembic
web/                 Next.js app (app/, components/, lib/, locales/ en·hi·mr)
config/              science.yaml, alert_rules.yaml, guidance.yaml, sources.yaml, crop_calendar.yaml, research_points.yaml
scripts/             seed, ingestion scheduler, research fetch, evaluation, docs generation, backup
reports/             generated scientific reports + artifacts
docs/                see below
```

## Documentation

[Repository audit](docs/REPOSITORY_AUDIT.md) · [Architecture & ADRs](docs/ARCHITECTURE.md) ·
[Data dictionary](docs/DATA_DICTIONARY.md) · [Data sources](docs/DATA_SOURCES.md) ·
[Data feasibility](docs/DATA_FEASIBILITY.md) · [Scientific methodology](docs/SCIENTIFIC_METHODOLOGY.md) ·
[Validation protocol](docs/VALIDATION_PROTOCOL.md) · [Model card](docs/MODEL_CARD.md) · [API](docs/API.md) ·
[Security & privacy](docs/SECURITY_AND_PRIVACY.md) · [Deployment](docs/DEPLOYMENT.md) ·
[Operations](docs/OPERATIONS.md) · [Pilot protocol](docs/PILOT_PROTOCOL.md) · [Limitations](docs/LIMITATIONS.md) ·
[Roadmap](docs/ROADMAP.md)

## Data acknowledgements

MODIS MOD13Q1 / MCD12Q1 Collection 6.1 (NASA LP DAAC), subsets via the ORNL DAAC MODIS/VIIRS web service.
NASA Langley Research Center (LaRC) POWER Project, funded through the NASA Earth Science/Applied Science Program.
Base map © OpenStreetMap contributors.

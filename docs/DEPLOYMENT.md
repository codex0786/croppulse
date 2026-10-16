# Deployment

## Local development (verified on macOS, 2026-10-15)

```bash
make setup          # Python 3.12 venv + backend deps; npm ci for web
cp .env.example .env
make migrate        # SQLite at data/croppulse.db
make seed           # dev accounts (passwords → data/dev_credentials.txt) + SYNTHETIC demo field
make api            # http://127.0.0.1:8000 (docs at /docs)
make web            # http://localhost:3000
```

No external credentials are needed. `make seed` creates a clearly labelled synthetic field so the alert → report →
expert workflow can be explored without network access; registering a real field triggers live downloads.

Optional: `PYTHONPATH=backend .venv/bin/python scripts/seed_dev.py --real-demo` adds a field on public sample point S7
fed by live NASA data (fast if `make research-fetch` has populated the raw cache, ~30 min otherwise).

## PostgreSQL

Migrations were verified on PostgreSQL 18.3 (`alembic upgrade head` + `alembic check`, database
`croppulse_migration_check`). Set `CROPPULSE_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/croppulse`.

## Containers (written, NOT verified in this environment — Docker daemon was not running)

```bash
# .env must define POSTGRES_PASSWORD and CROPPULSE_SECRET_KEY
docker compose up --build -d
```

Services: `db` (postgis/postgis:16-3.4, health-checked), `api` (runs migrations then uvicorn, non-root, health check),
`web` (Next.js production server). `docker compose config` validates. Before relying on it: build the images, run
`make test` inside the API image, and smoke-test `/ready`.

## Production-oriented checklist (not done)

- TLS termination (reverse proxy) and HSTS; restrict CORS to the real web origin.
- Managed PostgreSQL with automated backups and PITR; object storage for `data/raw`, `data/processed`, uploads.
- Secrets from a secret manager; rotate `CROPPULSE_SECRET_KEY` (invalidates tokens).
- Scheduler (cron/Kubernetes CronJob) for `scripts/run_ingestion.py` — see OPERATIONS.md.
- httpOnly-cookie auth and CSP (SECURITY_AND_PRIVACY.md).
- Do **not** deploy publicly with real farmer data before the legal review and pilot approvals in PILOT_PROTOCOL.md.

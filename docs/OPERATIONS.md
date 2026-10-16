# Operations

## Scheduled jobs

| Job | Command | Suggested schedule | Notes |
|---|---|---|---|
| Ingest + assess all real fields | `PYTHONPATH=backend .venv/bin/python scripts/run_ingestion.py` | daily 02:00 IST | MODIS changes every 16 days; POWER daily. Weather cells refresh at most every 12 h |
| Re-assess only | `… run_ingestion.py --assess-only` | after config changes | no downloads |
| Deliver notifications | `… run_ingestion.py --deliver-only` | every 15 min | retries failed deliveries (max 3 attempts) |
| Reports | `make evaluate` | per season / on demand | |

Each source job writes an `ingestion_jobs` row (status, counts, warnings, config version) and updates `data_sources`
(status, last success, last error, latest observation end, observed latency). Failed jobs never overwrite data;
previous observations keep their original timestamps and are marked stale by the assessment freshness rules.

## Monitoring

- `/health` (liveness) and `/ready` (DB migrated + config) for orchestrators.
- `/api/v1/admin/metrics` (admin): per-route request counts, 5xx counts, p50/p95 latency (in-process, since start),
  ingestion status counts and success rate, alert status counts, per-source status and latency.
- `/api/v1/sources`: freshness per source — alert operators if `last_success_at` is older than 2 × the source cadence
  (MODIS 32 d, POWER 2 d) or status becomes `unavailable`.
- Structured JSON logs on stdout (redacted); ship to a log store.
- Model monitoring to add: weekly distribution of assessment states and abstention rate per district, valid-pixel
  share, alert volume; compare with the backtest baseline (reports/BASELINE_BACKTEST.md) to detect drift.

Operational target (not yet measured): 99.5 % monthly API availability once a stable deployment exists.

## Backup and restore

- SQLite (dev): `make backup` → `data/backups/croppulse-<timestamp>.db` (online-consistent backup API).
  Restore: stop the API, copy the backup to `data/croppulse.db`, start, check `/ready`.
- PostgreSQL: `pg_dump -Fc croppulse > croppulse.dump`; restore with `pg_restore -d croppulse croppulse.dump`, then
  `alembic current` must equal head. Test restores quarterly.
- `data/raw` (source response cache) is reproducible from the providers but slow to rebuild (MODIS ~45 min/point);
  back it up with the database. Uploads must be backed up (not reproducible).

## Incidents

| Symptom | Likely cause | Action |
|---|---|---|
| MODIS jobs `failed` with HTTP 5xx | ORNL outage | Nothing; data go stale and assessments abstain. Re-run later |
| `SourceSchemaError` | Upstream format/unit change | Stop ingestion for that source, inspect raw response, update adapter + recorded fixtures |
| Sudden rise in `elevated_risk` | Real event, cloud artefact or config change | Check config hash, valid-pixel share, compare with backtest; notify agronomists |
| Login 429s | Brute force or shared NAT | Inspect audit log; adjust limit |
| Suspected data breach | — | Rotate secret key, revoke sessions, preserve audit logs, follow DPDP breach-notification obligations |

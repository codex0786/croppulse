# Roadmap

## Completed in build session 1 (2026-10-15)
Backend foundation, migrations (SQLite + PostgreSQL verified), live MODIS/POWER/land-cover adapters, quality checks,
anomaly and weather science with leakage tests, rule-based risk engine with evidence gate and abstention, alerts,
consent/RBAC/audit, farmer/expert/FPO/regional/research/admin web app, evaluation framework, real-data coverage
report and unlabelled backtest, documentation, Docker/CI files. See `reports/FINAL_REPORT.md`.

## Next priorities (ranked by impact, risk and dependency)

1. **Independent labels via a partner pilot** (PILOT_PROTOCOL.md): stratified expert inspections including non-alerted
   fields. Unblocks every scientific claim. *Dependency: partner FPO/KVK, legal review.*
2. **Higher-resolution vegetation (Sentinel-2 L2A, 10–20 m)** for field-scale attribution, with cloud masking
   (SCL band); keep MODIS for long baselines. *Dependency: Copernicus Data Space access or Microsoft Planetary Computer.*
3. **Earthdata integrations (GPM IMERG Late/Final, SMAP L4)**: obtain credentials, verify formats with recorded
   responses, add rainfall and soil-moisture indicators and their ablations.
4. **Security hardening for a pilot**: httpOnly cookie auth + CSRF, CSP, MFA for experts/admins, deletion job,
   password reset, DPDP legal review, Docker build + CI run.
5. **Reviewed localisation and crop calendar**: Marathi review with agronomists and native speakers; official crop
   calendars → growth-stage aware baselines and messages.

## Decisions for the pilot team (from the real-data backtest)
- Reference pooling: ±1 composite cuts kharif abstention from 71 % to 53 % but mixes phenological stages (reports/BASELINE_BACKTEST.md).
- Whether a rainfall deficit alone should raise `watch` when NDVI is strongly above normal (3 such cases observed).

## Later
- DES statistics import + district boundary (NWIC) import with PostGIS; district-level regional maps.
- Cache-aligned MODIS chunking (per-year chunks) and a shared pixel cache across nearby fields; ORNL batch orders.
- Queue-based workers (RQ/Celery) for concurrent refreshes; Prometheus metrics export.
- SMS/WhatsApp provider abstraction with consent and DLT registration; voice reports.
- Market-price module (isolated) once source terms are verified.
- Yield models only after labels per VALIDATION_PROTOCOL.md §8.

# Limitations

## Scientific
- **No validation.** No independent outcome labels exist; precision, recall, lead time and calibration are unknown.
  The core research question is unresolved. `screening-rules@0.1.0` is a research artefact, not an approved model.
- Thresholds (robust z ≤ −1.5, percentile ≤ 10, 2 consecutive composites, rain percentile ≤ 20, dry spell ≥ 14 d,
  Tmax ≥ 40 °C on ≥ 3 of 14 d) are untested defaults.
- Calendar-date baselines ignore crop stage, sowing shifts and crop rotation between years.
- 250 m MODIS pixels exceed most smallholder fields; land-cover check is a generic cropland class at 500 m.
- Heavy kharif cloud reduces usable composites; abstention will be common in July–August.
- POWER weather is coarse reanalysis; IMERG and soil moisture are not integrated.
- Yield prediction is disabled; no crop statistics have been imported.
- Research backtest uses public sample points with unknown crops, not farmer fields.

## Data/integration
- GPM IMERG, SMAP: awaiting Earthdata credentials (adapter contract only).
- IMD: manual advisory entry only. DES statistics, district boundaries, market prices: not imported.
- ORNL TESViS throughput (10–45 s/request) makes first-time field ingestion take ~30 min; no batch ordering.
- Year-end composite period truncation (31 Dec) is an assumption to verify.

## Product
- Hindi/Marathi translations are unreviewed drafts and cover farmer-facing strings only; expert/admin views are English.
- No voice, SMS or WhatsApp channels; email delivery is a development outbox only.
- No growth-stage names (crop calendar unreviewed).
- Offline support: app shell + cached GETs + queued text reports; photos are not queued offline.
- Organisation joining uses a raw organisation id ("code"); no invitation flow.

## Engineering / operations
- Docker images and the compose stack were not built (Docker daemon unavailable); CI workflow not executed.
- The web UI was verified by build, type-check, lint and i18n tests; browser-based end-to-end verification of the
  running app could not be completed in this session because the desktop preview servers did not start (see final report).
- Single-instance assumptions: in-process rate limiter, metrics and background tasks.
- No PostGIS; no spatial queries.
- Security gaps listed in SECURITY_AND_PRIVACY.md (token storage, CSP, MFA, deletion job, legal review).

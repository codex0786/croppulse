# Data sources

The machine-readable registry is `config/sources.yaml`; live operational status (last success, observed latency,
last error) is served at `GET /api/v1/sources` and shown on the Research page. This document adds context.

## Status summary (as verified on 2026-10-15)

| Source | Status | Evidence |
|---|---|---|
| MODIS MOD13Q1 C6.1 NDVI/EVI via ORNL TESViS | **Live integration tested** | `make test-live` passed; real responses recorded in `backend/tests/fixtures/recorded/` |
| MODIS MCD12Q1 C6.1 land cover via ORNL TESViS | **Live integration tested** | `make test-live`; 9 candidate points classified live |
| NASA POWER daily (AG community) | **Live integration tested** | `make test-live`; 1991–2026 series downloaded for research cells |
| GPM IMERG (precipitation) | **Awaiting credentials** | adapter contract only; returns `not_configured` |
| SMAP L4 (soil moisture) | **Awaiting credentials** | adapter contract only; returns `not_configured` |
| IMD warnings / agromet advisories | **Manual official-source workflow** | admin enters advisory text + official URL; no scraping |
| DES district crop statistics | **Importer implemented, no data imported** | `croppulse.sources.crop_stats`; tested only with unit-level checks |
| District boundaries (NWIC) | **Not imported** | licence/vintage to verify |
| Agmarknet / e-NAM | **Unavailable — disabled module** | feature flag off |
| Synthetic fixtures | **Simulated test fixture only** | `croppulse.devtools.synthetic`; every payload carries `_synthetic: true` |

## MODIS MOD13Q1 (vegetation)

- **Access**: `GET https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset?latitude&longitude&band&startDate&endDate&kmAboveBelow&kmLeftRight`.
  At most 10 composites per request; exceeding it returns a JSON *string* error (handled as a schema error).
- **Bands used**: `250m_16_days_NDVI`, `250m_16_days_EVI` (optional, `fetch_evi`), `250m_16_days_pixel_reliability`.
- **Decoding**: value × 0.0001; fill −3000 and values outside −2000..10000 become `NULL` (never 0).
  Reliability 0 (good) and 1 (marginal) accepted by default; 2 (snow/ice), 3 (cloudy), −1 (fill) rejected.
- **Field aggregation**: pixels whose centre (inverse sinusoidal projection, sphere R = 6 371 007.181 m) lies inside
  the field polygon; otherwise the pixel containing the centroid, flagged `pixel_containing_centroid`. Composite
  accepted only if ≥ 50 % of selected pixels are usable. Method string stored on every observation.
- **Time**: `calendar_date` = composite start; period end = start + 15 days, truncated at 31 Dec (assumption:
  composites restart at DOY 001 each year — verify against the MOD13 user guide before relying on year-end composites).
  `proc_date` → `published_at`.
- **Latency observed**: on 2026-10-15 the latest composite started 2026-09-14 (ended 09-29) — 16 days after period end.
- **Throughput observed**: 10–45 s per request (NDVI slower than reliability). A full 17-year field history ≈ 40 chunks × 2 bands.
- **Cache/reprocessing**: chunks older than ~400 days are served from the raw cache; recent chunks are always re-fetched.
  Changed values create a new observation revision (old rows kept, `is_current=false`).
- **Citation**: Didan, K. (2021). MOD13Q1 MODIS/Terra Vegetation Indices 16-Day L3 Global 250m SIN Grid V061.
  NASA EOSDIS LP DAAC. doi:10.5067/MODIS/MOD13Q1.061. Subsets: ORNL DAAC MODIS and VIIRS Land Products Global Subsetting and Visualization Tool.

## MODIS MCD12Q1 (land cover)

- LC_Type1 (IGBP) of the 500 m pixel at the field centroid, latest year (2024 at verification). Classes 12 (Croplands)
  and 14 (Cropland/Natural Vegetation Mosaic) count as cropland. Used only as a representativeness check.
- Observed: the initial probe point (19.88 N, 75.34 E) is class 13 (Urban); Latur and Parbhani city points also 13.

## NASA POWER (weather)

- **Access**: `GET https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR,T2M_MAX,T2M_MIN,T2M,RH2M,ALLSKY_SFC_SW_DWN&community=AG&latitude&longitude&start&end&format=JSON`.
- Requested for the MERRA-2 grid-cell centre (0.5° × 0.625°), not the field.
- Units are read from each response and compared with expected values (`mm/day`, `C`, `%`, `MJ/m^2/day`); a change raises
  a schema error. Fill value (−999) → `NaN`. Time standard LST.
- Observed: a 1991–2026 request returns in ~3 s (1.3 MB); the last ~3 days are fill (latency).
- PRECTOTCORR is bias-corrected MERRA-2 precipitation — model reanalysis, not gauge or IMERG.
- **Acknowledgement**: "These data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded
  through the NASA Earth Science/Applied Science Program."

## GPM IMERG and SMAP (not configured)

Both require NASA Earthdata Login. Without credentials the response format could not be verified, so no parser was
written against a guessed format. `croppulse/sources/earthdata.py` documents the steps to complete the integration.

## IMD

No supported public API was established. CropPulse never scrapes IMD and never generates forecasts. An admin enters an
advisory (title, text, districts, validity, **mandatory https source URL**); farmers see it with the issuing organisation,
dates and a link to the original.

## DES crop statistics / data.gov.in

Not downloadable programmatically in this session. The importer requires explicit unit columns, converts `'000 ha` and
`'000 tonnes`, computes yield only for mass units (never for bales/nuts), flags duplicate keys (revisions) and records the
file checksum. District renames (e.g. Aurangabad → Chhatrapati Sambhajinagar, Osmanabad → Dharashiv) must go through a
reviewed crosswalk. **A district statistic is never used as a field-level label.**

## Historical research datasets (ICRISAT / TCI)

Not integrated. Before use: check licence, district-boundary vintage (1966 boundaries in the ICRISAT district-level
database differ from today's), crop/season definitions, and overlap with DES statistics.

# Data coverage and quality report (REAL DATA)

Generated 2026-10-15 16:24 UTC by `make evaluate` · code b919926 · science config 5ed0ed98d0d9
Inputs: `reports/artifacts/research_data_manifest.json` (file checksums, request parameters, retrieval times).

**Scope.** 4 public sample points in Marathwada, Maharashtra, each a 750 m × 750 m footprint whose
containing MCD12Q1 (2024) pixel is classified Croplands. They are *not* farmer fields and carry no crop-type
information. Sources: MODIS MOD13Q1 C6.1 NDVI + pixel reliability via ORNL DAAC TESViS; NASA POWER daily (MERRA-2 based)
for the 0.5° × 0.625° grid cell containing each point.

## Per-point summary

| point | composites | first | latest_period_end | accepted_share | kharif_jun_sep_accepted_share | rejected_no_quality_pixels | rejected_low_valid_fraction | pixels_selected | land_cover_2024 | power_last_valid | power_missing_share_1991_on | median_publication_lag_days |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | 569 | 2002-01-01 | 2026-09-29 | 0.842 | 0.548 | 71 | 19 | 13 | 12 | 2026-10-12 | 0.0002 | 2668.0 |
| S3 | 569 | 2002-01-01 | 2026-09-29 | 0.842 | 0.548 | 75 | 15 | 13 | 12 | 2026-10-12 | 0.0002 | 2668.0 |
| S5 | 569 | 2002-01-01 | 2026-09-29 | 0.824 | 0.497 | 79 | 21 | 13 | 12 | 2026-10-12 | 0.0002 | 2668.0 |
| S7 | 569 | 2002-01-01 | 2026-09-29 | 0.838 | 0.538 | 81 | 11 | 14 | 12 | 2026-10-12 | 0.0002 | 2668.0 |

Column notes: *accepted_share* = composites with ≥ 50 % of selected pixels at reliability 0/1 and a valid NDVI;
*median_publication_lag_days* = provider `proc_date` minus composite end (reprocessed archives inflate this for old years);
*power_missing_share_1991_on* includes the trailing days not yet published.

## Share of composites usable, by calendar month of composite start

| month | S1 | S3 | S5 | S7 |
|---|---|---|---|---|
| Jan | 1.0 | 1.0 | 1.0 | 1.0 |
| Feb | 1.0 | 1.0 | 1.0 | 1.0 |
| Mar | 1.0 | 1.0 | 1.0 | 1.0 |
| Apr | 1.0 | 1.0 | 1.0 | 1.0 |
| May | 1.0 | 1.0 | 1.0 | 1.0 |
| Jun | 0.58 | 0.62 | 0.48 | 0.58 |
| Jul | 0.22 | 0.24 | 0.18 | 0.22 |
| Aug | 0.48 | 0.5 | 0.46 | 0.44 |
| Sep | 0.918 | 0.837 | 0.878 | 0.918 |
| Oct | 1.0 | 1.0 | 1.0 | 1.0 |
| Nov | 1.0 | 1.0 | 1.0 | 1.0 |
| Dec | 1.0 | 1.0 | 1.0 | 1.0 |

## Findings

- Monsoon cloud is the dominant data gap: usable-composite share in June–September is lower than in the dry season
  (table above). Kharif-season screening therefore often has to abstain or rely on weather indicators.
- MODIS latency: the latest composite available ends 2026-09-29; with typical 2–4 week latency the vegetation
  evidence is always weeks old. CropPulse marks it *stale* after 48 days.
- NASA POWER has essentially complete daily coverage since 1991 apart from the most recent days, which arrive with a lag.
- Spatial support: each footprint selects only a handful of 250 m pixels; ORNL subsets were observed to contain repeated values
  in adjacent cells, so pixel counts overstate independent information.

## What this report does not show

It does not show that any indicator predicts crop stress or yield loss. No independent outcome labels were available.

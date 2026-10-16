# Baseline screening backtest — descriptive, UNLABELLED (REAL DATA)

Generated 2026-10-15 16:24 UTC · code b919926 · science config 5ed0ed98d0d9
Stored predictions: `reports/artifacts/backtest_predictions.csv` (96 rows; every number below is recomputable from it).

## Design

- Units: research sample points (see DATA_COVERAGE_REPORT.md); crop unknown (context "unknown kharif crop").
- As-of dates: 15 Aug, 15 Sep, 15 Oct of each year in [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025].
- Availability simulation: a composite is usable from period end + 21 days; weather from day + 3.
  Reference statistics use only years strictly before the target year (leakage tests: `tests/scientific`).
- Method: `screening-rules@0.1.0` with the unvalidated thresholds in `config/science.yaml`.

## Results (descriptive only)

| unit | assessments | abstained | watch_or_higher | elevated | median_veg_age_days | abstention_rate | watch_rate |
|---|---|---|---|---|---|---|---|
| S1 | 24 | 17 | 4 | 0 | 50.5 | 0.708 | 0.167 |
| S3 | 24 | 15 | 4 | 0 | 50.5 | 0.625 | 0.167 |
| S5 | 24 | 20 | 4 | 0 | 51.0 | 0.833 | 0.167 |
| S7 | 24 | 16 | 3 | 0 | 50.5 | 0.667 | 0.125 |

State counts per unit:

| unit | insufficient_evidence | normal_for_reference_period | watch |
|---|---|---|---|
| S1 | 17 | 3 | 4 |
| S3 | 15 | 5 | 4 |
| S5 | 20 | 0 | 4 |
| S7 | 16 | 5 | 3 |

| Summary | Value |
|---|---|
| assessments | 96 |
| units | 4 |
| abstention_rate | 0.708 |
| watch_or_higher_rate | 0.156 |
| elevated_rate | 0.0 |
| z_vs_robust_z_flag_agreement | 1.0 |
| spearman_ndvi_robust_z_vs_rain30_percentile | 0.159 |
| labelled_metrics | not computable: no independent event labels |

## States by as-of date

| as_of_md | insufficient_evidence | normal_for_reference_period | watch |
|---|---|---|---|
| 08-15 | 23 | 0 | 9 |
| 09-15 | 30 | 0 | 2 |
| 10-15 | 15 | 13 | 4 |

## Label-free sensitivity: reference pooling

Pooling ±1 adjacent 16-day composite enlarges the reference sample under monsoon cloud at the cost of mixing
phenological stages. No outcome labels were used; this changes data sufficiency, not measured accuracy.

| pool_adjacent_composites | abstention_rate | median_reference_n | watch_or_higher_rate | elevated_rate |
|---|---|---|---|---|
| 0.0 | 0.708 | 9.0 | 0.156 | 0.0 |
| 1.0 | 0.531 | 14.0 | 0.156 | 0.0 |

## Observed behaviour worth reviewing

- 3 assessment(s) reached `watch` from weather indicators while NDVI was well **above** the reference
  (robust z > 1.5). The rules let a rainfall deficit raise `watch` regardless of strongly positive vegetation evidence;
  agronomists should decide whether that is desirable (it may be appropriate early in a dry spell, or a false alarm).
- Rainfall-deficit indicators fired at all four grid cells in 2018. Whether this matches documented events must be
  checked against official sources before any claim is made.

## Interpretation and limits

- **These are not accuracy metrics.** Precision, recall, PR-AUC, lead time and calibration require independent,
  dated stress events (expert-verified outcomes or documented events) that were not available. The scientific question
  — does the multi-source screen beat a seasonal baseline? — remains **unresolved**.
- The watch/elevated rates measure *alert burden* under the current thresholds; a high burden with no labels
  could equally mean real stress, cloud artefacts, or crop-calendar shifts between years.
- Agreement between standard and robust z flags indicates how sensitive flags are to outliers in the reference years.
- The rank correlation between NDVI anomaly and 30-day rainfall percentile is an internal-consistency check, not validation:
  both could be driven by the same season and neither is ground truth.
- Next step: collect verified outcomes through the expert workflow (docs/PILOT_PROTOCOL.md) and re-run with labels.

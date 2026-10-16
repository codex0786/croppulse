# Validation protocol

Code: `backend/croppulse/research/evaluation.py`, `backtest.py`, `pipeline.py`; tests: `backend/tests/scientific/`.

## 1. Labels (what counts as ground truth)

| Label source | Use | Notes |
|---|---|---|
| `verified_outcomes` (expert-verified, method recorded) | Primary label | Only agronomists can create; identity + time + evidence stored |
| Documented external events (e.g. official drought declarations, published crop-loss surveys) | Event-level evaluation | Must be dated, sourced, and not used to tune thresholds |
| Farmer reports | **Not labels** | Unverified; may trigger review only |
| District yield statistics | Regional yield models only | Never field-level labels; revisions tracked |
| Detector output | **Never** | Circular |

## 2. Splits

1. **Temporal hold-out**: train/tune on seasons < cutoff, report on ≥ cutoff (`temporal_holdout`).
2. **Rolling origin**: repeated origins, fixed horizon (`rolling_origin`).
3. **Geographic hold-out**: whole districts/clusters held out (`group_holdout`, `leave_one_group_out`).
4. **Crop/season strata** reported separately when n allows.
5. **Independent events**: a reserved set never used for thresholds.

Random row splits are not used. `check_split` fails on row overlap, non-chronological temporal splits, groups on both
sides and duplicate observation keys; `check_feature_availability` fails when any feature timestamp is after the
prediction time.

## 3. Leakage controls (automated tests)

- Reference years strictly before the target year; only composites with `available_at ≤ as_of` (`test_leakage.py`).
- Weather features invariant to rows after `as_of`.
- Backtest predictions identical with or without later data; simulated availability (period end + 21 d) excludes
  composites not yet published.
- Normalisation statistics are per-target, from permitted history only (no full-dataset normalisation).
- Synthetic rows refused by real-data reports (`assert_real_data`).
- Metrics recomputable from stored predictions tables (`metrics_from_table`).
- Hyper-parameters/thresholds: tune on training periods only; the final test period is evaluated once and reported.

## 4. Metrics

Event/alert: precision, recall, PR-AUC (average precision), false alerts per unit per season, event detection rate,
median lead time (only with independently dated events), alert burden and abstention rate.
Probabilistic models (future): Brier, log loss, reliability table. Yield (future): MAE, RMSE, bias, R², skill vs
baseline, prediction-interval coverage/width. Uncertainty: block bootstrap over districts or seasons
(`block_bootstrap_ci`), never i.i.d. rows. Accuracy alone is never reported.

## 5. Ablation

Historical base rate → vegetation-only → weather-only → vegetation + weather → + soil moisture (when configured) →
+ crop/season context. Only features present in the evaluated data are included.

## 6. Current status (2026-10-15)

| Item | Status |
|---|---|
| Real-data coverage report | Generated (`reports/DATA_COVERAGE_REPORT.md`) |
| Real-data descriptive backtest (alert burden, abstention) | Generated, **no labels** (`reports/BASELINE_BACKTEST.md`) |
| Labelled temporal/geographic evaluation | **Not possible yet — no labels** |
| Evaluation code mechanics | Verified on synthetic data (`reports/SYNTHETIC_EVALUATION_MECHANICS.md`) — not a result |
| Calibration | Not applicable (no probabilistic model) |

## 7. Approval gate for operational use

A model version may move from `research` to `approved` only when: (1) a pre-registered evaluation on held-out
seasons **and** held-out districts with independent labels beats the seasonal baseline on PR-AUC with block-bootstrap
CIs excluding no-improvement; (2) false alerts per field-season are acceptable to partner agronomists; (3) the model card
is updated; (4) a named approver records approval (`model_versions.approved_by/at`); (5) a rollback version is set.
Until then `risk.model_validated=false` and elevated cases go to experts.

## 8. Yield prediction enablement criteria

Crop-specific, consistently defined yield labels at the unit of prediction (district or below) for ≥ 10 seasons,
out-of-time and geographic validation, skill over a trend/persistence baseline, calibrated intervals.

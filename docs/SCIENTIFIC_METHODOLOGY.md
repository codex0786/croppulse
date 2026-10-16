# Scientific methodology

## Research questions

1. **Science**: can satellite vegetation indicators, weather, soil moisture and crop-season context identify crop
   stress earlier or more reliably than a historical seasonal baseline, with calibrated, explainable estimates?
2. **Product**: what is happening in or around a field, how unusual is it, what supports that, what next, and how
   confident should the user be?

**Status: question 1 is unresolved.** The data pipeline and evaluation code exist; independent outcome labels do not.

## Observation → inference → recommendation

| Layer | Stored in | Example |
|---|---|---|
| Observation | `observations`, POWER Parquet | NDVI 0.42 for 14–29 Sep 2026, 9/9 pixels good |
| Inference | `risk_assessments` | state `watch`, robust z −1.9, 4th percentile vs 2011–2025 |
| Recommendation | `config/guidance.yaml` (approved process guidance), expert `case_events` | "Check the field; this does not establish its cause" |

## Task A — vegetation anomaly

For target composite *x* (field mean NDVI) with composite index *k* in year *Y*:

- reference sample: one value per year *y* ∈ [Y − N, Y − 1] (N = 15) from composites with index within ±pool of *k*
  (pool = 0), quality-accepted, `available_at ≤ as_of`;
- `Z = (x − μ_ref)/σ_ref` (σ with ddof = 1); robust `Z_r = (x − median_ref)/(1.4826·MAD_ref)`;
- mid-rank percentile of *x* in the reference;
- status `insufficient_reference` if n < 8 (or < 2), `zero_variance` if σ or scaled MAD < 0.005;
- 5–95 % bootstrap interval of `Z_r` over resampled reference years (sensitivity, not probability);
- persistence: count of consecutive most-recent usable composites with `Z_r ≤ −1.5` **and** percentile ≤ 10;
  gaps > 32 days break the run (multiple-comparison control heuristic).

Known confounders (always shown to users when greenness is low): harvest timing, late sowing, crop change between
years, irrigation, flooding, residual cloud/aerosol, mixed pixels. Calendar alignment uses the calendar date, not the
crop stage, because historical sowing dates are unknown.

## Task B — weather indicators

From NASA POWER with rows after `as_of` removed and the window ending at the last valid day:
rain totals (7/30/60/90 d) with coverage ≥ 90 %; percentile and deficit vs the same calendar window in the 30 preceding
years (≥ 20 needed; deficits suppressed in climatologically dry windows); current dry spell (days < 2.5 mm, IMD rainy-day
convention; truncated at missing days); heat days (Tmax ≥ 40 °C in 14 d); Tmax anomaly. Thresholds are configurable and
**unvalidated**. A rainfall deficit is never equated with crop loss, nor low NDVI with drought.

## Task C — multisource screening (current model)

`screening-rules@0.1.0` (risk/engine.py):

1. Evidence gate: crop/season known (blocking); vegetation fresh (≤ 48 d after composite end), quality, reference
   sufficiency, cropland pixel, field resolution; weather fresh (≤ 10 d); ≥ 2 independent current sources; model validated.
2. State: insufficient → `insufficient_evidence`; vegetation unreliable → weather signal gives at most `watch`,
   otherwise `insufficient_evidence` (missing data never reads as healthy); persistent low NDVI + weather signal →
   `elevated_risk`; any single signal → `watch`; else `normal_for_reference_period`. Open farmer report upgrades
   watch/elevated to `expert_review_recommended`; a recent expert verification sets `verified_stress`.
3. Escalation to experts for elevated states (model unvalidated).
4. No probability is produced.

Transparent statistical (logistic) and tree models are deferred until labels exist; the evaluation code already
supports their comparison (ablation: base rate, vegetation-only, weather-only, combined).

## Task D — yield prediction

**Disabled.** No reliable, temporally compatible yield labels have been imported. `GET /api/v1/yield` returns 501 with
the reason. Requirements to enable are listed in VALIDATION_PROTOCOL.md.

## Task E — events

Distinguished in data and UI: anomaly (derived) ≠ screening state (estimated) ≠ farmer report (farmer_reported) ≠
verified finding (expert_verified). Only `verified_outcomes` (and future documented external events) are labels.

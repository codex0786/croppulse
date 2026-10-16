"""Generate scientific reports under reports/.

1. REAL DATA (if `make research-fetch` has been run):
   - reports/DATA_COVERAGE_REPORT.md   coverage / quality / latency of MODIS + POWER at sample points
   - reports/BASELINE_BACKTEST.md      UNLABELLED descriptive backtest of the screening rules
   - reports/artifacts/backtest_predictions.csv  (stored predictions; metrics recomputable)
2. SYNTHETIC MECHANICS CHECK (always):
   - reports/SYNTHETIC_EVALUATION_MECHANICS.md  exercises splits, metrics, ablation and
     calibration code on labelled synthetic data. NOT a scientific result.
Each run is also registered as an EvaluationRun (is_synthetic flagged) in the app database.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from croppulse.config import REPO_ROOT, config_version, get_settings, science_config
from croppulse.db import get_sessionmaker
from croppulse.models import EvaluationRun
from croppulse.research.evaluation import (
    brier,
    check_split,
    group_holdout,
    log_loss,
    metrics_from_table,
    pr_auc,
    precision_recall,
    reliability_table,
    temporal_holdout,
)
from croppulse.research.pipeline import ART, coverage_tables, descriptive_backtest
from croppulse.research.reports import code_version

REPORTS = REPO_ROOT / "reports"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.values) + " |")
    return "\n".join(lines)


def register(regime: str, synthetic: bool, metrics: dict, report: str, notes: str) -> None:
    s = get_sessionmaker()()
    try:
        s.add(
            EvaluationRun(
                model_name="screening-rules@0.1.0",
                regime=regime,
                is_synthetic=synthetic,
                metrics=json.loads(json.dumps(metrics, default=str)),
                report_path=report,
                notes=notes,
            )
        )
        s.commit()
    except Exception as exc:  # DB not migrated: the report files are still written
        print(f"(evaluation run not registered in DB: {exc.__class__.__name__})")
    finally:
        s.close()


def real_data_reports() -> bool:
    man_path = ART / "research_data_manifest.json"
    if not man_path.exists():
        print("No research data manifest — run `make research-fetch` first. Skipping real-data reports.")
        return False
    man = json.loads(man_path.read_text())
    man["points"] = {k: v for k, v in man["points"].items() if (get_settings().data_dir / v["modis_file"]).exists()}
    if not man["points"]:
        print("Research manifest lists no available files. Skipping real-data reports.")
        return False
    cov = coverage_tables(man)
    pp = cov["per_point"]
    months = cov["accepted_by_month"]
    months.index = [date(2000, m, 1).strftime("%b") for m in months.index]
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    (REPORTS / "DATA_COVERAGE_REPORT.md").write_text(
        f"""# Data coverage and quality report (REAL DATA)

Generated {now} by `make evaluate` · code {code_version(REPO_ROOT)} · science config {config_version(get_settings().science_config_path)}
Inputs: `reports/artifacts/research_data_manifest.json` (file checksums, request parameters, retrieval times).

**Scope.** {len(pp)} public sample points in Marathwada, Maharashtra, each a 750 m × 750 m footprint whose
containing MCD12Q1 (2024) pixel is classified Croplands. They are *not* farmer fields and carry no crop-type
information. Sources: MODIS MOD13Q1 C6.1 NDVI + pixel reliability via ORNL DAAC TESViS; NASA POWER daily (MERRA-2 based)
for the 0.5° × 0.625° grid cell containing each point.

## Per-point summary

{md_table(pp)}

Column notes: *accepted_share* = composites with ≥ {int(100 * 0.5)} % of selected pixels at reliability 0/1 and a valid NDVI;
*median_publication_lag_days* = provider `proc_date` minus composite end (reprocessed archives inflate this for old years);
*power_missing_share_1991_on* includes the trailing days not yet published.

## Share of composites usable, by calendar month of composite start

{md_table(months.reset_index().rename(columns={"index": "month"}))}

## Findings

- Monsoon cloud is the dominant data gap: usable-composite share in June–September is lower than in the dry season
  (table above). Kharif-season screening therefore often has to abstain or rely on weather indicators.
- MODIS latency: the latest composite available ends {pp["latest_period_end"].max()}; with typical 2–4 week latency the vegetation
  evidence is always weeks old. CropPulse marks it *stale* after {48} days.
- NASA POWER has essentially complete daily coverage since 1991 apart from the most recent days, which arrive with a lag.
- Spatial support: each footprint selects only a handful of 250 m pixels; ORNL subsets were observed to contain repeated values
  in adjacent cells, so pixel counts overstate independent information.

## What this report does not show

It does not show that any indicator predicts crop stress or yield loss. No independent outcome labels were available.
"""
    )
    bt = descriptive_backtest(man)
    cfg_pool0 = science_config()["vegetation"]["pool_adjacent_composites"]
    bt.to_csv(ART / "backtest_predictions.csv", index=False)
    states = bt.groupby("unit")["state"].value_counts().unstack(fill_value=0)
    burden = bt.groupby("unit").agg(
        assessments=("state", "size"),
        abstained=("state", lambda s: int((s == "insufficient_evidence").sum())),
        watch_or_higher=("flag_watch_or_higher", "sum"),
        elevated=("flag_elevated", "sum"),
        median_veg_age_days=("veg_age_days", "median"),
    )
    burden["abstention_rate"] = (burden["abstained"] / burden["assessments"]).round(3)
    burden["watch_rate"] = (burden["watch_or_higher"] / burden["assessments"]).round(3)
    both = bt.dropna(subset=["ndvi_z", "ndvi_robust_z"])
    agree = float(((both["ndvi_z"] <= -1.5) == (both["ndvi_robust_z"] <= -1.5)).mean()) if len(both) else float("nan")
    corr_df = bt.dropna(subset=["ndvi_robust_z", "rain30_percentile"])
    spearman = float(corr_df["ndvi_robust_z"].rank().corr(corr_df["rain30_percentile"].rank())) if len(corr_df) > 5 else float("nan")
    metrics = {
        "assessments": int(len(bt)),
        "units": int(bt["unit"].nunique()),
        "abstention_rate": round(float((bt["state"] == "insufficient_evidence").mean()), 3),
        "watch_or_higher_rate": round(float(bt["flag_watch_or_higher"].mean()), 3),
        "elevated_rate": round(float(bt["flag_elevated"].mean()), 3),
        "z_vs_robust_z_flag_agreement": round(agree, 3),
        "spearman_ndvi_robust_z_vs_rain30_percentile": round(spearman, 3),
        "labelled_metrics": "not computable: no independent event labels",
    }
    # Label-free sensitivity: how reference pooling changes data sufficiency (no outcome labels are used).
    sens_rows = []
    for pool in (0, 1):
        cfg = copy.deepcopy(science_config())
        cfg["vegetation"]["pool_adjacent_composites"] = pool
        b2 = bt if pool == cfg_pool0 else descriptive_backtest(man, cfg)
        sens_rows.append(
            {
                "pool_adjacent_composites": pool,
                "abstention_rate": round(float((b2["state"] == "insufficient_evidence").mean()), 3),
                "median_reference_n": float(b2["ndvi_reference_n"].median()),
                "watch_or_higher_rate": round(float(b2["flag_watch_or_higher"].mean()), 3),
                "elevated_rate": round(float(b2["flag_elevated"].mean()), 3),
            }
        )
    sens = pd.DataFrame(sens_rows)
    by_date = bt.assign(as_of_md=bt["as_of"].astype(str).str[5:]).groupby("as_of_md")["state"].value_counts().unstack(fill_value=0)
    weather_only = bt[(bt["flag_watch_or_higher"]) & (bt["ndvi_robust_z"] > 1.5)]
    (REPORTS / "BASELINE_BACKTEST.md").write_text(
        f"""# Baseline screening backtest — descriptive, UNLABELLED (REAL DATA)

Generated {now} · code {code_version(REPO_ROOT)} · science config {config_version(get_settings().science_config_path)}
Stored predictions: `reports/artifacts/backtest_predictions.csv` ({len(bt)} rows; every number below is recomputable from it).

## Design

- Units: research sample points (see DATA_COVERAGE_REPORT.md); crop unknown (context "unknown kharif crop").
- As-of dates: 15 Aug, 15 Sep, 15 Oct of each year in {sorted(set(pd.to_datetime(bt["as_of"]).dt.year))}.
- Availability simulation: a composite is usable from period end + 21 days; weather from day + 3.
  Reference statistics use only years strictly before the target year (leakage tests: `tests/scientific`).
- Method: `screening-rules@0.1.0` with the unvalidated thresholds in `config/science.yaml`.

## Results (descriptive only)

{md_table(burden.reset_index())}

State counts per unit:

{md_table(states.reset_index())}

| Summary | Value |
|---|---|
"""
        + "\n".join(f"| {k} | {v} |" for k, v in metrics.items())
        + """

## States by as-of date

"""
        + md_table(by_date.reset_index())
        + """

## Label-free sensitivity: reference pooling

Pooling ±1 adjacent 16-day composite enlarges the reference sample under monsoon cloud at the cost of mixing
phenological stages. No outcome labels were used; this changes data sufficiency, not measured accuracy.

"""
        + md_table(sens)
        + """

## Observed behaviour worth reviewing

- """
        + str(len(weather_only))
        + """ assessment(s) reached `watch` from weather indicators while NDVI was well **above** the reference
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
"""
    )
    register(
        "descriptive_backtest_unlabelled",
        False,
        metrics,
        "reports/BASELINE_BACKTEST.md",
        "Real MODIS/POWER data at public sample points; no labels, descriptive only.",
    )
    register("data_coverage", False, {"points": int(len(pp))}, "reports/DATA_COVERAGE_REPORT.md", "Real data coverage and quality.")
    print("real-data reports written")
    return True


def synthetic_mechanics() -> None:
    """Exercise the evaluation code end-to-end on LABELLED SYNTHETIC data."""
    rng = np.random.default_rng(42)
    rows = []
    for district in ["D1", "D2", "D3", "D4", "D5", "D6"]:
        for year in range(2014, 2026):
            for unit in range(8):
                stress = rng.random() < 0.15
                veg = rng.normal(-1.8 if stress else 0.0, 1.0)
                rain = rng.normal(-1.0 if stress else 0.0, 1.0)
                rows.append(
                    {"district": district, "year": year, "unit": f"{district}-{unit}", "label": int(stress), "veg_z": veg, "rain_z": rain, "is_synthetic": True}
                )
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["year"].astype(str) + "-09-15")

    def logistic(x: np.ndarray) -> np.ndarray:
        return 1 / (1 + np.exp(-x))

    def fit_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> np.ndarray:
        # Small, transparent logistic regression fitted by Newton's method (no sklearn dependency).
        X = np.c_[np.ones(len(train)), train[cols].to_numpy()]
        y = train["label"].to_numpy()
        w = np.zeros(X.shape[1])
        for _ in range(25):
            p = logistic(X @ w)
            H = X.T @ (X * (p * (1 - p))[:, None]) + 1e-6 * np.eye(X.shape[1])
            w -= np.linalg.solve(H, X.T @ (p - y))
        return logistic(np.c_[np.ones(len(test)), test[cols].to_numpy()] @ w)

    sp = temporal_holdout(df, "t", date(2022, 1, 1))
    gp = group_holdout(df[df["year"] < 2022], "district", ["D6"])
    leak_t = check_split(df, sp, time_col="t")
    leak_g = check_split(df[df["year"] < 2022].reset_index(drop=True), gp, group_col="district")
    train, test = df.iloc[sp.train_index], df.iloc[sp.test_index].copy()
    base_rate = train["label"].mean()
    ablation = {}
    for name, cols in {
        "historical_base_rate": [],
        "vegetation_only": ["veg_z"],
        "weather_only": ["rain_z"],
        "vegetation_plus_weather": ["veg_z", "rain_z"],
    }.items():
        prob = np.full(len(test), base_rate) if not cols else fit_predict(train, test, cols)
        test[f"p_{name}"] = prob
        ablation[name] = {
            "pr_auc": round(pr_auc(test["label"], prob) or float("nan"), 3),
            "brier": round(brier(test["label"], prob), 4),
            "log_loss": round(log_loss(test["label"], prob), 4),
        }
    test["flag"] = (test["p_vegetation_plus_weather"] >= 0.5).astype(int)
    test["score"] = test["p_vegetation_plus_weather"]
    pred_path = ART / "SYNTHETIC_mechanics_predictions.csv"
    test.to_csv(pred_path, index=False)
    recomputed = metrics_from_table(pd.read_csv(pred_path), block_col="district")
    rel = reliability_table(test["label"], test["p_vegetation_plus_weather"], bins=5)
    metrics = {
        "ablation": ablation,
        "threshold_0.5": precision_recall(test["label"], test["flag"]),
        "recomputed_from_table": recomputed,
        "reliability": rel,
        "leakage_temporal_ok": leak_t.ok,
        "leakage_geographic_ok": leak_g.ok,
    }
    (REPORTS / "SYNTHETIC_EVALUATION_MECHANICS.md").write_text(
        f"""# SYNTHETIC evaluation mechanics check — NOT A SCIENTIFIC RESULT

Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. Every row is synthetic (`is_synthetic=True`): labels and features were
generated by `scripts/run_evaluation.py` with a known effect size. This report only demonstrates that the evaluation
pipeline (temporal split, geographic hold-out, leakage checks, ablation, PR-AUC, Brier, log loss, reliability table,
block bootstrap, recomputation from a stored predictions table) runs correctly. The numbers say nothing about real crops.

- Temporal hold-out: train < 2022, test ≥ 2022 · leakage check passed: {leak_t.ok}
- Geographic hold-out (D6 held out, pre-2022): leakage check passed: {leak_g.ok}

## Ablation (synthetic)

{md_table(pd.DataFrame(ablation).T.reset_index().rename(columns={"index": "model"}))}

## Recomputed from stored predictions (`reports/artifacts/SYNTHETIC_mechanics_predictions.csv`)

```json
{json.dumps(recomputed, indent=2, default=str)}
```
"""
    )
    register("synthetic_mechanics_check", True, metrics, "reports/SYNTHETIC_EVALUATION_MECHANICS.md", "SYNTHETIC data — exercises evaluation code only.")
    print("synthetic mechanics report written")


if __name__ == "__main__":
    REPORTS.mkdir(exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    real_data_reports()
    synthetic_mechanics()

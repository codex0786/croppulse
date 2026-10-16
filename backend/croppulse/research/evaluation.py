"""Evaluation framework: leakage-safe splits, event metrics, calibration, block bootstrap.

Design rules (docs/VALIDATION_PROTOCOL.md):
  * Labels must be INDEPENDENT of the detector (expert-verified outcomes or documented
    external events) — never the detector's own output.
  * Splits are by time and/or geography; never random rows.
  * Every metric is recomputable from a stored predictions table (see ``metrics_from_table``).
  * Synthetic data can exercise the code but its results are flagged and never reported
    as scientific findings.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ splits


@dataclass(frozen=True)
class Split:
    name: str
    train_index: np.ndarray
    test_index: np.ndarray


def temporal_holdout(df: pd.DataFrame, time_col: str, cutoff: date) -> Split:
    t = pd.to_datetime(df[time_col]).dt.date
    return Split(f"temporal<{cutoff}", np.flatnonzero(t < cutoff), np.flatnonzero(t >= cutoff))


def rolling_origin(df: pd.DataFrame, time_col: str, origins: Sequence[date], horizon_days: int) -> list[Split]:
    t = pd.to_datetime(df[time_col]).dt.date
    out = []
    for o in origins:
        end = o + pd.Timedelta(days=horizon_days).to_pytimedelta()
        out.append(Split(f"origin={o}", np.flatnonzero(t < o), np.flatnonzero((t >= o) & (t < end))))
    return out


def group_holdout(df: pd.DataFrame, group_col: str, test_groups: Iterable[str]) -> Split:
    tg = set(test_groups)
    g = df[group_col].astype(str)
    return Split(f"groups={sorted(tg)}", np.flatnonzero(~g.isin(tg)), np.flatnonzero(g.isin(tg)))


def leave_one_group_out(df: pd.DataFrame, group_col: str) -> list[Split]:
    return [group_holdout(df, group_col, [g]) for g in sorted(df[group_col].astype(str).unique())]


# ------------------------------------------------------------------ leakage checks


@dataclass
class LeakageReport:
    ok: bool
    problems: list[str] = field(default_factory=list)


def check_split(df: pd.DataFrame, split: Split, *, time_col: str | None = None, group_col: str | None = None, id_cols: Sequence[str] = ()) -> LeakageReport:
    """Check a split. Pass ``time_col`` for temporal splits (train must precede test) and
    ``group_col`` for geographic splits (no group may appear on both sides)."""
    problems: list[str] = []
    if np.intersect1d(split.train_index, split.test_index).size:
        problems.append("rows appear in both train and test")
    tr, te = df.iloc[split.train_index], df.iloc[split.test_index]
    if time_col and len(tr) and len(te) and pd.to_datetime(tr[time_col]).max() >= pd.to_datetime(te[time_col]).min():
        problems.append("temporal split is not chronological (train max >= test min)")
    if group_col and len(tr) and len(te):
        overlap = set(tr[group_col].astype(str)) & set(te[group_col].astype(str))
        if overlap:
            problems.append(f"groups present in both train and test: {sorted(overlap)[:5]}")
    if id_cols and len(tr) and len(te):
        dup = pd.merge(tr[list(id_cols)].drop_duplicates(), te[list(id_cols)].drop_duplicates(), how="inner")
        if len(dup):
            problems.append(f"{len(dup)} duplicate observation keys across train/test")
    return LeakageReport(not problems, problems)


def check_feature_availability(df: pd.DataFrame, prediction_time_col: str, available_cols: Sequence[str]) -> LeakageReport:
    """Every feature's availability timestamp must be <= the prediction timestamp."""
    problems = []
    pt = pd.to_datetime(df[prediction_time_col], utc=True)
    for c in available_cols:
        late = pd.to_datetime(df[c], utc=True) > pt
        if late.any():
            problems.append(f"{int(late.sum())} rows use {c} after the prediction time")
    return LeakageReport(not problems, problems)


# ------------------------------------------------------------------ metrics


def confusion(y_true: Sequence[int], y_pred: Sequence[int]) -> dict[str, int]:
    yt, yp = np.asarray(y_true, bool), np.asarray(y_pred, bool)
    return {"tp": int((yt & yp).sum()), "fp": int((~yt & yp).sum()), "fn": int((yt & ~yp).sum()), "tn": int((~yt & ~yp).sum())}


def precision_recall(y_true: Sequence[int], y_pred: Sequence[int]) -> dict[str, float | None]:
    c = confusion(y_true, y_pred)
    p = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else None
    r = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else None
    return {"precision": p, "recall": r, **{k: float(v) for k, v in c.items()}}


def pr_auc(y_true: Sequence[int], score: Sequence[float]) -> float | None:
    """Average precision (step-wise PR-AUC). Higher score = more likely positive."""
    yt = np.asarray(y_true, int)
    s = np.asarray(score, float)
    if yt.sum() == 0:
        return None
    order = np.argsort(-s, kind="mergesort")
    yt = yt[order]
    tp = np.cumsum(yt)
    precision = tp / np.arange(1, len(yt) + 1)
    return float((precision * yt).sum() / yt.sum())


def brier(y_true: Sequence[int], prob: Sequence[float]) -> float:
    return float(np.mean((np.asarray(prob, float) - np.asarray(y_true, float)) ** 2))


def log_loss(y_true: Sequence[int], prob: Sequence[float], eps: float = 1e-12) -> float:
    p = np.clip(np.asarray(prob, float), eps, 1 - eps)
    y = np.asarray(y_true, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def reliability_table(y_true: Sequence[int], prob: Sequence[float], bins: int = 10) -> list[dict[str, float]]:
    p, y = np.asarray(prob, float), np.asarray(y_true, float)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (p >= lo) & ((p < hi) | (hi == 1.0))
        if m.any():
            out.append({"bin_lo": float(lo), "bin_hi": float(hi), "n": int(m.sum()), "mean_pred": float(p[m].mean()), "obs_rate": float(y[m].mean())})
    return out


def false_alerts_per_unit_time(y_true: Sequence[int], y_pred: Sequence[int], unit_ids: Sequence[str], periods: float) -> float | None:
    """False alerts per unit (field/district) per period (e.g. per season)."""
    c = confusion(y_true, y_pred)
    n_units = len(set(unit_ids))
    if n_units == 0 or periods <= 0:
        return None
    return c["fp"] / n_units / periods


def event_detection(events: pd.DataFrame, alerts: pd.DataFrame, max_lead_days: int, max_lag_days: int) -> dict[str, Any]:
    """Match independent events (unit, event_date) to alerts (unit, alert_date).

    An event is detected if an alert for the same unit falls in
    [event_date − max_lead_days, event_date + max_lag_days]. Lead time is reported only
    for events whose date is independently known.
    """
    detected, leads = 0, []
    for _, ev in events.iterrows():
        a = alerts[alerts["unit"] == ev["unit"]]
        delta = (pd.to_datetime(ev["event_date"]) - pd.to_datetime(a["alert_date"])).dt.days
        hit = delta[(delta <= max_lead_days) & (delta >= -max_lag_days)]
        if len(hit):
            detected += 1
            leads.append(int(hit.max()))
    n = len(events)
    return {"events": n, "detected": detected, "detection_rate": detected / n if n else None, "median_lead_days": float(np.median(leads)) if leads else None}


def block_bootstrap_ci(
    df: pd.DataFrame, block_col: str, stat: Callable[[pd.DataFrame], float | None], n_boot: int = 1000, alpha: float = 0.1, seed: int = 0
) -> tuple[float, float] | None:
    """Cluster (block) bootstrap: resample whole blocks (e.g. districts or seasons), not rows."""
    blocks = df[block_col].astype(str).unique()
    if len(blocks) < 3:
        return None
    rng = np.random.default_rng(seed)
    groups = {b: df[df[block_col].astype(str) == b] for b in blocks}
    vals = []
    for _ in range(n_boot):
        pick = rng.choice(blocks, size=len(blocks), replace=True)
        v = stat(pd.concat([groups[b] for b in pick], ignore_index=True))
        if v is not None and not np.isnan(v):
            vals.append(v)
    if len(vals) < n_boot * 0.5:
        return None
    return float(np.quantile(vals, alpha / 2)), float(np.quantile(vals, 1 - alpha / 2))


def metrics_from_table(
    pred: pd.DataFrame, *, label_col: str = "label", flag_col: str = "flag", score_col: str | None = "score", block_col: str | None = None
) -> dict[str, Any]:
    """Recompute all reportable metrics from a stored predictions table (reproducibility)."""
    m: dict[str, Any] = {"n": int(len(pred)), "positives": int(pred[label_col].sum())}
    m.update(precision_recall(pred[label_col], pred[flag_col]))
    if score_col and score_col in pred:
        m["pr_auc"] = pr_auc(pred[label_col], pred[score_col])
    if block_col:
        m["recall_ci90"] = block_bootstrap_ci(pred, block_col, lambda d: precision_recall(d[label_col], d[flag_col])["recall"])
        m["precision_ci90"] = block_bootstrap_ci(pred, block_col, lambda d: precision_recall(d[label_col], d[flag_col])["precision"])
    return m

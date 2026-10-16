"""Real-data research pipeline for public sample points (config/research_points.yaml).

Stage 1 ``fetch``    : MODIS MOD13Q1 (NDVI + reliability) and NASA POWER → Parquet + manifest.
Stage 2 ``analyze``  : data coverage/quality tables and an UNLABELLED descriptive backtest of
                       the screening engine with simulated availability.
Both stages refuse synthetic data. Raw API responses are cached under data/raw/ so the
analysis is reproducible from the same inputs (checksums recorded in the manifest).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from croppulse.config import REPO_ROOT, get_settings, science_config
from croppulse.geo.geometry import validate_field_geometry
from croppulse.logging_setup import log
from croppulse.research.backtest import backtest_unit
from croppulse.research.reports import assert_real_data, file_sha256, write_manifest
from croppulse.risk.engine import FieldContext
from croppulse.science.anomaly import SeriesPoint
from croppulse.sources.modis_ornl import LandCoverAdapter, ModisOrnlAdapter
from croppulse.sources.nasa_power import NasaPowerAdapter, grid_cell_for

logger = logging.getLogger(__name__)
ART = REPO_ROOT / "reports" / "artifacts"


def load_points() -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / "config" / "research_points.yaml").read_text())


def _footprint(lat: float, lon: float, h: float) -> dict[str, Any]:
    return {"type": "Polygon", "coordinates": [[[lon - h, lat - h], [lon + h, lat - h], [lon + h, lat + h], [lon - h, lat + h], [lon - h, lat - h]]]}


def research_dir() -> Path:
    d = get_settings().data_dir / "processed" / "research"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch(point_ids: list[str] | None = None) -> dict[str, Any]:
    cfg = load_points()
    vcfg = science_config()["vegetation"]
    modis, lc, power = ModisOrnlAdapter(), LandCoverAdapter(), NasaPowerAdapter()
    manifest: dict[str, Any] = {"points": {}, "power_cells": {}}
    out = research_dir()
    for p in cfg["points"]:
        if point_ids and p["id"] not in point_ids:
            continue
        g = validate_field_geometry(_footprint(p["lat"], p["lon"], cfg["footprint_half_deg"]))
        log(logger, logging.INFO, "research fetch modis", point=p["id"])
        series = modis.field_series(
            g.geojson,
            (g.centroid_lat, g.centroid_lon),
            g.bbox,
            date(cfg["modis_start_year"], 1, 1),
            accepted_reliability=set(vcfg["accepted_reliability"]),
            min_valid_fraction=vcfg["min_valid_pixel_fraction"],
            window_km_min=vcfg["fetch_window_km"],
            include_evi=False,
        )
        rows = [
            {
                "point": p["id"],
                "period_start": c.period_start,
                "period_end": c.period_end,
                "ndvi": c.ndvi,
                "accepted": c.accepted,
                "rejection_reason": c.rejection_reason,
                "valid_pixels": c.valid_pixels,
                "selected_pixels": c.selected_pixels,
                "valid_fraction": c.valid_fraction,
                "reliability_counts": json.dumps(c.reliability_counts, sort_keys=True),
                "published_at": c.published_at,
                "tile": c.tile,
                "is_synthetic": series.is_synthetic,
            }
            for c in series.composites
        ]
        df = pd.DataFrame(rows)
        assert_real_data(df, f"MODIS {p['id']}")
        path = out / f"{p['id']}_mod13q1.parquet"
        df.to_parquet(path, index=False)
        land = lc.latest(g.centroid_lat, g.centroid_lon)
        manifest["points"][p["id"]] = {
            "lat": p["lat"],
            "lon": p["lon"],
            "footprint_area_ha": g.area_ha,
            "pixel_rule": series.selection.rule,
            "pixels_selected": len(series.selection.indices),
            "window_km": series.window_km,
            "modis_file": str(path.relative_to(get_settings().data_dir)),
            "modis_sha256": file_sha256(path),
            "modis_rows": len(df),
            "modis_retrieved_at": series.retrieved_at,
            "modis_warnings": series.warnings[:20],
            "land_cover": {"year": land.year, "lc_type1": land.lc_type1},
            "raw_cache_files": len(series.raw_refs),
        }
        cell = grid_cell_for(p["lat"], p["lon"])
        manifest["points"][p["id"]]["power_cell"] = cell.key
        if cell.key not in manifest["power_cells"]:
            log(logger, logging.INFO, "research fetch power", cell=cell.key)
            ps = power.fetch(cell, date(1981, 1, 1))
            wdf = ps.frame.reset_index()
            wdf["date"] = pd.to_datetime(wdf["date"])
            wdf["is_synthetic"] = ps.is_synthetic
            assert_real_data(wdf, f"POWER {cell.key}")
            wpath = out / f"{cell.key}.parquet"
            wdf.to_parquet(wpath, index=False)
            manifest["power_cells"][cell.key] = {
                "lat": cell.lat,
                "lon": cell.lon,
                "file": str(wpath.relative_to(get_settings().data_dir)),
                "sha256": file_sha256(wpath),
                "rows": len(wdf),
                "last_valid_date": ps.last_valid_date,
                "units": ps.units,
                "sources": ps.sources,
                "api_version": ps.api_version,
                "time_standard": ps.time_standard,
                "retrieved_at": ps.retrieved_at,
            }
    ART.mkdir(parents=True, exist_ok=True)
    path = ART / "research_data_manifest.json"
    existing = json.loads(path.read_text()) if path.exists() else {"points": {}, "power_cells": {}}
    existing["points"].update(manifest["points"])
    existing["power_cells"].update(manifest["power_cells"])
    existing.pop("generated_at", None)
    write_manifest(path, existing)
    return existing


def _load_point(pid: str, man: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = get_settings().data_dir
    m = pd.read_parquet(d / man["points"][pid]["modis_file"])
    w = pd.read_parquet(d / man["power_cells"][man["points"][pid]["power_cell"]]["file"])
    assert_real_data(m, pid)
    assert_real_data(w, pid)
    m["period_start"] = pd.to_datetime(m["period_start"]).dt.date
    m["period_end"] = pd.to_datetime(m["period_end"]).dt.date
    w["date"] = pd.to_datetime(w["date"]).dt.date
    return m, w.set_index("date").drop(columns=["is_synthetic"])


def coverage_tables(man: dict[str, Any]) -> dict[str, pd.DataFrame]:
    per_point, per_month = [], []
    for pid in man["points"]:
        m, w = _load_point(pid, man)
        lat_end = max(m["period_end"])
        per_point.append(
            {
                "point": pid,
                "composites": len(m),
                "first": min(m["period_start"]),
                "latest_period_end": lat_end,
                "accepted_share": round(float(m["accepted"].mean()), 3),
                "kharif_jun_sep_accepted_share": round(float(m[pd.to_datetime(m["period_start"]).dt.month.isin([6, 7, 8, 9])]["accepted"].mean()), 3),
                "rejected_no_quality_pixels": int((m["rejection_reason"] == "no_quality_accepted_pixels").sum()),
                "rejected_low_valid_fraction": int((m["rejection_reason"] == "valid_pixel_fraction_below_minimum").sum()),
                "pixels_selected": man["points"][pid]["pixels_selected"],
                "land_cover_2024": man["points"][pid]["land_cover"]["lc_type1"],
                "power_last_valid": man["power_cells"][man["points"][pid]["power_cell"]]["last_valid_date"],
                "power_missing_share_1991_on": round(float(w.loc[w.index >= date(1991, 1, 1), "PRECTOTCORR"].isna().mean()), 4),
                "median_publication_lag_days": float(
                    np.median([(pd.Timestamp(p).date() - e).days for p, e in zip(m["published_at"], m["period_end"], strict=True) if pd.notna(p)])
                ),
            }
        )
        mm = m.assign(month=pd.to_datetime(m["period_start"]).dt.month).groupby("month")["accepted"].mean()
        per_month.append(mm.rename(pid))
    return {"per_point": pd.DataFrame(per_point), "accepted_by_month": pd.concat(per_month, axis=1).round(3)}


def descriptive_backtest(man: dict[str, Any]) -> pd.DataFrame:
    cfg = load_points()
    sci = science_config()
    frames = []
    for pid in man["points"]:
        m, w = _load_point(pid, man)
        series = [
            (
                SeriesPoint(r.period_start, None if pd.isna(r.ndvi) else float(r.ndvi), bool(r.accepted), datetime(1970, 1, 1, tzinfo=UTC)),
                r.period_end,
                {"valid_fraction": r.valid_fraction, "selection_rule": man["points"][pid]["pixel_rule"]},
            )
            for r in m.itertuples()
        ]
        lc = man["points"][pid]["land_cover"]
        ctx = FieldContext(pid, "unknown_kharif_crop", "kharif", None, False, "polygon", lc["lc_type1"], lc["year"])
        dates = [date(y, int(md[:2]), int(md[3:])) for y in cfg["backtest_years"] for md in cfg["backtest_dates"]]
        bt = backtest_unit(pid, ctx, series, w, dates, sci)
        bt["power_cell"] = man["points"][pid]["power_cell"]
        frames.append(bt)
    out = pd.concat(frames, ignore_index=True)
    out["is_synthetic"] = False
    return out

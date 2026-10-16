"""NASA POWER daily point adapter (verified live 2026-10-15, API v2.10.0).

Privacy: requests are made for the centre of the POWER meteorology grid cell that
contains the field, never the field's own coordinates, and series are stored per
grid cell so neighbouring fields share one dataset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from croppulse.sources.base import HttpFetcher, SourceSchemaError, relpath

BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMETERS = ["PRECTOTCORR", "T2M_MAX", "T2M_MIN", "T2M", "RH2M", "ALLSKY_SFC_SW_DWN"]
EXPECTED_UNITS = {
    "PRECTOTCORR": "mm/day",
    "T2M_MAX": "C",
    "T2M_MIN": "C",
    "T2M": "C",
    "RH2M": "%",
    "ALLSKY_SFC_SW_DWN": "MJ/m^2/day",
}
# MERRA-2 grid used by POWER meteorology
GRID_DLAT = 0.5
GRID_DLON = 0.625


@dataclass(frozen=True)
class GridCell:
    lat: float
    lon: float

    @property
    def key(self) -> str:
        return f"power_{self.lat:+07.2f}_{self.lon:+08.3f}".replace("+", "p").replace("-", "m")


def grid_cell_for(lat: float, lon: float) -> GridCell:
    clat = round(round((lat + 90) / GRID_DLAT) * GRID_DLAT - 90, 4)
    clon = round(round((lon + 180) / GRID_DLON) * GRID_DLON - 180, 4)
    return GridCell(clat, clon)


@dataclass
class PowerSeries:
    cell: GridCell
    frame: pd.DataFrame          # index: date; columns: PARAMETERS; NaN where the source has fill
    units: dict[str, str]
    sources: list[str]
    api_version: str
    time_standard: str
    retrieved_at: datetime
    raw_ref: str | None
    last_valid_date: date | None
    request_url: str
    is_synthetic: bool = False


def parse_power_payload(payload: dict, cell: GridCell, retrieved_at: datetime, raw_ref: str | None, url: str) -> PowerSeries:
    try:
        header = payload["header"]
        params = payload["properties"]["parameter"]
        units = {k: v["units"] for k, v in payload["parameters"].items()}
    except (KeyError, TypeError) as exc:
        raise SourceSchemaError(f"POWER response missing expected structure: {exc}") from exc
    for p, u in EXPECTED_UNITS.items():
        if p in units and units[p] != u:
            raise SourceSchemaError(f"POWER unit change for {p}: expected {u!r}, got {units[p]!r}")
    fill = float(header.get("fill_value", -999.0))
    cols = {}
    for p in PARAMETERS:
        if p not in params:
            continue
        s = pd.Series(params[p], dtype="float64")
        s.index = pd.to_datetime(s.index, format="%Y%m%d").date
        s[np.isclose(s, fill)] = np.nan
        cols[p] = s
    if "PRECTOTCORR" not in cols:
        raise SourceSchemaError("POWER response lacks PRECTOTCORR")
    frame = pd.DataFrame(cols).sort_index()
    frame.index.name = "date"
    # Physical-range checks: out-of-range values are set to NaN and counted, not silently kept.
    bad = (frame["PRECTOTCORR"] < 0) | (frame["PRECTOTCORR"] > 1000)
    frame.loc[bad, "PRECTOTCORR"] = np.nan
    for t in ("T2M_MAX", "T2M_MIN", "T2M"):
        if t in frame:
            frame.loc[(frame[t] < -60) | (frame[t] > 65), t] = np.nan
    valid = frame["PRECTOTCORR"].dropna()
    last_valid = valid.index.max() if not valid.empty else None
    return PowerSeries(
        cell=cell,
        frame=frame,
        units=units,
        sources=list(header.get("sources", [])),
        api_version=str(header.get("api", {}).get("version", "unknown")),
        time_standard=str(header.get("time_standard", "unknown")),
        retrieved_at=retrieved_at,
        raw_ref=raw_ref,
        last_valid_date=last_valid,
        request_url=url,
        is_synthetic=bool(payload.get("_synthetic")),
    )


class NasaPowerAdapter:
    source_id = "nasa_power_daily"

    def __init__(self, fetcher: HttpFetcher | None = None) -> None:
        self.fetcher = fetcher or HttpFetcher(self.source_id)

    def fetch(self, cell: GridCell, start: date, end: date | None = None) -> PowerSeries:
        end = end or datetime.now(UTC).date()
        params = {
            "parameters": ",".join(PARAMETERS),
            "community": "AG",
            "latitude": cell.lat,
            "longitude": cell.lon,
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
        }
        raw = self.fetcher.get_json(BASE_URL, params, use_cache=False)
        if not isinstance(raw.payload, dict):
            raise SourceSchemaError("POWER returned a non-object response")
        if raw.payload.get("messages"):
            msgs = raw.payload["messages"]
            if any("error" in str(m).lower() for m in msgs):
                raise SourceSchemaError(f"POWER reported errors: {msgs}")
        return parse_power_payload(raw.payload, cell, raw.retrieved_at, relpath(raw.cache_path), BASE_URL)


def latency_days(last_valid: date | None, now: datetime | None = None) -> float | None:
    if last_valid is None:
        return None
    now = now or datetime.now(UTC)
    return float((now.date() - last_valid).days)


def is_finite(x: float | None) -> bool:
    return x is not None and not math.isnan(x)

"""SYNTHETIC test fixtures — deterministic fake responses in the real wire formats.

Everything generated here is synthetic. Payloads carry ``"_synthetic": true`` and
fields built from them are flagged ``is_synthetic``. They exist only so tests are
deterministic and offline; they are excluded from every scientific report.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import numpy as np

from croppulse.geo.geometry import sinusoidal_forward

CELL = 231.656358264


def modis_dates(start_year: int, end: date) -> list[tuple[str, date]]:
    out = []
    for y in range(start_year, end.year + 1):
        for doy in range(1, 366, 16):
            d = date(y, 1, 1) + timedelta(days=doy - 1)
            if d.year != y or d > end:
                continue
            out.append((f"A{y}{doy:03d}", d))
    return out


def seasonal_ndvi(d: date) -> float:
    """Kharif-like seasonal curve: low in April–May, peak in late August–September."""
    doy = d.timetuple().tm_yday
    return 0.25 + 0.45 * math.exp(-(((doy - 245) / 45.0) ** 2))


@dataclass
class SyntheticWorld:
    """Configurable synthetic data generator."""

    today: date = field(default_factory=date.today)
    first_year: int = 2008
    anomaly_year: int | None = None  # inject a drop in this year …
    anomaly_from: date | None = None  # … from this composite onwards
    anomaly_delta: float = -0.25
    cloudy_dates: set[str] = field(default_factory=set)
    noise: float = 0.02
    interannual_sd: float = 0.04
    rain_scale_target_year: float = 1.0  # multiply rainfall in the final 90 days
    power_fail: bool = False
    modis_fail: bool = False
    calls: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- ORNL
    def _ndvi(self, mdate: str, d: date, i: int) -> int:
        rng = np.random.default_rng(zlib.crc32(f"{mdate}:{i}".encode()))
        year_effect = np.random.default_rng(d.year).normal(0, self.interannual_sd)  # shared by all pixels in a year
        v = seasonal_ndvi(d) + year_effect + rng.normal(0, self.noise)
        if self.anomaly_year and d.year == self.anomaly_year and self.anomaly_from and d >= self.anomaly_from:
            v += self.anomaly_delta
        return int(round(v / 0.0001))

    def ornl(self, path: str, q: dict[str, str]) -> Any:
        product = path.split("/")[-2]
        lat, lon = float(q["latitude"]), float(q["longitude"])
        if path.endswith("/dates"):
            if product == "MCD12Q1":
                return {"dates": [{"modis_date": "A2024001", "calendar_date": "2024-01-01"}], "_synthetic": True}
            return {
                "dates": [{"modis_date": m, "calendar_date": d.isoformat()} for m, d in modis_dates(self.first_year, self.today - timedelta(days=31))],
                "_synthetic": True,
            }
        km = int(q["kmAboveBelow"])
        band = q["band"]
        all_dates = dict(modis_dates(self.first_year, self.today))
        keys = sorted(all_dates)
        sel = [k for k in keys if q["startDate"] <= k <= q["endDate"]]
        if len(sel) > 10:
            return f"Subset time period {q['startDate']} to {q['endDate']} exceeds maximum subset tiles support of 10."
        if product == "MCD12Q1":
            x, y = sinusoidal_forward(lat, lon)
            return {
                "xllcorner": str(x - 231),
                "yllcorner": str(y - 231),
                "cellsize": 463.3,
                "nrows": 1,
                "ncols": 1,
                "band": band,
                "_synthetic": True,
                "subset": [
                    {"modis_date": "A2024001", "calendar_date": "2024-01-01", "band": band, "tile": "h25v07", "proc_date": "2025206031834", "data": [12]}
                ],
            }
        n = 2 * math.ceil(km * 1000 / CELL) + 1 if km > 0 else 1
        x, y = sinusoidal_forward(lat, lon)
        cx = math.floor(x / CELL) * CELL
        cy = math.floor(y / CELL) * CELL
        half = n // 2
        xll, yll = cx - half * CELL, cy - half * CELL
        subset = []
        for k in sel:
            d = all_dates[k]
            if band.endswith("NDVI"):
                data = [self._ndvi(k, d, i) for i in range(n * n)]
            elif band.endswith("EVI"):
                data = [int(self._ndvi(k, d, i) * 0.6) for i in range(n * n)]
            else:
                data = [3 if k in self.cloudy_dates else 0 for _ in range(n * n)]
            proc = d + timedelta(days=20)
            subset.append(
                {
                    "modis_date": k,
                    "calendar_date": d.isoformat(),
                    "band": band,
                    "tile": "h25v07",
                    "proc_date": f"{proc.year}{proc.timetuple().tm_yday:03d}120000",
                    "data": data,
                }
            )
        return {
            "xllcorner": f"{xll:.2f}",
            "yllcorner": f"{yll:.2f}",
            "cellsize": CELL,
            "nrows": n,
            "ncols": n,
            "band": band,
            "_synthetic": True,
            "subset": subset,
        }

    # ---------------------------------------------------------------- POWER
    def power(self, q: dict[str, str]) -> Any:
        start = date(int(q["start"][:4]), int(q["start"][4:6]), int(q["start"][6:]))
        end = date(int(q["end"][:4]), int(q["end"][4:6]), int(q["end"][6:]))
        params = q["parameters"].split(",")
        out: dict[str, dict[str, float]] = {p: {} for p in params}
        d = start
        while d <= end:
            key = d.strftime("%Y%m%d")
            doy = d.timetuple().tm_yday
            monsoon = math.exp(-(((doy - 210) / 40.0) ** 2))
            rng = np.random.default_rng(int(key))
            rain = max(0.0, rng.gamma(0.6, 12.0) * monsoon - 0.5)
            if (self.today - d).days < 90:
                rain *= self.rain_scale_target_year
            tmax = 31 + 8 * math.exp(-(((doy - 130) / 35.0) ** 2)) + rng.normal(0, 1)
            vals = {
                "PRECTOTCORR": round(rain, 2),
                "T2M_MAX": round(tmax, 2),
                "T2M_MIN": round(tmax - 12, 2),
                "T2M": round(tmax - 6, 2),
                "RH2M": 60.0,
                "ALLSKY_SFC_SW_DWN": 20.0,
            }
            lag = (self.today - d).days
            for p in params:
                out[p][key] = -999.0 if lag < 3 else vals[p]
            d += timedelta(days=1)
        units = {"PRECTOTCORR": "mm/day", "T2M_MAX": "C", "T2M_MIN": "C", "T2M": "C", "RH2M": "%", "ALLSKY_SFC_SW_DWN": "MJ/m^2/day"}
        return {
            "type": "Feature",
            "_synthetic": True,
            "geometry": {"type": "Point", "coordinates": [float(q["longitude"]), float(q["latitude"]), 500]},
            "properties": {"parameter": out},
            "header": {
                "title": "SYNTHETIC",
                "api": {"version": "synthetic"},
                "sources": ["SYNTHETIC"],
                "fill_value": -999.0,
                "time_standard": "LST",
                "start": q["start"],
                "end": q["end"],
            },
            "messages": [],
            "parameters": {p: {"units": units[p], "longname": p} for p in params},
        }

    # ---------------------------------------------------------------- transport
    def transport(self) -> FakeTransport:
        return FakeTransport(self)


class FakeTransport:
    def __init__(self, world: SyntheticWorld) -> None:
        self.world = world

    def get(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> httpx.Response:
        q = {k: str(v) for k, v in (params or {}).items()}
        parsed = urlparse(url)
        q.update({k: v[0] for k, v in parse_qs(parsed.query).items()})
        self.world.calls.append(parsed.path)
        req = httpx.Request("GET", url)
        if "modis.ornl.gov" in url:
            if self.world.modis_fail:
                return httpx.Response(503, text="Service Unavailable", request=req)
            return httpx.Response(200, json=self.world.ornl(parsed.path, q), request=req)
        if "power.larc.nasa.gov" in url:
            if self.world.power_fail:
                return httpx.Response(503, text="Service Unavailable", request=req)
            return httpx.Response(200, json=self.world.power(q), request=req)
        return httpx.Response(404, request=req)


def square_polygon(lat: float, lon: float, half_deg: float = 0.004) -> dict[str, Any]:
    """~0.9 km × 0.9 km square (≈ 70 ha) around a point — SYNTHETIC test field."""
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - half_deg, lat - half_deg],
                [lon + half_deg, lat - half_deg],
                [lon + half_deg, lat + half_deg],
                [lon - half_deg, lat + half_deg],
                [lon - half_deg, lat - half_deg],
            ]
        ],
    }

"""MODIS adapters using the ORNL DAAC MODIS/VIIRS Web Service (TESViS).

Verified against the live service on 2026-10-15:
  GET /rst/api/v1/{product}/dates?latitude&longitude
  GET /rst/api/v1/{product}/subset?latitude&longitude&band&startDate&endDate&kmAboveBelow&kmLeftRight
  - at most 10 composite dates per subset request (otherwise a JSON *string* error is returned)
  - data arrays are row-major from the north-west pixel; header carries xllcorner/yllcorner/cellsize (sinusoidal metres)
  - each composite carries proc_date (YYYYDDDHHMMSS) — the provider processing time
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from croppulse.geo.geometry import PixelSelection, select_pixels
from croppulse.sources.base import HttpFetcher, RawResponse, SourceSchemaError, relpath

BASE_URL = "https://modis.ornl.gov/rst/api/v1"
MAX_DATES_PER_REQUEST = 10

# MOD13Q1 band decoding (from the live /bands endpoint and the MOD13 user guide)
VI_SCALE = 0.0001
VI_FILL = -3000
VI_VALID = (-2000, 10000)
RELIABILITY_FILL = -1
RELIABILITY_LABELS = {0: "good", 1: "marginal", 2: "snow_ice", 3: "cloudy", -1: "fill"}

BAND_NDVI = "250m_16_days_NDVI"
BAND_EVI = "250m_16_days_EVI"
BAND_REL = "250m_16_days_pixel_reliability"


def parse_proc_date(proc: str | None) -> datetime | None:
    """ORNL proc_date 'YYYYDDDHHMMSS' → UTC datetime (None if absent/unparseable)."""
    if not proc or len(proc) < 13 or not proc.isdigit():
        return None
    year, doy = int(proc[:4]), int(proc[4:7])
    hh, mm, ss = int(proc[7:9]), int(proc[9:11]), int(proc[11:13])
    return datetime(year, 1, 1, hh, mm, ss, tzinfo=UTC) + timedelta(days=doy - 1)


def composite_period(start: date) -> tuple[date, date]:
    """16-day composite period. The final composite of a year (DOY 353/361) is truncated at 31 Dec.

    Assumption documented in docs/DATA_SOURCES.md: MOD13 composites restart at DOY 001 each year.
    """
    end = start + timedelta(days=15)
    year_end = date(start.year, 12, 31)
    return start, min(end, year_end)


def decode_vi(raw: int | None) -> float | None:
    """Scaled VI value, or None for fill / out-of-range. Never returns 0 for missing data."""
    if raw is None or raw == VI_FILL or not (VI_VALID[0] <= raw <= VI_VALID[1]):
        return None
    return raw * VI_SCALE


def _check_subset(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        raise SourceSchemaError(f"ORNL service returned an error message: {payload[:200]}")
    required = {"xllcorner", "yllcorner", "cellsize", "nrows", "ncols", "subset"}
    if not isinstance(payload, dict) or not required <= payload.keys():
        raise SourceSchemaError("ORNL subset response missing expected keys (schema change?)")
    n = int(payload["nrows"]) * int(payload["ncols"])
    for item in payload["subset"]:
        if len(item.get("data", [])) != n:
            raise SourceSchemaError("ORNL subset data length does not match nrows×ncols")
    return payload


@dataclass
class CompositeAggregate:
    period_start: date
    period_end: date
    ndvi: float | None
    evi: float | None
    accepted: bool
    rejection_reason: str | None
    valid_pixels: int
    selected_pixels: int
    valid_fraction: float
    reliability_counts: dict[str, int]
    published_at: datetime | None
    tile: str | None


@dataclass
class FieldVegetationSeries:
    composites: list[CompositeAggregate]
    selection: PixelSelection
    window_km: int
    retrieved_at: datetime
    raw_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_synthetic: bool = False  # True if any payload was a labelled synthetic fixture


def aggregate_composite(
    ndvi_raw: list[int],
    evi_raw: list[int] | None,
    rel_raw: list[int],
    idx: list[int],
    accepted_reliability: set[int],
    min_valid_fraction: float,
) -> tuple[float | None, float | None, int, dict[str, int], bool, str | None]:
    """Mean of quality-accepted pixels inside the selection.

    A pixel counts only if its reliability is accepted AND its VI decodes to a valid value.
    """
    counts: dict[str, int] = {}
    nd_vals: list[float] = []
    ev_vals: list[float] = []
    for i in idx:
        rel = rel_raw[i]
        counts[RELIABILITY_LABELS.get(rel, f"code_{rel}")] = counts.get(RELIABILITY_LABELS.get(rel, f"code_{rel}"), 0) + 1
        if rel not in accepted_reliability:
            continue
        nd = decode_vi(ndvi_raw[i])
        if nd is None:
            continue
        nd_vals.append(nd)
        if evi_raw is not None:
            ev = decode_vi(evi_raw[i])
            if ev is not None:
                ev_vals.append(ev)
    valid = len(nd_vals)
    frac = valid / len(idx) if idx else 0.0
    if valid == 0:
        return None, None, 0, counts, False, "no_quality_accepted_pixels"
    if frac < min_valid_fraction:
        return (
            sum(nd_vals) / valid,
            (sum(ev_vals) / len(ev_vals)) if ev_vals else None,
            valid,
            counts,
            False,
            "valid_pixel_fraction_below_minimum",
        )
    return sum(nd_vals) / valid, (sum(ev_vals) / len(ev_vals)) if ev_vals else None, valid, counts, True, None


class ModisOrnlAdapter:
    source_id = "modis_mod13q1"
    product = "MOD13Q1"

    def __init__(self, fetcher: HttpFetcher | None = None) -> None:
        self.fetcher = fetcher or HttpFetcher(self.source_id)

    def list_dates(self, lat: float, lon: float) -> list[tuple[str, date]]:
        raw = self.fetcher.get_json(f"{BASE_URL}/{self.product}/dates", {"latitude": round(lat, 5), "longitude": round(lon, 5)}, use_cache=False, cacheable=False)
        if not isinstance(raw.payload, dict) or "dates" not in raw.payload:
            raise SourceSchemaError("ORNL dates response missing 'dates'")
        return [(d["modis_date"], date.fromisoformat(d["calendar_date"])) for d in raw.payload["dates"]]

    def fetch_subset(self, band: str, lat: float, lon: float, start: str, end: str, km: int, *, use_cache: bool) -> RawResponse:
        params = {
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "band": band,
            "startDate": start,
            "endDate": end,
            "kmAboveBelow": km,
            "kmLeftRight": km,
        }
        raw = self.fetcher.get_json(f"{BASE_URL}/{self.product}/subset", params, use_cache=use_cache)
        _check_subset(raw.payload)
        return raw

    @staticmethod
    def window_km_for(bbox: tuple[float, float, float, float], minimum: int) -> int:
        min_lon, min_lat, max_lon, max_lat = bbox
        half_ns = (max_lat - min_lat) * 111.32 / 2
        half_ew = (max_lon - min_lon) * 111.32 * math.cos(math.radians((min_lat + max_lat) / 2)) / 2
        return max(minimum, math.ceil(max(half_ns, half_ew) + 0.25))

    def field_series(
        self,
        geojson: dict[str, Any],
        centroid: tuple[float, float],
        bbox: tuple[float, float, float, float],
        start: date,
        *,
        accepted_reliability: set[int],
        min_valid_fraction: float,
        window_km_min: int,
        today: date | None = None,
    ) -> FieldVegetationSeries:
        lat, lon = centroid
        today = today or datetime.now(UTC).date()
        km = self.window_km_for(bbox, window_km_min)
        dates = [(m, d) for m, d in self.list_dates(lat, lon) if d >= start]
        composites: list[CompositeAggregate] = []
        raw_refs: list[str] = []
        warnings: list[str] = []
        selection: PixelSelection | None = None
        retrieved_at = datetime.now(UTC)
        synthetic = False
        for i in range(0, len(dates), MAX_DATES_PER_REQUEST):
            chunk = dates[i : i + MAX_DATES_PER_REQUEST]
            # Historic chunks (all composites older than ~1 year) are immutable enough to cache;
            # recent chunks are always re-fetched so provider reprocessing is picked up.
            use_cache = (today - chunk[-1][1]).days > 400
            by_band: dict[str, RawResponse] = {}
            for band in (BAND_NDVI, BAND_EVI, BAND_REL):
                by_band[band] = self.fetch_subset(band, lat, lon, chunk[0][0], chunk[-1][0], km, use_cache=use_cache)
                ref = relpath(by_band[band].cache_path)
                if ref:
                    raw_refs.append(ref)
                retrieved_at = min(retrieved_at, by_band[band].retrieved_at)
                synthetic = synthetic or bool(by_band[band].payload.get("_synthetic"))
            hdr = by_band[BAND_NDVI].payload
            if selection is None:
                selection = select_pixels(
                    geojson, float(hdr["xllcorner"]), float(hdr["yllcorner"]), float(hdr["cellsize"]), int(hdr["nrows"]), int(hdr["ncols"])
                )
            nd_items = {s["modis_date"]: s for s in hdr["subset"]}
            ev_items = {s["modis_date"]: s for s in by_band[BAND_EVI].payload["subset"]}
            rel_items = {s["modis_date"]: s for s in by_band[BAND_REL].payload["subset"]}
            for mdate, cal in chunk:
                if mdate not in nd_items or mdate not in rel_items:
                    warnings.append(f"composite_missing_from_response:{mdate}")
                    continue
                nd, ev, valid, counts, ok, reason = aggregate_composite(
                    nd_items[mdate]["data"],
                    ev_items.get(mdate, {}).get("data"),
                    rel_items[mdate]["data"],
                    selection.indices,
                    accepted_reliability,
                    min_valid_fraction,
                )
                p0, p1 = composite_period(cal)
                composites.append(
                    CompositeAggregate(
                        period_start=p0,
                        period_end=p1,
                        ndvi=nd if ok else None,
                        evi=ev if ok else None,
                        accepted=ok,
                        rejection_reason=reason,
                        valid_pixels=valid,
                        selected_pixels=len(selection.indices),
                        valid_fraction=valid / len(selection.indices),
                        reliability_counts=counts,
                        published_at=parse_proc_date(nd_items[mdate].get("proc_date")),
                        tile=nd_items[mdate].get("tile"),
                    )
                )
        if selection is None:
            raise SourceSchemaError("No MODIS composites were returned for the requested period")
        if selection.note:
            warnings.append("field_represented_by_single_pixel")
        return FieldVegetationSeries(composites, selection, km, retrieved_at, raw_refs, warnings, synthetic)


@dataclass
class LandCoverResult:
    year: int
    lc_type1: int | None
    published_at: datetime | None
    retrieved_at: datetime
    raw_ref: str | None
    is_synthetic: bool = False


class LandCoverAdapter:
    source_id = "modis_mcd12q1"
    product = "MCD12Q1"

    def __init__(self, fetcher: HttpFetcher | None = None) -> None:
        self.fetcher = fetcher or HttpFetcher(self.source_id)

    def latest(self, lat: float, lon: float) -> LandCoverResult:
        raw = self.fetcher.get_json(f"{BASE_URL}/{self.product}/dates", {"latitude": round(lat, 5), "longitude": round(lon, 5)}, use_cache=False, cacheable=False)
        dates = raw.payload.get("dates") if isinstance(raw.payload, dict) else None
        if not dates:
            raise SourceSchemaError("MCD12Q1 dates response empty")
        last = dates[-1]
        params = {
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "band": "LC_Type1",
            "startDate": last["modis_date"],
            "endDate": last["modis_date"],
            "kmAboveBelow": 0,
            "kmLeftRight": 0,
        }
        sub = self.fetcher.get_json(f"{BASE_URL}/{self.product}/subset", params)
        payload = _check_subset(sub.payload)
        item = payload["subset"][0]
        val = item["data"][0]
        return LandCoverResult(
            year=int(last["calendar_date"][:4]),
            lc_type1=None if val == 255 else int(val),
            published_at=parse_proc_date(item.get("proc_date")),
            retrieved_at=sub.retrieved_at,
            raw_ref=relpath(sub.cache_path),
            is_synthetic=bool(payload.get("_synthetic")),
        )


IGBP_LABELS = {
    1: "Evergreen Needleleaf Forests",
    2: "Evergreen Broadleaf Forests",
    3: "Deciduous Needleleaf Forests",
    4: "Deciduous Broadleaf Forests",
    5: "Mixed Forests",
    6: "Closed Shrublands",
    7: "Open Shrublands",
    8: "Woody Savannas",
    9: "Savannas",
    10: "Grasslands",
    11: "Permanent Wetlands",
    12: "Croplands",
    13: "Urban and Built-up Lands",
    14: "Cropland/Natural Vegetation Mosaics",
    15: "Permanent Snow and Ice",
    16: "Barren",
    17: "Water Bodies",
}

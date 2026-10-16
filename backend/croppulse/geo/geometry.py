"""Field geometry validation and MODIS sinusoidal-grid helpers.

Field boundaries are accepted as GeoJSON (EPSG:4326, lon/lat order). Validation
rejects — never silently repairs — invalid geometries so the user can correct them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely import Point, Polygon, from_geojson, to_geojson
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from shapely.validation import explain_validity

# India bounding box (generous) — fields outside are rejected for the India-first MVP.
INDIA_BBOX = (68.0, 6.0, 98.0, 37.5)  # min_lon, min_lat, max_lon, max_lat
MAX_FIELD_AREA_HA = 2000.0
MIN_FIELD_AREA_HA = 0.01
MODIS_SPHERE_RADIUS_M = 6371007.181  # MODIS sinusoidal grid sphere radius


class GeometryError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedGeometry:
    geojson: dict[str, Any]
    kind: str  # polygon | point
    centroid_lat: float
    centroid_lon: float
    bbox: tuple[float, float, float, float]  # min_lon, min_lat, max_lon, max_lat
    area_ha: float | None
    warnings: list[str]


def _equal_area_projector(lat0: float, lon0: float):  # type: ignore[no-untyped-def]
    """Lambert azimuthal equal-area on a sphere centred on the field (adequate for field-sized areas)."""
    r = 6371008.8
    phi0, lam0 = math.radians(lat0), math.radians(lon0)

    def fwd(lon: Any, lat: Any, z: Any = None) -> tuple[Any, Any]:
        import numpy as np

        phi, lam = np.radians(lat), np.radians(lon)
        k = np.sqrt(2 / (1 + math.sin(phi0) * np.sin(phi) + math.cos(phi0) * np.cos(phi) * np.cos(lam - lam0)))
        x = r * k * np.cos(phi) * np.sin(lam - lam0)
        y = r * k * (math.cos(phi0) * np.sin(phi) - math.sin(phi0) * np.cos(phi) * np.cos(lam - lam0))
        return x, y

    return fwd


def area_hectares(geom: BaseGeometry) -> float:
    c = geom.centroid
    projected = transform(_equal_area_projector(c.y, c.x), geom)
    return float(projected.area / 10_000.0)


def validate_field_geometry(geojson: dict[str, Any]) -> ValidatedGeometry:
    if not isinstance(geojson, dict) or "type" not in geojson:
        raise GeometryError("Geometry must be a GeoJSON geometry object")
    gtype = geojson.get("type")
    if gtype == "Feature":
        geojson = geojson.get("geometry") or {}
        gtype = geojson.get("type")
    if gtype not in {"Polygon", "Point"}:
        raise GeometryError("Only GeoJSON Polygon or Point geometries are supported")
    try:
        import json

        geom = from_geojson(json.dumps(geojson))
    except Exception as exc:  # shapely raises GEOSException / ValueError variants
        raise GeometryError(f"Unreadable GeoJSON geometry: {exc}") from exc
    if geom.is_empty:
        raise GeometryError("Geometry is empty")

    coords = list(geom.exterior.coords) if isinstance(geom, Polygon) else [(geom.x, geom.y)]
    for lon, lat, *_ in coords:
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise GeometryError("Coordinates out of range; GeoJSON must be [longitude, latitude]")
        if not (INDIA_BBOX[0] <= lon <= INDIA_BBOX[2] and INDIA_BBOX[1] <= lat <= INDIA_BBOX[3]):
            raise GeometryError("Location is outside the supported region (India)")

    warnings: list[str] = []
    if isinstance(geom, Point):
        warnings.append("point_only_boundary_unknown")
        return ValidatedGeometry(
            geojson=mapping(geom),  # type: ignore[arg-type]
            kind="point",
            centroid_lat=geom.y,
            centroid_lon=geom.x,
            bbox=(geom.x, geom.y, geom.x, geom.y),
            area_ha=None,
            warnings=warnings,
        )

    assert isinstance(geom, Polygon)
    if len(geom.interiors) > 0:
        warnings.append("polygon_has_holes")
    if not geom.is_valid:
        raise GeometryError(f"Invalid polygon: {explain_validity(geom)}")
    area = area_hectares(geom)
    if area < MIN_FIELD_AREA_HA:
        raise GeometryError(f"Field area {area:.4f} ha is implausibly small")
    if area > MAX_FIELD_AREA_HA:
        raise GeometryError(f"Field area {area:.0f} ha exceeds the {MAX_FIELD_AREA_HA:.0f} ha limit for a single field")
    if area < 5.4:
        warnings.append("field_smaller_than_modis_pixel")
    c = geom.centroid
    # Normalise orientation/precision: 7 decimals ≈ 1 cm.
    import json

    norm = json.loads(to_geojson(shape(mapping(geom)), indent=None))
    norm["coordinates"] = [[[round(x, 7), round(y, 7)] for x, y, *_ in ring] for ring in norm["coordinates"]]
    minx, miny, maxx, maxy = geom.bounds
    return ValidatedGeometry(
        geojson=norm,
        kind="polygon",
        centroid_lat=c.y,
        centroid_lon=c.x,
        bbox=(minx, miny, maxx, maxy),
        area_ha=round(area, 4),
        warnings=warnings,
    )


# ---------------------------------------------------------------- MODIS sinusoidal grid


def sinusoidal_forward(lat: float, lon: float) -> tuple[float, float]:
    phi, lam = math.radians(lat), math.radians(lon)
    return MODIS_SPHERE_RADIUS_M * lam * math.cos(phi), MODIS_SPHERE_RADIUS_M * phi


def sinusoidal_inverse(x: float, y: float) -> tuple[float, float]:
    phi = y / MODIS_SPHERE_RADIUS_M
    lam = x / (MODIS_SPHERE_RADIUS_M * math.cos(phi))
    return math.degrees(phi), math.degrees(lam)


@dataclass(frozen=True)
class PixelSelection:
    indices: list[int]  # row-major indices into the subset's data array
    rule: str  # "pixel_center_in_polygon" | "pixel_containing_centroid"
    total_in_window: int
    note: str | None


def select_pixels(
    geojson: dict[str, Any],
    xllcorner: float,
    yllcorner: float,
    cellsize: float,
    nrows: int,
    ncols: int,
) -> PixelSelection:
    """Choose subset pixels that represent a field.

    Rule: use pixels whose centre lies inside the field polygon. If none does (field
    smaller than a ~5.4 ha MODIS pixel, or a point location) fall back to the single
    pixel containing the field centroid and say so explicitly.

    ORNL subset arrays are row-major starting at the upper-left (north-west) pixel.
    """
    import json

    geom = from_geojson(json.dumps(geojson))
    top = yllcorner + nrows * cellsize
    inside: list[int] = []
    if isinstance(geom, Polygon):
        for r in range(nrows):
            cy = top - (r + 0.5) * cellsize
            for c in range(ncols):
                cx = xllcorner + (c + 0.5) * cellsize
                lat, lon = sinusoidal_inverse(cx, cy)
                if geom.contains(Point(lon, lat)):
                    inside.append(r * ncols + c)
    if inside:
        return PixelSelection(inside, "pixel_center_in_polygon", nrows * ncols, None)
    cen = geom.centroid
    x, y = sinusoidal_forward(cen.y, cen.x)
    col = int((x - xllcorner) // cellsize)
    row = int((top - y) // cellsize)
    if not (0 <= row < nrows and 0 <= col < ncols):
        raise GeometryError("Field centroid falls outside the retrieved MODIS subset window")
    return PixelSelection(
        [row * ncols + col],
        "pixel_containing_centroid",
        nrows * ncols,
        "No MODIS pixel centre falls inside the field; the value describes the ~5.4 ha pixel containing the field centre and may mix several land uses.",
    )

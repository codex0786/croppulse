import struct
import zlib

import pytest

from croppulse.geo.geometry import GeometryError, area_hectares, sinusoidal_forward, sinusoidal_inverse, validate_field_geometry
from croppulse.uploads import UploadError, store_photo, strip_jpeg_metadata, strip_png_metadata
from tests.fixtures.synthetic import square_polygon


def test_valid_polygon_area_and_warnings():
    g = validate_field_geometry(square_polygon(19.95, 75.9, half_deg=0.001))
    assert g.kind == "polygon"
    assert 4.0 < g.area_ha < 5.5  # ~222 m × 209 m
    assert "field_smaller_than_modis_pixel" in g.warnings


def test_point_is_accepted_with_warning():
    g = validate_field_geometry({"type": "Point", "coordinates": [75.9, 19.95]})
    assert g.kind == "point" and g.area_ha is None and "point_only_boundary_unknown" in g.warnings


@pytest.mark.parametrize(
    "geom,msg",
    [
        ({"type": "Polygon", "coordinates": [[[75.9, 19.9], [75.91, 19.91], [75.91, 19.9], [75.9, 19.91], [75.9, 19.9]]]}, "Invalid polygon"),  # bow-tie
        ({"type": "Point", "coordinates": [19.95, 75.9]}, "outside"),  # lat/lon swapped
        ({"type": "Point", "coordinates": [-0.1, 51.5]}, "outside"),
        ({"type": "LineString", "coordinates": [[75.9, 19.9], [75.91, 19.91]]}, "Only GeoJSON"),
        ({"type": "Polygon", "coordinates": [[[75.9, 19.9], [75.90001, 19.9], [75.90001, 19.90001], [75.9, 19.9]]]}, "implausibly small"),
        (square_polygon(19.95, 75.9, half_deg=0.5), "exceeds"),
        ({"foo": 1}, "GeoJSON geometry"),
    ],
)
def test_invalid_geometries_are_rejected_not_repaired(geom, msg):
    with pytest.raises(GeometryError, match=msg):
        validate_field_geometry(geom)


def test_sinusoidal_round_trip():
    x, y = sinusoidal_forward(19.88, 75.34)
    lat, lon = sinusoidal_inverse(x, y)
    assert lat == pytest.approx(19.88, abs=1e-9) and lon == pytest.approx(75.34, abs=1e-9)
    # Matches the xllcorner of the real ORNL single-pixel response (pixel containing the point).
    assert 7878169.42 <= x < 7878169.42 + 231.66 and 2210465.01 <= y < 2210465.01 + 231.66


def test_area_of_one_hectare():
    from shapely import Polygon

    d = 100 / 111320
    poly = Polygon([(75.9, 19.9), (75.9 + d / 0.9403, 19.9), (75.9 + d / 0.9403, 19.9 + d), (75.9, 19.9 + d)])
    assert area_hectares(poly) == pytest.approx(1.0, rel=0.02)


def _jpeg_with_exif() -> bytes:
    exif = b"Exif\x00\x00GPSDATA-secret-location"
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
    dqt = b"\xff\xdb" + struct.pack(">H", 4) + b"\x00\x01"
    return b"\xff\xd8" + app1 + dqt + b"\xff\xda\x00\x02" + b"imagedata" + b"\xff\xd9"


def _png_with_text() -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", b"\x00" * 13) + chunk(b"tEXt", b"GPS\x0019.95,75.9") + chunk(b"IDAT", b"x") + chunk(b"IEND", b"")


def test_jpeg_exif_is_stripped(tmp_path):
    clean = strip_jpeg_metadata(_jpeg_with_exif())
    assert b"GPSDATA" not in clean and clean.startswith(b"\xff\xd8") and b"imagedata" in clean
    stored = store_photo(_jpeg_with_exif(), tmp_path, 1024)
    assert stored.content_type == "image/jpeg" and stored.metadata_stripped
    assert b"GPSDATA" not in (tmp_path / stored.storage_key).read_bytes()


def test_png_text_is_stripped():
    clean = strip_png_metadata(_png_with_text())
    assert b"GPS" not in clean and b"IDAT" in clean


@pytest.mark.parametrize(
    "data,msg", [(b"", "Empty"), (b"GIF89a....", "Only JPEG"), (b"<?php echo 1; ?>", "Only JPEG"), (b"\xff\xd8\xff" + b"0" * 5000, "exceeds")]
)
def test_bad_uploads_rejected(tmp_path, data, msg):
    with pytest.raises(UploadError, match=msg):
        store_photo(data, tmp_path, 1024)

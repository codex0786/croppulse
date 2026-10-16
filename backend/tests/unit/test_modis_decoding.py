"""MOD13Q1 decoding, quality masking and parsing against REAL recorded ORNL responses."""

import json
from datetime import UTC, date, datetime

import pytest

from croppulse.geo.geometry import select_pixels
from croppulse.sources.base import SourceSchemaError
from croppulse.sources.modis_ornl import _check_subset, aggregate_composite, composite_period, decode_vi, parse_proc_date
from tests.conftest import RECORDED


def test_decode_vi_scale_and_fill():
    assert decode_vi(5000) == pytest.approx(0.5)
    assert decode_vi(-3000) is None  # fill
    assert decode_vi(-2001) is None  # below valid range
    assert decode_vi(10001) is None
    assert decode_vi(None) is None
    assert decode_vi(0) == 0.0  # a genuine zero is still zero


def test_missing_is_never_zero():
    nd, ev, valid, counts, ok, reason = aggregate_composite([-3000, -3000], None, [0, 0], [0, 1], {0, 1}, 0.5)
    assert nd is None and not ok and valid == 0 and reason == "no_quality_accepted_pixels"


def test_quality_mask_excludes_cloudy_and_counts_classes():
    nd, ev, valid, counts, ok, reason = aggregate_composite([6000, 2000, 7000], [3000, 1000, 3500], [0, 3, 1], [0, 1, 2], {0, 1}, 0.5)
    assert ok and valid == 2
    assert nd == pytest.approx(0.65)
    assert ev == pytest.approx(0.325)
    assert counts == {"good": 1, "cloudy": 1, "marginal": 1}


def test_valid_fraction_gate():
    nd, _, valid, _, ok, reason = aggregate_composite([6000, 2000, 7000, 5000], None, [0, 3, 3, 3], [0, 1, 2, 3], {0}, 0.5)
    assert not ok and reason == "valid_pixel_fraction_below_minimum" and valid == 1


def test_proc_date_and_composite_period():
    assert parse_proc_date("2026277222234") == datetime(2026, 10, 4, 22, 22, 34, tzinfo=UTC)
    assert parse_proc_date(None) is None
    assert parse_proc_date("garbage") is None
    assert composite_period(date(2026, 9, 14)) == (date(2026, 9, 14), date(2026, 9, 29))
    assert composite_period(date(2026, 12, 19)) == (date(2026, 12, 19), date(2026, 12, 31))


def test_real_recorded_subset_parses_and_selects_pixels():
    nd = json.loads((RECORDED / "ornl_mod13q1_250m_16_days_NDVI_A2026113_A2026257_km1.json").read_text())
    rel = json.loads((RECORDED / "ornl_mod13q1_250m_16_days_pixel_reliability_A2026113_A2026257_km1.json").read_text())
    _check_subset(nd)
    _check_subset(rel)
    assert nd["nrows"] == 9 and nd["ncols"] == 9 and len(nd["subset"]) == 10
    # A ~70 ha square around the request point contains several pixel centres.
    poly = {"type": "Polygon", "coordinates": [[[75.336, 19.876], [75.344, 19.876], [75.344, 19.884], [75.336, 19.884], [75.336, 19.876]]]}
    sel = select_pixels(poly, float(nd["xllcorner"]), float(nd["yllcorner"]), float(nd["cellsize"]), nd["nrows"], nd["ncols"])
    assert sel.rule == "pixel_center_in_polygon" and 4 <= len(sel.indices) <= 25
    # A point falls back to the centroid pixel — the centre of the 9×9 window.
    pt = {"type": "Point", "coordinates": [75.34, 19.88]}
    sel2 = select_pixels(pt, float(nd["xllcorner"]), float(nd["yllcorner"]), float(nd["cellsize"]), 9, 9)
    assert sel2.rule == "pixel_containing_centroid" and sel2.indices == [40]
    last = nd["subset"][-1]
    v, _, n, _, ok, _ = aggregate_composite(last["data"], None, rel["subset"][-1]["data"], sel.indices, {0, 1}, 0.0)
    assert n >= 0 and (v is None or -0.2 <= v <= 1.0)


def test_real_error_string_is_schema_error():
    payload = json.loads((RECORDED / "ornl_error_too_many_dates.json").read_text())
    assert isinstance(payload, str)
    with pytest.raises(SourceSchemaError):
        _check_subset(payload)

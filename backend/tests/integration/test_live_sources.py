"""LIVE tests against the real public services (no credentials). Run: make test-live.

They verify the adapters against today's real responses: schema, units, fill handling,
quality flags and latency. Skipped by default (pytest -m 'not live').
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from croppulse.sources.modis_ornl import LandCoverAdapter, ModisOrnlAdapter
from croppulse.sources.nasa_power import NasaPowerAdapter, grid_cell_for

pytestmark = pytest.mark.live
CROPLAND_POINT = (19.95, 75.95)  # research sample point S7: MCD12Q1 2024 class 12 (verified 2026-10-15)


def test_live_power_recent_window():
    s = NasaPowerAdapter().fetch(grid_cell_for(*CROPLAND_POINT), date.today() - timedelta(days=60))
    assert not s.is_synthetic and s.units["PRECTOTCORR"] == "mm/day"
    assert s.last_valid_date is not None and (date.today() - s.last_valid_date).days < 30
    assert (s.frame["PRECTOTCORR"].dropna() >= 0).all()


def test_live_modis_recent_composites():
    poly = {"type": "Polygon", "coordinates": [[[75.9465, 19.9465], [75.9535, 19.9465], [75.9535, 19.9535], [75.9465, 19.9535], [75.9465, 19.9465]]]}
    today = datetime.now(UTC).date()
    s = ModisOrnlAdapter().field_series(
        poly,
        CROPLAND_POINT,
        (75.9465, 19.9465, 75.9535, 19.9535),
        today - timedelta(days=120),
        accepted_reliability={0, 1},
        min_valid_fraction=0.5,
        window_km_min=1,
        include_evi=False,
    )
    assert s.composites and not s.is_synthetic
    latest = max(c.period_end for c in s.composites)
    assert (today - latest).days < 60, "MOD13Q1 latency larger than expected — check the service"
    assert all(c.published_at is None or c.published_at.date() >= c.period_start for c in s.composites)


def test_live_land_cover_is_cropland():
    r = LandCoverAdapter().latest(*CROPLAND_POINT)
    assert r.lc_type1 in (12, 14) and r.year >= 2023

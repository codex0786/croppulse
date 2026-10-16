from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from croppulse.ingestion.quality import check_vegetation_composites, check_weather_frame
from croppulse.sources.crop_stats import import_crop_statistics


@dataclass
class C:
    period_start: date
    ndvi: float | None
    accepted: bool
    published_at: datetime | None = None


def test_vegetation_quality_warnings():
    d0 = date(2025, 1, 1)
    comps = [
        C(d0, 0.3, True),
        C(d0 + timedelta(days=16), 0.9, True),
        C(d0 + timedelta(days=64), None, False),
        C(d0 + timedelta(days=80), 1.4, True, datetime(2024, 1, 1, tzinfo=UTC)),
    ]
    w = check_vegetation_composites(comps)
    assert any(x.startswith("ndvi_discontinuity") for x in w)
    assert any(x.startswith("composite_gap") for x in w)
    assert any(x.startswith("ndvi_out_of_range") for x in w)
    assert any(x.startswith("published_before_period") for x in w)
    assert check_vegetation_composites([]) == ["no_composites_returned"]


def test_weather_quality_warnings():
    idx = [date(2026, 1, 1) + timedelta(days=i) for i in range(10) if i != 4]
    f = pd.DataFrame({"PRECTOTCORR": [1.0] * 7 + [np.nan, np.nan], "T2M_MAX": [30.0] * 9, "T2M_MIN": [20.0] * 8 + [35.0]}, index=idx)
    w = check_weather_frame(f)
    assert "missing_dates:1" in w and "trailing_missing_days:2" in w and "tmax_below_tmin_days:1" in w


def test_crop_stats_units_yield_and_duplicates(tmp_path):
    p = tmp_path / "stats.csv"
    p.write_text(
        "State,District,Agri_Year,Season,Crop,Area,Area_Unit,Production,Production_Unit\n"
        "Maharashtra,Jalna,2019-20,Kharif,Soybean,100,'000 hectare,150,'000 tonnes\n"
        "Maharashtra,Jalna,2019-20,Kharif,Cotton,200,'000 hectare,500,'000 bales\n"
        "Maharashtra,Jalna,2019-20,Kharif,Soybean,101,'000 hectare,151,'000 tonnes\n"
    )
    r = import_crop_statistics(p)
    soy = r.frame[r.frame["crop"] == "Soybean"].iloc[0]
    assert soy["area_ha"] == 100_000 and soy["yield_t_per_ha"] == pytest.approx(1.5)
    assert pd.isna(r.frame[r.frame["crop"] == "Cotton"].iloc[0]["yield_t_per_ha"])  # bales: never converted
    assert r.frame["duplicate_key"].sum() == 2 and len(r.frame) == 3  # flagged, not dropped
    assert any("non-mass" in w for w in r.warnings) and len(r.sha256) == 64


def test_crop_stats_rejects_unknown_units(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("state,district,agri_year,season,crop,area,area_unit,production,production_unit\nM,J,2019-20,K,S,1,acres,1,tonnes\n")
    with pytest.raises(ValueError, match="Unrecognised units"):
        import_crop_statistics(p)

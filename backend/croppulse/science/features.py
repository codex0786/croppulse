"""Feature registry: one documented entry per feature used by the risk engine.

Served at GET /api/v1/features and rendered into docs/DATA_DICTIONARY.md by
scripts/generate_docs.py, so documentation cannot drift from the code silently.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    definition: str
    units: str
    source: str
    transformation: str
    availability_time: str
    missing_behavior: str
    intended_use: str
    leakage_risk: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FEATURES: list[FeatureSpec] = [
    FeatureSpec(
        "ndvi_field_mean",
        "Mean NDVI of quality-accepted MOD13Q1 pixels representing the field for one 16-day composite",
        "NDVI (dimensionless, −0.2..1.0)",
        "modis_mod13q1",
        "raw × 0.0001; fill (−3000) and out-of-range removed; pixel_reliability ∈ accepted set; "
        "pixels whose centre lies in the polygon, else the pixel containing the centroid",
        "Composite period end + provider latency (published_at = proc_date); usable from available_at",
        "NULL when no accepted pixel or valid-pixel fraction < minimum; never 0",
        "Vegetation condition time series; input to anomaly",
        "Low: value describes its own period. Provider reprocessing can change historic values (revisions are kept).",
    ),
    FeatureSpec(
        "ndvi_valid_pixel_fraction",
        "Accepted pixels / selected pixels for the composite",
        "fraction 0..1",
        "modis_mod13q1",
        "count of accepted pixels ÷ count of selected pixels",
        "Same as ndvi_field_mean",
        "0 when nothing accepted",
        "Observation-quality indicator; evidence gate",
        "None",
    ),
    FeatureSpec(
        "ndvi_robust_z",
        "(x − median_ref) / (1.4826·MAD_ref) for the same composite period in the N preceding years",
        "standardised units",
        "derived from ndvi_field_mean",
        "reference: years strictly before target year, same composite index (± pool), accepted only, available_at ≤ as_of",
        "As of the target composite's availability",
        "NULL with status insufficient_reference (n < min) or zero_variance",
        "Screening anomaly signal",
        "Guarded: future years and not-yet-available composites are excluded (tests/scientific/test_leakage.py)",
    ),
    FeatureSpec(
        "ndvi_z",
        "(x − mean_ref) / sd_ref (ddof=1), same reference as ndvi_robust_z",
        "standardised units",
        "derived from ndvi_field_mean",
        "as above",
        "As above",
        "As above",
        "Reported alongside robust z for comparison",
        "As above",
    ),
    FeatureSpec(
        "ndvi_percentile",
        "Mid-rank empirical percentile of x within the reference sample",
        "percent",
        "derived from ndvi_field_mean",
        "(count_below + 0.5·count_equal) / n × 100",
        "As above",
        "NULL if reference insufficient",
        "Screening anomaly signal; user-facing wording",
        "As above",
    ),
    FeatureSpec(
        "ndvi_low_persistence",
        "Number of most-recent consecutive usable composites with robust z ≤ threshold AND percentile ≤ threshold",
        "count of composites",
        "derived",
        "newest-first run; gap > 32 days between usable composites breaks the run",
        "As of latest composite",
        "0 when no usable composites",
        "Reduce single-composite false alarms (multiple-comparison control heuristic)",
        "None beyond inputs",
    ),
    FeatureSpec(
        "rain_{7,30,60,90}d_total",
        "Sum of daily PRECTOTCORR over the window ending at the last valid day ≤ as_of",
        "mm",
        "nasa_power_daily",
        "sum of observed days; window rejected if coverage < min_window_coverage",
        "Daily, several days latency (window_end reported)",
        "NULL when coverage is insufficient; missing days are not treated as 0 mm",
        "Rainfall context",
        "Guarded: rows after as_of dropped before computation",
    ),
    FeatureSpec(
        "rain_{w}d_percentile / deficit_pct",
        "Percentile of the window total among the same calendar window in the N preceding years; deficit relative to their mean",
        "percent",
        "derived from nasa_power_daily",
        "reference years strictly before window_end year; deficit suppressed in climatologically dry windows",
        "As above",
        "NULL if fewer than min_reference_years usable reference windows",
        "Rainfall-deficit indicator",
        "Guarded as above",
    ),
    FeatureSpec(
        "current_dry_spell_days",
        "Consecutive days with PRECTOTCORR < rainy_day_mm ending at window_end",
        "days",
        "derived from nasa_power_daily",
        "IMD rainy-day convention 2.5 mm; a missing day stops the count (flag dry_spell_truncated)",
        "As above",
        "Truncated (lower bound) when a missing day is reached",
        "Dry-spell indicator",
        "None",
    ),
    FeatureSpec(
        "heat_days",
        "Days with T2M_MAX ≥ heat threshold in the last heat_window_days",
        "days",
        "nasa_power_daily",
        "count; window rejected if coverage < minimum",
        "As above",
        "NULL if coverage insufficient",
        "Heat-exposure indicator (crop-agnostic, unvalidated threshold)",
        "None",
    ),
    FeatureSpec(
        "tmax_anomaly_c",
        "Mean T2M_MAX over the heat window minus the mean of the same window in reference years",
        "°C",
        "derived from nasa_power_daily",
        "as above",
        "As above",
        "NULL if reference insufficient",
        "Temperature anomaly context",
        "Guarded",
    ),
    FeatureSpec(
        "land_cover_igbp",
        "MCD12Q1 LC_Type1 class of the 500 m pixel containing the field centre (latest available year)",
        "IGBP class code",
        "modis_mcd12q1",
        "none",
        "Annual, > 1 year latency",
        "NULL on fill (255) or source failure",
        "Cropland-context check for representativeness",
        "Latest map may post-date historical target periods; used for context only, not in evaluation features",
    ),
    FeatureSpec(
        "days_after_sowing",
        "Assessment date minus farmer-reported sowing date",
        "days",
        "farmer_reported",
        "difference in days",
        "When the farmer records it",
        "NULL when sowing date unknown; flagged when farmer marks it uncertain",
        "Crop-stage context (stage names only from a reviewed crop calendar)",
        "Farmer-entered after the fact in backtests — exclude from historical evaluation",
    ),
]

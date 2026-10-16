"""Schema-validated import of manually downloaded district crop statistics (DES / data.gov.in).

No statistics file is bundled. The importer:
  * requires explicit unit columns and refuses unknown units;
  * computes yield = production / area ONLY when production is in tonnes and area in hectares
    (cotton bales, jute bales, coconut nuts etc. are left uncomputed);
  * preserves the raw file (checksum recorded) and flags duplicate keys instead of dropping them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = [
    "state",
    "district",
    "agri_year",  # e.g. "2019-20"
    "season",  # kharif | rabi | summer | whole_year | ... (as published)
    "crop",
    "area",
    "area_unit",
    "production",
    "production_unit",
]
AREA_UNITS = {"hectare": 1.0, "ha": 1.0, "'000 hectare": 1000.0}
TONNE_UNITS = {"tonnes": 1.0, "tonne": 1.0, "'000 tonnes": 1000.0}
NON_MASS_UNITS = {"bales", "'000 bales", "nuts", "'000 nuts"}


@dataclass
class ImportResult:
    frame: pd.DataFrame
    sha256: str
    warnings: list[str] = field(default_factory=list)
    rejected_rows: int = 0


def import_crop_statistics(path: Path) -> ImportResult:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Crop statistics file is missing columns: {missing}")
    warnings: list[str] = []
    df["area_unit"] = df["area_unit"].str.strip().str.lower()
    df["production_unit"] = df["production_unit"].str.strip().str.lower()
    unknown_area = set(df["area_unit"]) - set(AREA_UNITS)
    unknown_prod = set(df["production_unit"]) - set(TONNE_UNITS) - NON_MASS_UNITS
    if unknown_area or unknown_prod:
        raise ValueError(f"Unrecognised units: area={sorted(unknown_area)} production={sorted(unknown_prod)}")

    df["area_ha"] = pd.to_numeric(df["area"], errors="coerce") * df["area_unit"].map(AREA_UNITS)
    mass = df["production_unit"].isin(TONNE_UNITS.keys())
    df["production_t"] = pd.NA
    df.loc[mass, "production_t"] = pd.to_numeric(df.loc[mass, "production"], errors="coerce") * df.loc[mass, "production_unit"].map(TONNE_UNITS)
    df["production_t"] = pd.to_numeric(df["production_t"], errors="coerce")
    ok = mass & df["area_ha"].gt(0) & df["production_t"].notna()
    df["yield_t_per_ha"] = pd.NA
    df.loc[ok, "yield_t_per_ha"] = df.loc[ok, "production_t"] / df.loc[ok, "area_ha"]
    df["yield_t_per_ha"] = pd.to_numeric(df["yield_t_per_ha"], errors="coerce")
    if (~mass).any():
        warnings.append(f"{int((~mass).sum())} rows use non-mass production units; yield not computed for them")

    key = ["state", "district", "agri_year", "season", "crop"]
    dups = df.duplicated(key, keep=False)
    if dups.any():
        warnings.append(f"{int(dups.sum())} rows share a state/district/year/season/crop key (possible revisions); kept and flagged")
    df["duplicate_key"] = dups
    rejected = int(df["area_ha"].isna().sum())
    if rejected:
        warnings.append(f"{rejected} rows have non-numeric area")
    df["source_sha256"] = sha
    return ImportResult(df, sha, warnings, rejected)

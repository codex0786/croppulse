"""Earthdata-authenticated sources (GPM IMERG precipitation, SMAP soil moisture).

Status in this build: NOT IMPLEMENTED against the live service — no Earthdata
credentials were available, so the response format could not be verified. The
adapters expose the contract the rest of the system uses and report an honest
status. They never return placeholder values.

To complete (docs/ROADMAP.md, item "Earthdata adapters"):
  1. Create an Earthdata Login account and approve the GES DISC / NSIDC applications.
  2. Set CROPPULSE_EARTHDATA_TOKEN (a user token from urs.earthdata.nasa.gov).
  3. Implement ``fetch_daily`` using the GES DISC OPeNDAP or Harmony subsetting
     service, verify units (mm/day; m³/m³), time zone (UTC days for IMERG) and
     quality fields against a real response, then add recorded-response tests.
"""

from __future__ import annotations

from datetime import date

from croppulse.config import get_settings
from croppulse.enums import SourceStatus
from croppulse.sources.base import SourceNotConfigured


class _EarthdataAdapter:
    source_id = ""
    variable = ""

    def status(self) -> SourceStatus:
        return SourceStatus.not_configured if not get_settings().earthdata_token else SourceStatus.implemented_untested

    def fetch_daily(self, lat: float, lon: float, start: date, end: date) -> None:
        if not get_settings().earthdata_token:
            raise SourceNotConfigured(f"{self.source_id}: CROPPULSE_EARTHDATA_TOKEN is not set")
        raise SourceNotConfigured(
            f"{self.source_id}: retrieval is not implemented yet because the live response format has not been "
            "verified with real credentials (see module docstring)."
        )


class GpmImergAdapter(_EarthdataAdapter):
    source_id = "gpm_imerg"
    variable = "precipitation_mm_per_day"


class SmapAdapter(_EarthdataAdapter):
    source_id = "smap_l4"
    variable = "soil_moisture_m3_m3"

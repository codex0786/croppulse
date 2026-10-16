"""Fetch real MODIS + NASA POWER data for the public research sample points.

Usage: python scripts/research_fetch.py [S1 S2 ...]
Requires network access to modis.ornl.gov and power.larc.nasa.gov (no credentials).
"""

import sys

from croppulse.logging_setup import configure_logging
from croppulse.research.pipeline import fetch

if __name__ == "__main__":
    configure_logging("INFO")
    man = fetch(sys.argv[1:] or None)
    print(f"fetched {len(man['points'])} points, {len(man['power_cells'])} POWER cells")

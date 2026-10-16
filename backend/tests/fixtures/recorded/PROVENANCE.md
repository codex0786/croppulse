# Recorded live responses (real data)

Retrieved by the CropPulse build session on 2026-10-15 from the public, unauthenticated
endpoints below, to test parsers against the real response schema. These are genuine
NASA data products (open data). The location (19.88 N, 75.34 E) is a public
test point inside Chhatrapati Sambhajinagar city — MCD12Q1 classifies it as Urban (13) —
and is NOT a farmer's field. POWER was requested for the grid-cell centre (20.0 N, 75.625 E).

| File | Request |
|---|---|
| ornl_mod13q1_*_A2026113_A2026257_km1.json | https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset?latitude=19.88&longitude=75.34&band=<band>&startDate=A2026113&endDate=A2026257&kmAboveBelow=1&kmLeftRight=1 |
| ornl_mcd12q1_LC_Type1_A2024001.json | .../MCD12Q1/subset?...&band=LC_Type1&startDate=A2024001&endDate=A2024001&kmAboveBelow=0&kmLeftRight=0 |
| ornl_error_too_many_dates.json | a request spanning >10 composites (service returns a JSON string error) |
| power_daily_20260920_20261015.json | https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR,T2M_MAX,T2M_MIN,T2M,RH2M,ALLSKY_SFC_SW_DWN&community=AG&longitude=75.625&latitude=20.0&start=20260920&end=20261015&format=JSON |

Citations: MOD13Q1.061 DOI 10.5067/MODIS/MOD13Q1.061; MCD12Q1.061 DOI 10.5067/MODIS/MCD12Q1.061;
ORNL DAAC MODIS/VIIRS Web Service; NASA Langley Research Center POWER Project.

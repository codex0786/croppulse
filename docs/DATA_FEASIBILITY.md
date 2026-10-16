# Data feasibility assessment and pilot crop/district choice

The brief asks for the pilot crop and district to be chosen only after a feasibility assessment. This is the
assessment as far as it could be carried out in the build environment.

## Criteria and evidence

| Criterion | Evidence available now | Verdict |
|---|---|---|
| Satellite coverage over cropland | MOD13Q1 complete since 2000 at 7 Marathwada cropland sample points (see reports/DATA_COVERAGE_REPORT.md) | Feasible |
| Cloud-free observations in season | Kharif (Jun–Sep) usable-composite share is lower than dry season (coverage report) | Constraining for kharif; better for rabi |
| Weather history | POWER complete 1991→present per grid cell | Feasible |
| Field-scale resolution | 250 m pixel ≈ 5.4 ha; most Marathwada holdings are smaller | **Main limitation**: field attribution is coarse; regional/FPO-level interpretation more defensible |
| Crop masks / crop-type maps | Only MCD12Q1 generic cropland class (500 m) | Not crop-specific; needs a crop-type map or farmer-declared crop |
| Crop calendar | No reviewed official calendar loaded | Blocker for stage-aware rules |
| District statistics | DES portal identified; not downloaded | Pending manual import |
| Independent labels | None | **Blocker for validation**; must come from the pilot (expert-verified outcomes) or documented events |
| Expert review capacity | Unknown; requires a partner FPO/KVK | Pending partnership |

## Recommendation (provisional)

- **Region**: Marathwada (e.g. Jalna / Chhatrapati Sambhajinagar / Beed), which is predominantly rainfed and
  drought-prone and where all three live sources have complete coverage.
- **Crop**: **Kharif soybean or cotton** as candidates (large, contiguous rainfed area is more likely to fill 250 m
  pixels). Final choice should follow (a) DES district area statistics, (b) a partner's ability to provide expert
  verification, and (c) a crop-type map or reliable farmer declarations. Rabi crops have better cloud-free coverage
  but smaller irrigated areas — evaluate both once statistics are imported.
- **Unit of analysis for validation**: FPO cluster / village of enrolled fields rather than individual small plots,
  until higher-resolution imagery (Sentinel-2, 10–20 m) is integrated.

This is not yet a final decision: steps (a)–(c) require external data access and a partner.

# Model card — `screening-rules` v0.1.0

| Field | Value |
|---|---|
| Type | Transparent rule set over derived indicators (no learned parameters) |
| Status | **research — NOT approved for operational decisions** (`risk.model_validated: false`) |
| Code | `backend/croppulse/risk/engine.py` |
| Configuration | `config/science.yaml` (`screening-rules-0.1-unvalidated`); config hash stored on every assessment |
| Inputs | MODIS MOD13Q1 NDVI (field aggregate, quality-screened), NASA POWER daily rain/Tmax, MCD12Q1 land cover, farmer-declared crop/season/sowing, farmer reports, expert verifications |
| Outputs | Screening state, evidence-sufficiency status and checks, explanations generated from inputs, uncertainty descriptors, freshness, approved process-guidance ids, escalation flag. **No probability.** |
| Training data | None (rules) |
| Evaluation | Descriptive unlabelled backtest at public sample points (reports/BASELINE_BACKTEST.md). **No accuracy has been measured.** |

## Intended use

A prompt for a farmer, FPO or agronomist to look at a field or area when satellite greenness is unusually low for the
time of year and/or weather is unusual; routing of potentially affected fields to expert review; transparent evidence
summaries.

## Excluded uses

Crop-loss or yield assessment; insurance claim decisions; credit decisions; drought declaration or any official
determination; pest, disease or nutrient diagnosis; prescribing pesticides, fertilisers or irrigation; automated
decisions about individuals.

## Known limitations

- Unvalidated thresholds; unknown false-alarm and miss rates.
- 250 m MODIS pixels are larger than many fields; mixed pixels; ORNL subsets show repeated neighbouring values.
- 16-day composites with 2–4 week latency; heavy kharif cloud reduces usable composites.
- Calendar-date (not crop-stage) baseline; crop rotation and sowing shifts between years cause false signals.
- POWER weather is ~50 km reanalysis; local convective rain is smoothed.
- Soil moisture and IMERG not integrated.

## Ethical considerations

False alarms can cause unnecessary input spending; missed events can create false reassurance. Mitigations: every
output shows uncertainty, data age and alternative explanations; "insufficient evidence" is the default when data are
missing; only process guidance is shown; experts review elevated cases; outputs are never presented as official.

## Versioning and rollback

Model name/version and config hash are written to every assessment and alert. Changing `config/science.yaml` changes
the config hash. Rollback = redeploy the previous code tag and configuration; historical assessments remain traceable.

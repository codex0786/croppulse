# Pilot and field-validation protocol (16 weeks)

Goal: collect **independent, expert-verified outcomes** and usability evidence; decide whether the screening method
merits validation as a model. A full season is needed for any impact or yield claim.

## Pre-conditions

Partner FPO/KVK with agronomists; ethics/consent process; legal review of data handling (DPDP); named data
protection contact; crop and district chosen per DATA_FEASIBILITY.md.

## Weeks 1–2 — feasibility & co-design
Import DES statistics for candidate districts; confirm crop; agree outcome definitions with agronomists
(what counts as "stress confirmed", minimum inspection standard, photo protocol); define the pre-registered
evaluation (VALIDATION_PROTOCOL.md §7).

## Weeks 3–5 — data & science
Run `make research-fetch` / real fields for the pilot area; produce coverage report for the pilot season; freeze
`config/science.yaml` for the season (hash recorded).

## Weeks 6–9 — application & workflows
Translate and **review** Marathi strings and guidance with agronomists and native speakers; enrol 30–100 farmers
with informed consent (paper + app); train experts on the case console.

## Weeks 10–12 — controlled usability & field testing
- **Sampling for labels (key design choice):** inspect not only alerted fields. Each fortnight agronomists visit
  (a) all `elevated`/`expert_review` fields, (b) a random sample of `watch`, and (c) a random sample of
  `normal`/`insufficient` fields. Without (b) and (c) recall and false-negative rates cannot be estimated.
- Record verified findings in the console (method = field_inspection).
- Comprehension tests: can farmers explain the state, its uncertainty and the data age? (task-based, recorded)
- Log false alarms, missed problems, missing-data cases and usability failures.

## Weeks 13–16 — operational pilot
Reliability fixes; alert-rule refinement on training weeks only; security checks; write an honest pilot evaluation
(including null results).

## Metrics
Scientific (with labels): precision/recall/PR-AUC vs seasonal baseline, false alerts per field-season, lead time.
Farmer: registration completion, comprehension, report submission success, repeat use. Expert: time to review,
agreement, insufficient-evidence referrals. Operational: source availability, freshness, ingestion success, API errors.
Engagement is not impact: yield/income effects need a separate, properly designed study.

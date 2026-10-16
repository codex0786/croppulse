# Security and privacy

## Data classification

| Data | Sensitivity | Where |
|---|---|---|
| Field boundaries, centroids | High (precise location) | `fields` (DB only; never in logs or public endpoints) |
| Farmer identity (name, email) | High | `users` |
| Farmer reports, photos | High | `farmer_reports`, `data/uploads` (random names, metadata stripped) |
| Assessments, alerts, cases | Medium | DB |
| Source data (MODIS, POWER) | Public | `data/raw`, `data/processed` |
| Research sample points | Public, not personal | config/research_points.yaml |

## Controls implemented (with tests in `backend/tests/security/`)

- **Authentication**: PBKDF2-SHA256 (600 000 iterations) password hashes; HMAC-SHA256 bearer tokens, 12 h expiry;
  constant-time comparisons; production refuses to start without a ≥ 32-char secret or with SQLite.
- **Authorisation** (`croppulse/governance.py`): owner-only writes; org access requires the owner's
  `share_with_organization` consent and same organisation; case access requires `expert_review` consent and same org;
  admins read-only on fields and every delegated read is audited; regional/research roles get aggregates only.
  404 for unauthorised resources. Self-registration can only create farmers.
- **Consent**: append-only `consent_records` with policy version; latest record wins; withdrawal is immediate.
  Purposes: core_service, share_with_organization, expert_review, aggregated_research, notifications.
- **Data minimisation**: no phone/address/ID numbers collected; weather requested for grid-cell centres, not fields;
  regional outputs suppress groups < 3 fields and never include ids or coordinates; org CSV export aggregated.
- **Uploads**: type by magic bytes (JPEG/PNG only), 5 MB limit, 5 per report, EXIF/XMP/PNG text chunks stripped,
  random storage keys outside the web root.
- **Logging**: JSON logs with key- and pattern-based redaction of passwords, tokens, emails and coordinates (≥ 3 decimals);
  validation errors never echo input; no stack traces in responses (request id instead).
- **Rate limiting**: login (10/min/client by default) and registration (5/min/client); in-process (single instance).
- **Headers**: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`
  on API; HSTS in production; CORS restricted to configured origins.
- **Audit**: logins (success/denied), field create/delete/boundary change, delegated reads, consent changes, report/photo
  creation, case actions and verification, exports, regional queries, advisory entry.
- **Secrets**: only in environment / `.env` (gitignored); `.env.example` has placeholders only.

## Known gaps (to do before any real pilot)

- Tokens in `sessionStorage` are readable by injected scripts → move to httpOnly, SameSite cookies + CSRF tokens; add
  a Content-Security-Policy; token revocation on logout/password change.
- No password reset / account recovery flow; no MFA for experts and admins.
- Rate limiter is per-process; use a shared store behind a load balancer.
- Deletion requests are recorded but processed manually; implement the deletion job (see below).
- Uploaded photos are not virus-scanned and not encrypted at rest beyond the disk.
- Offline caches in `localStorage` hold field data on the device (cleared on logout); shared phones are a risk.
- No independent penetration test or DPDP legal review has been done.

## Retention and deletion (policy to implement)

| Data | Retention | Deletion |
|---|---|---|
| Account, fields, reports, photos | While account active | On verified deletion request: hard-delete reports/photos, soft-delete then purge fields after 30 days, anonymise `audit_events.actor_id` |
| Verified outcomes | Kept for evaluation | De-identified (field geometry removed, coarse grid cell retained) on account deletion |
| Raw public source data | Indefinitely | n/a |
| Logs | 90 days | Rotation |

## Indian law

The Digital Personal Data Protection Act, 2023 and its Rules govern this processing (consent-based processing, notice,
purpose limitation, rights to access/correction/erasure, breach notification, Data Fiduciary obligations). The controls
above are designed with these principles in mind, but **CropPulse has not been reviewed for legal compliance**. A
qualified legal review of the current Rules and of partner data-sharing agreements is required before collecting real
farmer data.

## Guidance

Farmer-facing guidance in this build is limited to **process guidance** (check the field, report, request expert
review, explanation of what satellite data can and cannot show). It contains no treatment, input, dosage or
irrigation prescriptions and is approved under this policy by the project, not by an agronomist. Agronomic guidance
requires an official source and named agronomist approval before `approval_status: approved`, and translations require
review before they are shown as primary text.

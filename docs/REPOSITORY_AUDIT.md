# Repository audit (Phase 0)

Date: 2026-10-15. Auditor: CropPulse build session.

## What was found

The working directory supplied for this task (`~/Downloads/rcsa2`) is **not a CropPulse repository** and is not a
Git repository. It contains two unrelated projects:

| Path | What it is | Relevance to CropPulse |
|---|---|---|
| `rcsa2/` (root) | "RCSA Ledger — Accounts Payable Pilot": Next.js 14 + TypeScript app with a JSON-file store (`data/db.json`), LLM gateway, governance rules. `.env.local` contains API keys. | None (finance/risk-control domain). Not modified. |
| `rcsa2/india-policy-evaluation/` | Separate Python project (own `.git`, Makefile, Docker) for Indian policy evaluation. | None directly. Not modified. |

No existing crop, geospatial, satellite or agricultural code, data, tests, schema or deployment configuration
exists. There was therefore nothing to reuse functionally, and nothing to break.

### Decision

CropPulse was created as a **new, self-contained project in `rcsa2/croppulse/`** with its own Git repository, so that:

- the RCSA app and the policy project are untouched (no shared dependencies, configs or data);
- CropPulse can be moved to its own location or remote without history from unrelated work.

The only change outside `croppulse/` is an additive entry in `rcsa2/.claude/launch.json` (two dev-server
configurations, `croppulse-api` and `croppulse-web` on port 3100) so the desktop preview can start CropPulse;
the existing `rcsa-dev` entry is unchanged.

### Environment observed

| Item | Finding |
|---|---|
| Python | 3.12 (used), 3.11, 3.14 available via Homebrew |
| Node | v26 (web built with Next.js 14.2.35 / React 18.3.1) |
| PostgreSQL | 18.3 local server, **no PostGIS extension available** |
| Docker | CLI present, **daemon not running** (compose file validated with `docker compose config`, images not built) |
| Network | NASA POWER and ORNL DAAC MODIS web services reachable without credentials (verified live) |
| Earthdata credentials | none available → GPM IMERG and SMAP cannot be integrated live |

## Security observations (pre-existing, outside CropPulse)

- `rcsa2/.env.local` holds third-party API keys in plain text. It is gitignored by that project but sits in a
  Downloads folder; consider moving secrets to a secret manager and rotating keys if the folder was ever shared.
- `rcsa2/data/db.json` stores client data in a JSON file without access control.

These were noted, not changed (out of scope).

## Gaps relative to the CropPulse brief (all addressed or documented in this build)

| Capability | Status after this build |
|---|---|
| Data pipeline (MODIS, POWER, land cover) | Implemented; live-tested |
| Earthdata sources (IMERG, SMAP) | Contract + honest `not_configured` status; awaiting credentials |
| IMD | Manual official-advisory workflow (no scraping) |
| Crop statistics (DES) | Schema-validated manual importer; no file imported; yield prediction disabled |
| District boundaries | Not imported; regional aggregation by registered district + coarse grid |
| Anomaly science, leakage control | Implemented + tested |
| Risk engine + evidence gate | Implemented (rules, unvalidated) |
| Evaluation framework | Implemented; real-data descriptive backtest; labelled evaluation blocked on labels |
| Farmer / expert / FPO / regional / research / admin UI | Implemented (Next.js) |
| Auth, RBAC, consent, audit | Implemented + security tests |
| Docker / CI | Written; compose validated; images not built here (daemon off) |

## Prioritised backlog at audit time

1. Executable backend foundation (config, schema, migrations, health) — done.
2. Live MODIS + POWER adapters with provenance — done.
3. Leakage-safe anomaly + weather features — done.
4. Risk engine with abstention — done.
5. Farmer registration → field intelligence → report → expert review vertical slice — done.
6. Evaluation framework + real-data coverage report — done (labels missing).
7. Docs, Docker, CI — done (Docker unverified).
See `docs/ROADMAP.md` for what remains.

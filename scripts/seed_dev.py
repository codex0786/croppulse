"""Seed a LOCAL DEVELOPMENT database with demo organisations, users and fields.

    python scripts/seed_dev.py [--synthetic-demo] [--real-demo]

* Refuses to run when CROPPULSE_ENVIRONMENT=production.
* Generates random passwords and writes them to data/dev_credentials.txt (gitignored,
  mode 600). Nothing is printed to the console except the file path.
* --synthetic-demo : a field fed by LABELLED synthetic fixtures (shows the alert →
  report → expert workflow). Everything about it is flagged synthetic in the UI.
* --real-demo      : a demo field on public research sample point S7 (MODIS cropland
  pixel; NOT a farm), ingested from the live NASA services. Reuses the raw-response
  cache from `make research-fetch` when available; otherwise takes ~30 minutes.
"""

from __future__ import annotations

import argparse
import os
import secrets
import stat
from datetime import timedelta

from croppulse.config import config_version, get_settings
from croppulse.db import get_sessionmaker, utcnow
from croppulse.enums import ConsentPurpose, Role
from croppulse.geo.geometry import validate_field_geometry
from croppulse.governance import record_consent
from croppulse.ingestion.jobs import ingest_field
from croppulse.models import CropSeason, Field, ModelVersion, Organization, User
from croppulse.risk.engine import MODEL_NAME, MODEL_VERSION
from croppulse.risk.service import open_report_case, run_assessment
from croppulse.security import hash_password
from sqlalchemy import select

DOMAIN = "demo.croppulse.in"


def _user(
    s, creds, role: Role, local: str, org: Organization | None, name: str
) -> User:
    email = f"{local}@{DOMAIN}"
    u = s.scalars(select(User).where(User.email == email)).first()
    if u is None:
        pw = secrets.token_urlsafe(12)
        u = User(
            email=email,
            display_name=name,
            password_hash=hash_password(pw),
            role=role,
            organization_id=org.id if org else None,
        )
        s.add(u)
        s.flush()
        record_consent(s, u.id, ConsentPurpose.core_service, True)
        creds.append(f"{role.value:17s} {email}  {pw}")
    return u


def _field(
    s, owner: User, name: str, geom: dict, district: str, synthetic: bool
) -> Field:
    g = validate_field_geometry(geom)
    f = Field(
        owner_id=owner.id,
        organization_id=owner.organization_id,
        name=name,
        district=district,
        geometry_geojson=g.geojson,
        geometry_source="drawn",
        centroid_lat=g.centroid_lat,
        centroid_lon=g.centroid_lon,
        min_lon=g.bbox[0],
        min_lat=g.bbox[1],
        max_lon=g.bbox[2],
        max_lat=g.bbox[3],
        area_ha=g.area_ha,
        is_synthetic=synthetic,
    )
    s.add(f)
    s.flush()
    s.add(
        CropSeason(
            field_id=f.id,
            crop="soybean",
            season="kharif",
            season_year=utcnow().year,
            sowing_date=None,
            sowing_date_uncertain=True,
            irrigation="rainfed",
        )
    )
    s.commit()
    return f


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic-demo", action="store_true")
    ap.add_argument("--real-demo", action="store_true")
    args = ap.parse_args()
    settings = get_settings()
    if settings.environment == "production":
        raise SystemExit("Refusing to seed a production database.")
    s = get_sessionmaker()()
    creds: list[str] = []
    org = s.scalars(
        select(Organization).where(Organization.name == "Demo FPO (development only)")
    ).first()
    if org is None:
        org = Organization(
            name="Demo FPO (development only)",
            kind="fpo",
            state="Maharashtra",
            district="Jalna",
        )
        s.add(org)
        s.flush()
    farmer = _user(s, creds, Role.farmer, "farmer", org, "Demo Farmer")
    _user(s, creds, Role.agronomist, "agronomist", org, "Demo Agronomist")
    _user(s, creds, Role.fpo_manager, "fpo", org, "Demo FPO Manager")
    _user(s, creds, Role.regional_analyst, "analyst", None, "Demo Regional Analyst")
    _user(s, creds, Role.researcher, "researcher", None, "Demo Researcher")
    _user(s, creds, Role.admin, "admin", None, "Demo Admin")
    for p in (
        ConsentPurpose.share_with_organization,
        ConsentPurpose.expert_review,
        ConsentPurpose.aggregated_research,
    ):
        record_consent(s, farmer.id, p, True)
    if not s.scalars(
        select(ModelVersion).where(
            ModelVersion.name == MODEL_NAME, ModelVersion.version == MODEL_VERSION
        )
    ).first():
        s.add(
            ModelVersion(
                name=MODEL_NAME,
                version=MODEL_VERSION,
                kind="rules",
                status="research",
                config_hash=config_version(settings.science_config_path),
                intended_use="Screening prompt to inspect a field: flags unusual MODIS NDVI relative to the same 16-day period in earlier years, "
                "corroborated by NASA POWER rainfall/heat indicators. Elevated cases are routed to an agronomist.",
                excluded_uses="Not for crop-loss assessment, insurance claims, credit decisions, drought declaration, pesticide/fertiliser "
                "prescription or any automated decision. Not validated against independent outcomes.",
                training_refs=[],
                evaluation_run_ids=[],
            )
        )
    s.commit()

    if args.synthetic_demo:
        from croppulse.devtools.synthetic import SyntheticWorld, square_polygon
        from croppulse.models import FarmerReport
        from croppulse.sources import base

        w = SyntheticWorld(
            anomaly_year=utcnow().year,
            anomaly_from=utcnow().date() - timedelta(days=90),
            rain_scale_target_year=0.0,
        )
        base.default_transport = w.transport()
        f = _field(
            s,
            farmer,
            "SYNTHETIC demo field (test data)",
            square_polygon(19.40, 75.40),
            "Jalna",
            True,
        )
        ingest_field(s, f)
        run_assessment(s, f)
        rep = FarmerReport(
            field_id=f.id,
            reporter_id=farmer.id,
            symptoms=["wilting"],
            description="Synthetic demo report",
            observed_on=utcnow().date(),
            affected_fraction="quarter_half",
            request_expert=True,
        )
        s.add(rep)
        s.flush()
        open_report_case(s, f, rep)
        s.commit()
        run_assessment(s, f)
        base.default_transport = None

    if args.real_demo:
        h = 0.0035  # same footprint as research point S7 so cached raw responses are reused
        lat, lon = 19.95, 75.95
        geom = {
            "type": "Polygon",
            "coordinates": [
                [
                    [lon - h, lat - h],
                    [lon + h, lat - h],
                    [lon + h, lat + h],
                    [lon - h, lat + h],
                    [lon - h, lat - h],
                ]
            ],
        }
        f = _field(
            s,
            farmer,
            "Demo: public sample point S7 (cropland pixel, not a farm)",
            geom,
            "Jalna",
            False,
        )
        jobs = ingest_field(
            s, f, start_year=2002
        )  # same chunking as the research fetch → cache hits
        run_assessment(s, f)
        print(
            "real demo ingestion:", ", ".join(f"{j.source_id}={j.status}" for j in jobs)
        )

    if creds:
        path = settings.data_dir / "dev_credentials.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(
                "# CropPulse LOCAL DEVELOPMENT accounts — do not reuse these passwords anywhere\n"
            )
            fh.write("\n".join(creds) + "\n")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        print(
            f"Created {len(creds)} development account(s); credentials written to {path}"
        )
    else:
        print("Development accounts already exist; see data/dev_credentials.txt")


if __name__ == "__main__":
    main()

"""Ingestion idempotency, revisions, source failures, assessment persistence and alert controls.

All external responses are SYNTHETIC fixtures served by tests/fixtures/synthetic.py.
"""

from datetime import timedelta

from sqlalchemy import func, select

from croppulse.alerting.engine import deliver_pending, evaluate_assessment
from croppulse.db import utcnow
from croppulse.enums import ConsentPurpose, Role, SourceStatus
from croppulse.geo.geometry import validate_field_geometry
from croppulse.ingestion.jobs import ingest_field, ingest_field_vegetation
from croppulse.models import Alert, CropSeason, DataSource, Field, NotificationDelivery, Observation, RiskAssessment
from croppulse.risk.service import run_assessment
from tests.fixtures.synthetic import square_polygon


def make_field(session, owner, lat=19.95, lon=75.9):
    g = validate_field_geometry(square_polygon(lat, lon))
    f = Field(owner_id=owner.id, organization_id=owner.organization_id, name="syn", district="Jalna", geometry_geojson=g.geojson, geometry_source="drawn",
              centroid_lat=g.centroid_lat, centroid_lon=g.centroid_lon, min_lon=g.bbox[0], min_lat=g.bbox[1], max_lon=g.bbox[2], max_lat=g.bbox[3], area_ha=g.area_ha)
    session.add(f)
    session.flush()
    session.add(CropSeason(field_id=f.id, crop="soybean", season="kharif", season_year=utcnow().year, irrigation="rainfed"))
    session.commit()
    return f


def test_ingestion_is_idempotent_and_labelled_synthetic(session, actors, world):
    farmer, _ = actors.user(Role.farmer, "f1@pilot.croppulse.in", actors.org)
    f = make_field(session, farmer)
    jobs = ingest_field(session, f)
    assert [j.status for j in jobs].count("failed") == 0
    n1 = session.scalar(select(func.count()).select_from(Observation))
    assert n1 > 300
    assert session.scalar(select(func.count()).select_from(Observation).where(Observation.is_synthetic.is_(False))) == 0
    assert session.get(DataSource, "modis_mod13q1").status == SourceStatus.fixture_only
    assert session.get(Field, f.id).is_synthetic
    job2 = ingest_field_vegetation(session, f)
    assert job2.records_written == 0 and job2.records_unchanged == n1 - 1  # minus land cover row
    assert session.scalar(select(func.count()).select_from(Observation)) == n1


def test_provider_revision_creates_new_revision_not_overwrite(session, actors, world):
    farmer, _ = actors.user(Role.farmer, "f2@pilot.croppulse.in", actors.org)
    f = make_field(session, farmer)
    ingest_field_vegetation(session, f)
    world.noise = 0.03  # provider "reprocessed" — values change
    job = ingest_field_vegetation(session, f)
    assert job.checkpoint["revised"] > 0
    revised = session.scalars(select(Observation).where(Observation.revision == 2)).first()
    old = session.scalars(select(Observation).where(Observation.field_id == f.id, Observation.period_start == revised.period_start, Observation.variable == revised.variable, Observation.revision == 1)).one()
    assert old.is_current is False and revised.is_current is True


def test_source_outage_records_failure_and_creates_no_data(session, actors, world):
    world.modis_fail = True
    world.power_fail = True
    farmer, _ = actors.user(Role.farmer, "f3@pilot.croppulse.in", actors.org)
    f = make_field(session, farmer)
    jobs = ingest_field(session, f)
    assert all(j.status == "failed" for j in jobs)
    assert session.scalar(select(func.count()).select_from(Observation)) == 0
    assert session.get(DataSource, "modis_mod13q1").status == SourceStatus.unavailable
    ra, decision, _ = run_assessment(session, f)
    assert ra.state == "insufficient_evidence"
    assert decision.outcome in ("no_rule",)  # ingestion failure never creates an alert
    assert session.scalar(select(func.count()).select_from(Alert)) == 0


def test_outage_after_success_keeps_old_data_and_marks_stale(session, actors, world):
    farmer, _ = actors.user(Role.farmer, "f4@pilot.croppulse.in", actors.org)
    f = make_field(session, farmer)
    ingest_field(session, f)
    first = session.scalars(select(Observation).where(Observation.variable == "NDVI").order_by(Observation.period_start.desc())).first()
    world.modis_fail = True
    ingest_field_vegetation(session, f)
    again = session.get(Observation, first.id)
    assert again.retrieved_at == first.retrieved_at  # original timestamp preserved
    # Assessed 90 days later the same data are stale and cannot support an alert.
    ra, decision, _ = run_assessment(session, f, as_of=utcnow() + timedelta(days=90))
    assert ra.freshness["vegetation"]["status"] == "stale"
    assert decision.outcome != "created"


def test_alert_dedupe_cooldown_escalation_and_consent(session, actors, world):
    world.anomaly_year = utcnow().year
    world.anomaly_from = utcnow().date() - timedelta(days=90)
    world.rain_scale_target_year = 0.0
    farmer, _ = actors.user(Role.farmer, "f5@pilot.croppulse.in", actors.org, consents=(ConsentPurpose.expert_review,))
    f = make_field(session, farmer)
    ingest_field(session, f)
    ra1, d1, res = run_assessment(session, f)
    assert ra1.state == "elevated_risk", (ra1.state, res.indicators, [c.__dict__ for c in res.checks])
    assert d1.outcome == "created" and d1.alert.requires_expert
    # same condition again → suppressed duplicate
    ra2, d2, _ = run_assessment(session, f)
    assert d2.outcome == "suppressed_duplicate"
    assert session.scalar(select(func.count()).select_from(Alert)) == 1
    # email delivery suppressed without notification consent; in-app sent
    channels = {d.channel: d.status for d in session.scalars(select(NotificationDelivery)).all()}
    assert channels == {"in_app": "sent", "email": "suppressed"}
    # escalation supersedes
    ra2.state = "expert_review_recommended"
    d3 = evaluate_assessment(session, ra2, f)
    assert d3.outcome == "escalated" and session.get(Alert, d1.alert.id).status == "superseded"
    # after expiry, the same severity inside the cooldown window is suppressed
    session.commit()
    d4 = evaluate_assessment(session, ra2, f, now=utcnow() + timedelta(days=17))
    assert d4.outcome == "created"  # 17 days > 14-day cooldown and old alert expired
    d5 = evaluate_assessment(session, ra2, f, now=utcnow() + timedelta(days=17, hours=1))
    assert d5.outcome == "suppressed_duplicate"


def test_notification_delivery_with_consent_and_retry(session, actors, world, monkeypatch):
    world.anomaly_year = utcnow().year
    world.anomaly_from = utcnow().date() - timedelta(days=90)
    world.rain_scale_target_year = 0.0
    farmer, _ = actors.user(Role.farmer, "f6@pilot.croppulse.in", actors.org, consents=(ConsentPurpose.notifications,))
    f = make_field(session, farmer)
    ingest_field(session, f)
    run_assessment(session, f)

    class Flaky:
        name = "flaky"
        calls = 0

        def send(self, user, alert):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise RuntimeError("smtp down")

    assert deliver_pending(session, Flaky()) == {"sent": 0, "failed": 1, "skipped": 0}
    assert deliver_pending(session, Flaky()) == {"sent": 1, "failed": 0, "skipped": 0}
    email = session.scalars(select(NotificationDelivery).where(NotificationDelivery.channel == "email")).one()
    assert email.status == "sent" and email.attempts == 2


def test_escalation_opens_case_only_with_consent(session, actors, world):
    from croppulse.models import ExpertCase

    world.anomaly_year = utcnow().year
    world.anomaly_from = utcnow().date() - timedelta(days=90)
    world.rain_scale_target_year = 0.0
    no_consent, _ = actors.user(Role.farmer, "f7@pilot.croppulse.in", actors.org)
    f = make_field(session, no_consent)
    ingest_field(session, f)
    run_assessment(session, f)
    assert session.scalar(select(func.count()).select_from(ExpertCase)) == 0
    assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 1
